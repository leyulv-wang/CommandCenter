from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder

from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import ExtensionEventBatch


logger = logging.getLogger(__name__)


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
    ):
        self.repository = repository
        self.recorder = recorder
        self.learning_graph = learning_graph
        self.execution_graph = execution_graph
        self.extension_recorder = extension_recorder
        self.system_profiles = system_profiles or {}
        self.learning_graph_factory = learning_graph_factory
        self.browser_skill_distiller = browser_skill_distiller
        self._analysis_lock = threading.Lock()
        self._active_analyses: set[UUID] = set()

    def create_recording(self, request: Any) -> dict[str, Any]:
        recording_id = uuid4()
        now = datetime.now(UTC).isoformat()
        payload = {
            "recording_id": str(recording_id),
            "status": "created",
            "objective": request.objective,
            "source_system": request.source_system,
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
        profile = self.system_profiles.get(str(recording["source_system"]))
        if profile is None:
            raise ValueError("recording system profile is not configured")
        grant = self.extension_recorder.start(
            identifier,
            str(recording["objective"]),
            {
                "system_code": recording["source_system"],
                "object_id": recording["source_task_id"],
            },
            profile,
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
        self._save_recording(identifier, recording)
        try:
            trace = recording["trace"]
            if not trace.get("api_exchanges") and self.browser_skill_distiller is not None:
                result = self._compile_browser_candidate(recording)
            else:
                graph = self.learning_graph_factory(
                    str(recording["source_system"]), identifier
                )
                result = graph.invoke(
                    {"recording_id": str(identifier), "trace": trace}
                )
                if (
                    result.get("final_status") == "rejected"
                    and self.browser_skill_distiller is not None
                ):
                    result = self._compile_browser_candidate(recording)
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
            recording["failure_reasons"] = [
                "后台分析失败；录制证据已经保存，可以稍后重新分析。"
            ]
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

    def get_task_run(self, run_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_task_run(UUID(str(run_id)))
