from __future__ import annotations

import logging
import re
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder

from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import ExtensionEventBatch, SkillDefinition
from app.command_center.system_connections import (
    ConnectionHandshakeStore,
    SystemCredentialStore,
)


logger = logging.getLogger(__name__)

_EXTENSION_ABORT_MESSAGES = {
    "no_uploadable_evidence": "浏览器未采集到可用证据，请重新录制。",
    "upload_failed": "浏览器录制证据上传失败，请稍后重试。",
}
_SENSITIVE_FAILURE_TEXT = re.compile(
    r"authorization|cookie|credential|token|api\s*key|password|captcha|"
    r"local.?storage|file.?content",
    re.IGNORECASE,
)


def _safe_prior_analysis_reasons(recording: dict[str, Any]) -> list[str]:
    result = recording.get("api_learning_result")
    if not isinstance(result, dict):
        return []
    reasons = result.get("failure_reasons")
    if not isinstance(reasons, list):
        return []
    safe: list[str] = []
    for value in reasons:
        if not isinstance(value, str):
            continue
        reason = value.strip()[:300]
        if not reason or _SENSITIVE_FAILURE_TEXT.search(reason):
            continue
        safe.append(reason)
        if len(safe) == 5:
            break
    return safe


class CommandCenterService:
    def __init__(
        self,
        *,
        repository: CommandCenterRepository,
        recorder: Any,
        learning_graph: Any,
        execution_graph: Any,
        extension_recorder: Any | None = None,
        system_profiles: dict[str, Any] | None = None,
        learning_graph_factory: Any | None = None,
        browser_skill_distiller: Any | None = None,
        system_credential_store: SystemCredentialStore | None = None,
        connection_handshakes: ConnectionHandshakeStore | None = None,
        system_skill_tester_factory: Any | None = None,
        purchase_tracking_graph_factory: Callable[[], Any] | None = None,
    ):
        self.repository = repository
        self.recorder = recorder
        self.learning_graph = learning_graph
        self.execution_graph = execution_graph
        self.extension_recorder = extension_recorder
        self.system_profiles = system_profiles or {}
        self.learning_graph_factory = learning_graph_factory
        self.browser_skill_distiller = browser_skill_distiller
        self.system_credential_store = system_credential_store
        self.connection_handshakes = connection_handshakes
        self.system_skill_tester_factory = system_skill_tester_factory
        self.purchase_tracking_graph_factory = purchase_tracking_graph_factory
        self._analysis_lock = threading.Lock()
        self._active_analyses: set[UUID] = set()

    def begin_system_connection(self, system_code: str) -> dict[str, Any]:
        profile = self._system_profile(system_code)
        if self.connection_handshakes is None:
            raise RuntimeError("system connections are not configured")
        return {
            "system_code": system_code,
            "display_name": profile.display_name,
            "connection_token": self.connection_handshakes.begin(system_code),
        }

    def put_system_credential(
        self,
        system_code: str,
        name: str,
        secret: Any,
        connection_token: str,
    ) -> dict[str, Any]:
        self._system_profile(system_code)
        if (
            self.connection_handshakes is None
            or not self.connection_handshakes.authorize(system_code, connection_token)
        ):
            raise PermissionError("connection authorization failed")
        if self.system_credential_store is None:
            raise RuntimeError("system credential storage is not configured")
        self.system_credential_store.put(system_code, name, secret)
        return self.get_system_connection(system_code)

    def get_system_connection(self, system_code: str) -> dict[str, Any]:
        profile = self._system_profile(system_code)
        connected = bool(
            self.system_credential_store
            and self.system_credential_store.has(system_code)
        )
        return {
            "system_code": system_code,
            "display_name": profile.display_name,
            "status": "connected" if connected else "disconnected",
            "credential_source": "windows_keyring",
        }

    def disconnect_system(self, system_code: str) -> dict[str, Any]:
        self._system_profile(system_code)
        if self.system_credential_store is not None:
            self.system_credential_store.delete(system_code)
        if self.connection_handshakes is not None:
            self.connection_handshakes.clear(system_code)
        return self.get_system_connection(system_code)

    def verify_latest_system_skill(self, system_code: str) -> dict[str, Any]:
        self._system_profile(system_code)
        if not (
            self.system_credential_store
            and self.system_credential_store.has(system_code)
        ):
            raise ValueError("system connection is not available")
        if self.system_skill_tester_factory is None:
            raise RuntimeError("system Skill verification is not configured")

        candidate_ids = {
            (str(skill.skill_id), skill.version)
            for skill in self.repository.list_candidate_skills()
        }
        candidates: list[tuple[dict[str, Any], SkillDefinition, list[dict[str, Any]]]] = []
        for recording in self.repository.list_recordings():
            if (
                recording.get("source_system") != system_code
                or recording.get("status") != "api_candidate"
            ):
                continue
            learning_result = recording.get("learning_result")
            if not isinstance(learning_result, dict):
                continue
            candidate_payload = learning_result.get("candidate_skill")
            test_plan = learning_result.get("test_plan")
            if not isinstance(candidate_payload, dict) or not isinstance(test_plan, list):
                continue
            skill = SkillDefinition.model_validate(candidate_payload)
            if (str(skill.skill_id), skill.version) not in candidate_ids:
                continue
            cases = [case for case in test_plan if isinstance(case, dict)]
            candidates.append((recording, skill, cases))
        if not candidates:
            raise KeyError(f"no API candidate for system: {system_code}")

        recording, skill, test_plan = max(
            candidates,
            key=lambda item: str(item[0].get("created_at", "")),
        )
        if any(step.side_effect != "read" for step in skill.steps):
            raise ValueError("only read-only API candidates can be verified")
        categories = {
            str(case.get("category", ""))
            for case in test_plan
        }
        if categories != self.repository.REQUIRED_TESTS:
            raise ValueError("candidate must contain all required read-only tests")

        tester = self.system_skill_tester_factory(system_code)
        results: list[dict[str, Any]] = []
        for case in test_plan:
            result = tester.run(skill, case)
            results.append(result)
            self.repository.save_test_result(
                skill.skill_id,
                skill.version,
                str(result["category"]),
                str(result["status"]),
                result,
            )

        passed = {
            str(result.get("category", ""))
            for result in results
            if result.get("status") == "passed"
            and result.get("unknown_side_effect") is not True
        }
        verified = passed == self.repository.REQUIRED_TESTS
        if verified:
            skill = self.repository.mark_verified_candidate(
                skill.skill_id, skill.version
            )

        learning_result = dict(recording["learning_result"])
        learning_result.update(
            {
                "candidate_skill": skill.model_dump(mode="json"),
                "test_results": results,
                "final_status": (
                    "verified_candidate" if verified else "api_candidate"
                ),
                "execution_verification": (
                    "verified_live" if verified else "failed_live"
                ),
            }
        )
        recording["learning_result"] = learning_result
        recording["status"] = (
            "verified_candidate" if verified else "api_candidate"
        )
        recording["analysis_stage"] = "completed"
        recording["verification_finished_at"] = datetime.now(UTC).isoformat()
        self._save_recording(UUID(str(recording["recording_id"])), recording)
        return {
            "system_code": system_code,
            "recording_id": str(recording["recording_id"]),
            "skill_id": str(skill.skill_id),
            "skill_version": skill.version,
            "status": recording["status"],
            "test_results": results,
        }

    def _system_profile(self, system_code: str) -> Any:
        try:
            return self.system_profiles[system_code]
        except KeyError as exc:
            raise KeyError(f"unknown system profile: {system_code}") from exc

    def create_recording(self, request: Any) -> dict[str, Any]:
        source_systems = list(request.source_systems)
        if request.recording_mode == "multi_system":
            missing = [
                system_code
                for system_code in source_systems
                if system_code not in self.system_profiles
            ]
            if missing:
                raise ValueError(
                    "recording system profile is not configured: "
                    + ", ".join(missing)
                )
        recording_id = uuid4()
        now = datetime.now(UTC).isoformat()
        payload = {
            "recording_id": str(recording_id),
            "status": "created",
            "objective": request.objective,
            "source_system": request.source_system,
            "source_systems": source_systems,
            "recording_mode": request.recording_mode,
            "source_task_id": request.source_task_id,
            "capture_source": request.capture_source,
            "created_at": now,
            "updated_at": now,
        }
        self.repository.save_recording(recording_id, payload)
        return payload

    async def start_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if recording.get("capture_source") == "browser_extension":
            raise ValueError("browser extension recordings use the extension start route")
        await self.recorder.start(
            identifier,
            recording["objective"],
            {
                "system_code": recording["source_system"],
                "object_id": recording["source_task_id"],
            },
            "http://127.0.0.1:8101",
        )
        recording["status"] = "recording"
        self._save_recording(identifier, recording)
        return recording

    async def stop_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if recording.get("capture_source") == "browser_extension":
            raise ValueError("browser extension recordings use the extension stop route")
        trace = await self.recorder.stop(identifier)
        recording["status"] = "analyzing"
        recording["trace"] = trace.model_dump(mode="json")
        self._save_recording(identifier, recording)
        try:
            result = self.learning_graph.invoke(
                {
                    "recording_id": str(identifier),
                    "trace": recording["trace"],
                }
            )
        except Exception:
            logger.exception(
                "Learning graph failed for recording %s",
                identifier,
            )
            result = {
                "recording_id": str(identifier),
                "final_status": "rejected",
                "failure_stage": "system",
                "failure_reasons": [
                    "系统处理演示时发生错误，请检查模型配置和服务日志后重试。"
                ],
            }
        recording["status"] = (
            "published"
            if result.get("final_status") == "published"
            else "needs_reteach"
        )
        recording["learning_result"] = jsonable_encoder(result)
        if recording["status"] == "needs_reteach":
            if result.get("failure_stage"):
                recording["failure_stage"] = result["failure_stage"]
            if result.get("failure_reasons"):
                recording["failure_reasons"] = result["failure_reasons"]
        else:
            recording.pop("failure_stage", None)
            recording.pop("failure_reasons", None)
        self._save_recording(identifier, recording)
        return recording

    def start_extension_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if recording.get("capture_source") != "browser_extension":
            raise ValueError("recording capture source is not browser_extension")
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        source_systems = recording.get("source_systems") or [recording["source_system"]]
        profiles = [self.system_profiles.get(str(system_code)) for system_code in source_systems]
        if any(profile is None for profile in profiles):
            raise ValueError("recording system profile is not configured")
        grant = self.extension_recorder.start(
            identifier,
            str(recording["objective"]),
            {
                "system_code": recording["source_system"],
                "object_id": recording["source_task_id"],
            },
            profiles[0] if len(profiles) == 1 else profiles,
        )
        recording["status"] = "recording"
        self._save_recording(identifier, recording)
        return {**recording, "recording_token": grant.token}

    def ingest_extension_events(self, recording_id: UUID | str, batch: Any, token: str) -> None:
        identifier = UUID(str(recording_id))
        self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        validated = ExtensionEventBatch.model_validate(batch)
        self.extension_recorder.ingest(identifier, validated, token)

    def fail_extension_recording(
        self,
        recording_id: UUID | str,
        token: str,
        issues: list[dict[str, str]],
    ) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        self.extension_recorder.abort_authorized(identifier, token)
        recording["status"] = "upload_failed"
        recording["failure_stage"] = "upload"
        recording["failure_reasons"] = [
            "浏览器录制证据未通过协议校验，请重新加载扩展后再录制。"
        ]
        recording["validation_issues"] = issues
        self._save_recording(identifier, recording)
        logger.warning(
            "Extension evidence validation failed for recording %s: %s",
            identifier,
            issues,
        )
        return recording

    def abort_extension_recording(
        self,
        recording_id: UUID | str,
        token: str,
        reason: str,
    ) -> dict[str, Any]:
        message = _EXTENSION_ABORT_MESSAGES.get(reason)
        if message is None:
            raise ValueError("unsupported extension abort reason")
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        self.extension_recorder.abort_authorized(identifier, token)
        recording["status"] = "upload_failed"
        recording["failure_stage"] = "upload"
        recording["failure_reasons"] = [message]
        self._save_recording(identifier, recording)
        logger.warning(
            "Extension recording %s aborted with safe reason code %s",
            identifier,
            reason,
        )
        return recording

    def put_extension_credential(
        self,
        recording_id: UUID | str,
        name: str,
        secret: Any,
        token: str,
    ) -> None:
        identifier = UUID(str(recording_id))
        self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        self.extension_recorder.put_credential(identifier, name, secret, token)

    def stop_extension_recording(
        self,
        recording_id: UUID | str,
        token: str,
        *,
        enqueue_analysis: bool = False,
    ) -> dict[str, Any]:
        recording = self.finalize_extension_recording(recording_id, token)
        if self.learning_graph_factory is None:
            return recording
        if enqueue_analysis:
            return self.enqueue_extension_analysis(recording_id)
        return self.analyze_extension_recording(recording_id)

    def finalize_extension_recording(
        self,
        recording_id: UUID | str,
        token: str,
    ) -> dict[str, Any]:
        """Finalize and persist evidence without waiting for model analysis."""
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        trace = self.extension_recorder.stop(
            identifier,
            token,
            retain_credentials=self.learning_graph_factory is not None,
        )
        recording["trace"] = trace.model_dump(mode="json")
        recording["status"] = "recorded"
        recording["analysis_stage"] = "recorded"
        self._save_recording(identifier, recording)
        if self.learning_graph_factory is None:
            self.extension_recorder.clear_credentials(identifier)
        return recording

    def enqueue_extension_analysis(
        self,
        recording_id: UUID | str,
    ) -> dict[str, Any]:
        """Persist a queued state and run learning after the stop response returns."""
        identifier = UUID(str(recording_id))
        with self._analysis_lock:
            if identifier in self._active_analyses:
                return self.repository.get_recording(identifier)
            recording = self.repository.get_recording(identifier)
            if recording.get("status") != "recorded":
                raise ValueError("recording is not ready for analysis")
            self._active_analyses.add(identifier)
            recording["status"] = "analyzing"
            recording["analysis_stage"] = "queued"
            recording["analysis_queued_at"] = datetime.now(UTC).isoformat()
            self._save_recording(identifier, recording)

        worker = threading.Thread(
            target=self._run_queued_extension_analysis,
            args=(identifier,),
            name=f"recording-analysis-{identifier}",
            daemon=True,
        )
        worker.start()
        return recording

    def _run_queued_extension_analysis(self, recording_id: UUID) -> None:
        try:
            self.analyze_extension_recording(recording_id)
        except Exception:
            # analyze_extension_recording persists a safe terminal result.
            logger.exception("Queued analysis crashed for recording %s", recording_id)
        finally:
            with self._analysis_lock:
                self._active_analyses.discard(recording_id)

    def analyze_extension_recording(
        self,
        recording_id: UUID | str,
    ) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        if self.learning_graph_factory is None:
            self.extension_recorder.clear_credentials(identifier)
            return recording

        recording["status"] = "analyzing"
        recording["analysis_stage"] = "learning"
        recording["analysis_started_at"] = datetime.now(UTC).isoformat()
        recording.pop("failure_stage", None)
        recording.pop("failure_reasons", None)
        self._save_recording(identifier, recording)
        try:
            trace = recording["trace"]
            if not trace.get("api_exchanges") and self.browser_skill_distiller is not None:
                result = self._compile_browser_candidate(recording)
            else:
                source_systems = recording.get("source_systems") or [
                    str(recording["source_system"])
                ]
                graph = self.learning_graph_factory(source_systems, identifier)
                result = graph.invoke(
                    {"recording_id": str(identifier), "trace": trace}
                )
            recording["status"] = str(result.get("final_status", "rejected"))
            recording["learning_result"] = jsonable_encoder(result)
            recording["analysis_stage"] = (
                "awaiting_browser_verification"
                if recording["status"] == "browser_candidate"
                else "completed"
            )
            if result.get("failure_reasons"):
                recording["failure_reasons"] = result["failure_reasons"]
            else:
                recording.pop("failure_reasons", None)
        except Exception:
            logger.exception("Learning graph failed for recording %s", identifier)
            recording["status"] = "needs_reteach"
            recording["analysis_stage"] = "failed"
            recording["failure_stage"] = "system"
            recording["failure_reasons"] = _safe_prior_analysis_reasons(
                recording
            ) or ["后台分析失败；录制证据已经保存，可以稍后重新分析。"]
        finally:
            recording["analysis_finished_at"] = datetime.now(UTC).isoformat()
            self._save_recording(identifier, recording)
            self.extension_recorder.clear_credentials(identifier)
        return recording

    def _compile_browser_candidate(
        self,
        recording: dict[str, Any],
    ) -> dict[str, Any]:
        trace = recording["trace"]
        origins = sorted(
            {
                f"{parsed.scheme}://{parsed.netloc}"
                for event in trace.get("ui_events", [])
                if (parsed := urlsplit(str(event.get("page_url", ""))))
                and parsed.scheme in {"http", "https"}
                and parsed.netloc
            }
        )
        if not origins:
            raise ValueError("browser recording does not contain an allowed page origin")
        candidate = self.browser_skill_distiller.compile_browser_skill(trace, origins)
        return {
            "recording_id": str(recording["recording_id"]),
            "final_status": "browser_candidate",
            "execution_mode": "browser",
            "verification_status": "pending_isolated_browser",
            "candidate_skill": jsonable_encoder(candidate),
        }

    def get_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_recording(UUID(str(recording_id)))

    def list_recordings(
        self,
        capture_source: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        recordings = self.repository.list_recordings()
        if capture_source is not None:
            recordings = [
                recording
                for recording in recordings
                if recording.get("capture_source") == capture_source
            ]
        recordings.sort(
            key=lambda recording: str(recording.get("created_at", "")),
            reverse=True,
        )
        safe_fields = (
            "recording_id",
            "status",
            "objective",
            "source_system",
            "source_systems",
            "recording_mode",
            "capture_source",
            "created_at",
            "updated_at",
            "failure_reasons",
            "analysis_stage",
        )
        return [
            {
                field: (
                    recording.get(field, [])
                    if field == "failure_reasons"
                    else recording.get(field)
                )
                for field in safe_fields
            }
            for recording in recordings[:bounded_limit]
        ]

    def _save_recording(
        self,
        recording_id: UUID,
        recording: dict[str, Any],
    ) -> None:
        recording["updated_at"] = datetime.now(UTC).isoformat()
        self.repository.save_recording(recording_id, recording)

    def list_skills(
        self, status: str = "published"
    ) -> list[dict[str, Any]]:
        skills = (
            self.repository.list_verified_candidates()
            if status == "verified_candidate"
            else self.repository.list_published_skills()
        )
        return [
            skill.model_dump(mode="json")
            for skill in skills
        ]

    def get_skill(self, skill_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_skill(UUID(str(skill_id))).model_dump(mode="json")

    def create_task_run(self, request: Any) -> dict[str, Any]:
        run_id = uuid4()
        result = self.execution_graph.invoke({"user_request": request.user_request})
        payload = {
            "run_id": str(run_id),
            "user_request": request.user_request,
            **jsonable_encoder(result),
        }
        self.repository.save_task_run(run_id, payload)
        return payload

    def select_task_object(
        self,
        run_id: UUID | str,
        object_id: str,
    ) -> dict[str, Any]:
        identifier = UUID(str(run_id))
        existing = self.repository.get_task_run(identifier)
        result = self.execution_graph.invoke(
            {
                "user_request": existing["user_request"],
                "selected_object_id": object_id,
            }
        )
        payload = {
            "run_id": str(identifier),
            "user_request": existing["user_request"],
            **jsonable_encoder(result),
        }
        self.repository.save_task_run(identifier, payload)
        return payload

    def create_task_detail_run(
        self,
        run_id: UUID | str,
        record_id: str,
    ) -> dict[str, Any]:
        parent_run_id = UUID(str(run_id))
        parent = self.repository.get_task_run(parent_run_id)
        outputs = parent.get("final_response", {}).get("outputs")
        selected_record = _find_record_by_id(outputs, record_id)
        if selected_record is None:
            raise KeyError("record is not present in the saved task result")

        detail_run_id = uuid4()
        result = self.execution_graph.invoke(
            {
                "user_request": "查看所选采购申请详情",
                "task_context": {"selected_record": selected_record},
            }
        )
        payload = {
            "run_id": str(detail_run_id),
            "parent_run_id": str(parent_run_id),
            "user_request": "查看所选采购申请详情",
            **jsonable_encoder(result),
        }
        self.repository.save_task_run(detail_run_id, payload)
        return payload

    def create_purchase_progress_run(
        self,
        run_id: UUID | str,
        record_id: str,
    ) -> dict[str, Any]:
        parent_run_id = UUID(str(run_id))
        parent = self.repository.get_task_run(parent_run_id)
        outputs = parent.get("final_response", {}).get("outputs")
        selected_record = _find_record_by_id(outputs, record_id)
        if selected_record is None:
            raise KeyError("record is not present in the saved task result")
        if self.purchase_tracking_graph_factory is None:
            raise RuntimeError("purchase tracking is not configured")

        progress_run_id = uuid4()
        result = self.purchase_tracking_graph_factory().invoke(
            {"selected_application": selected_record}
        )
        payload = {
            "run_id": str(progress_run_id),
            "parent_run_id": str(parent_run_id),
            "user_request": "追踪所选采购申请进度",
            **jsonable_encoder(result),
        }
        self.repository.save_task_run(progress_run_id, payload)
        return payload

    def create_purchase_follow_up_run(
        self,
        run_id: UUID | str,
        record_id: str,
        instruction: str,
    ) -> dict[str, Any]:
        parent_run_id = UUID(str(run_id))
        parent = self.repository.get_task_run(parent_run_id)
        outputs = parent.get("final_response", {}).get("outputs")
        selected_record = _find_record_by_id(outputs, record_id)
        if selected_record is None:
            raise KeyError("record is not present in the saved task result")

        follow_up_run_id = uuid4()
        result = self.execution_graph.invoke(
            {
                "user_request": instruction,
                "task_context": {
                    "selected_record": selected_record,
                    "requested_capability": "purchase_follow_up",
                },
            }
        )
        payload = {
            "run_id": str(follow_up_run_id),
            "parent_run_id": str(parent_run_id),
            "selected_record_id": record_id,
            "user_request": instruction,
            **jsonable_encoder(result),
        }
        self.repository.save_task_run(follow_up_run_id, payload)
        return payload

    def get_task_run(self, run_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_task_run(UUID(str(run_id)))


def _find_record_by_id(
    value: Any,
    record_id: str,
    *,
    max_depth: int = 6,
    max_values: int = 250,
) -> dict[str, Any] | None:
    queue = deque([(value, 0)])
    visited = 0
    while queue and visited < max_values:
        current, depth = queue.popleft()
        visited += 1
        if isinstance(current, dict):
            if "id" in current and str(current["id"]) == record_id:
                return dict(current)
            if depth < max_depth:
                queue.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list) and depth < max_depth:
            queue.extend((child, depth + 1) for child in current)
    return None
