from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder

from app.command_center.repository import CommandCenterRepository


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
    ):
        self.repository = repository
        self.recorder = recorder
        self.learning_graph = learning_graph
        self.execution_graph = execution_graph
        self.extension_recorder = extension_recorder
        self.system_profiles = system_profiles or {}

    def create_recording(self, request: Any) -> dict[str, Any]:
        recording_id = uuid4()
        payload = {
            "recording_id": str(recording_id),
            "status": "created",
            "objective": request.objective,
            "source_system": request.source_system,
            "source_task_id": request.source_task_id,
            "capture_source": request.capture_source,
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
        self.repository.save_recording(identifier, recording)
        return recording

    async def stop_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if recording.get("capture_source") == "browser_extension":
            raise ValueError("browser extension recordings use the extension stop route")
        trace = await self.recorder.stop(identifier)
        recording["status"] = "analyzing"
        recording["trace"] = trace.model_dump(mode="json")
        self.repository.save_recording(identifier, recording)
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
        self.repository.save_recording(identifier, recording)
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
        self.repository.save_recording(identifier, recording)
        return {**recording, "recording_token": grant.token}

    def ingest_extension_events(self, recording_id: UUID | str, batch: Any, token: str) -> None:
        identifier = UUID(str(recording_id))
        self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        self.extension_recorder.ingest(identifier, batch, token)

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
    ) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
        if self.extension_recorder is None:
            raise ValueError("browser extension recorder is not configured")
        trace = self.extension_recorder.stop(identifier, token)
        recording["status"] = "recorded"
        recording["trace"] = trace.model_dump(mode="json")
        self.repository.save_recording(identifier, recording)
        return recording

    def get_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_recording(UUID(str(recording_id)))

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
