from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder

from app.command_center.repository import CommandCenterRepository


class CommandCenterService:
    def __init__(
        self,
        *,
        repository: CommandCenterRepository,
        recorder: Any,
        learning_graph: Any,
        execution_graph: Any,
    ):
        self.repository = repository
        self.recorder = recorder
        self.learning_graph = learning_graph
        self.execution_graph = execution_graph

    def create_recording(self, request: Any) -> dict[str, Any]:
        recording_id = uuid4()
        payload = {
            "recording_id": str(recording_id),
            "status": "created",
            "objective": request.objective,
            "source_system": request.source_system,
            "source_task_id": request.source_task_id,
        }
        self.repository.save_recording(recording_id, payload)
        return payload

    async def start_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        identifier = UUID(str(recording_id))
        recording = self.repository.get_recording(identifier)
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
        trace = await self.recorder.stop(identifier)
        recording["status"] = "analyzing"
        recording["trace"] = trace.model_dump(mode="json")
        self.repository.save_recording(identifier, recording)
        result = self.learning_graph.invoke(
            {
                "recording_id": str(identifier),
                "trace": recording["trace"],
            }
        )
        recording["status"] = (
            "published"
            if result.get("final_status") == "published"
            else "needs_reteach"
        )
        recording["learning_result"] = jsonable_encoder(result)
        self.repository.save_recording(identifier, recording)
        return recording

    def get_recording(self, recording_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_recording(UUID(str(recording_id)))

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            skill.model_dump(mode="json")
            for skill in self.repository.list_published_skills()
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
