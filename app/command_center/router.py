from __future__ import annotations

from typing import Any, Callable, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    model_validator,
)

from app.command_center.schemas import EvidenceIdentifier, ExtensionEventBatch
from app.command_center.repository import TaskSessionConflictError
from app.command_center.task_session_inputs import InputSchemaError
from app.command_center.task_session_policy import (
    ConfirmationError,
    PlanValidationError,
)
from app.command_center.task_session_schemas import (
    CreateTaskSessionRequest,
    TaskSessionConfirmationRequest,
    TaskSessionInputRequest,
    TaskSessionMessageRequest,
)


class CreateRecordingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    source_system: str
    source_systems: list[str] = Field(default_factory=list)
    recording_mode: Literal["single_system", "multi_system"] = "single_system"
    source_task_id: str
    capture_source: Literal["playwright", "browser_extension"] = "playwright"

    @model_validator(mode="after")
    def normalize_recording_scope(self) -> CreateRecordingRequest:
        systems = self.source_systems or [self.source_system]
        if len(systems) != len(set(systems)):
            raise ValueError("source systems must be unique")
        if not systems or systems[0] != self.source_system:
            raise ValueError("source_system must be the first source system")
        if self.recording_mode == "single_system" and len(systems) != 1:
            raise ValueError("single-system recording requires exactly one system")
        if self.recording_mode == "multi_system" and len(systems) < 2:
            raise ValueError("multi-system recording requires at least two systems")
        self.source_systems = systems
        return self


class ExtensionCredentialRequest(BaseModel):
    name: EvidenceIdentifier
    secret: SecretStr


class ExtensionAbortRequest(BaseModel):
    reason: Literal["no_uploadable_evidence", "upload_failed"]


class SystemCredentialRequest(BaseModel):
    name: EvidenceIdentifier
    secret: SecretStr


class CreateTaskRunRequest(BaseModel):
    user_request: str = Field(min_length=1)


class CreateTaskDetailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=128)


class CreatePurchaseProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=128)


class CreatePurchaseFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=500)


class ExecuteTaskActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=128)


class SelectObjectRequest(BaseModel):
    object_id: str


def _safe_validation_issues(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "location": ".".join(str(part) for part in issue["loc"]),
            "type": str(issue["type"]),
        }
        for issue in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    ]


def create_router(service_provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/system-connections/{system_code}/begin",
        status_code=status.HTTP_201_CREATED,
    )
    def begin_system_connection(
        system_code: str,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.begin_system_connection(system_code)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put(
        "/system-connections/{system_code}/credential",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def put_system_credential(
        system_code: str,
        request: SystemCredentialRequest,
        connection_token: str = Header(alias="X-CommandCenter-Connection-Token"),
        service: Any = Depends(service_provider),
    ):
        try:
            return service.put_system_credential(
                system_code,
                request.name,
                request.secret,
                connection_token,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="connection authorization failed") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/system-connections/{system_code}")
    def get_system_connection(
        system_code: str,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.get_system_connection(system_code)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/system-connections/{system_code}")
    def disconnect_system(
        system_code: str,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.disconnect_system(system_code)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/system-connections/{system_code}/verify-latest-skill")
    def verify_latest_system_skill(
        system_code: str,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.verify_latest_system_skill(system_code)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/recordings")
    def list_recordings(
        capture_source: str | None = None,
        limit: int = Query(default=10, ge=1, le=100),
        service: Any = Depends(service_provider),
    ):
        return service.list_recordings(
            capture_source=capture_source,
            limit=limit,
        )

    @router.post("/recordings", status_code=status.HTTP_201_CREATED)
    def create_recording(
        request: CreateRecordingRequest,
        service: Any = Depends(service_provider),
    ):
        return service.create_recording(request)

    @router.post("/recordings/{recording_id}/start")
    async def start_recording(
        recording_id: UUID,
        service: Any = Depends(service_provider),
    ):
        try:
            return await service.start_recording(recording_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/recordings/{recording_id}/extension/start")
    def start_extension_recording(
        recording_id: UUID,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.start_extension_recording(recording_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="recording not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/recordings/{recording_id}/extension/events", status_code=202)
    def ingest_extension_events(
        recording_id: UUID,
        payload: dict[str, Any] = Body(),
        recording_token: str = Header(alias="X-CommandCenter-Recording-Token"),
        service: Any = Depends(service_provider),
    ):
        try:
            batch = ExtensionEventBatch.model_validate(payload)
        except ValidationError as exc:
            issues = _safe_validation_issues(exc)
            try:
                service.fail_extension_recording(
                    recording_id,
                    recording_token,
                    issues,
                )
            except PermissionError as auth_exc:
                raise HTTPException(
                    status_code=401,
                    detail="recording authorization failed",
                ) from auth_exc
            except KeyError as missing_exc:
                raise HTTPException(status_code=404, detail="recording not found") from missing_exc
            except ValueError as state_exc:
                raise HTTPException(status_code=409, detail=str(state_exc)) from state_exc
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_extension_evidence",
                    "issues": issues,
                },
            ) from exc
        try:
            service.ingest_extension_events(recording_id, batch, recording_token)
            return {"accepted": True}
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="recording authorization failed") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put("/recordings/{recording_id}/extension/credential", status_code=202)
    def put_extension_credential(
        recording_id: UUID,
        request: ExtensionCredentialRequest,
        recording_token: str = Header(alias="X-CommandCenter-Recording-Token"),
        service: Any = Depends(service_provider),
    ) -> dict[str, bool]:
        try:
            service.put_extension_credential(
                recording_id,
                request.name,
                request.secret,
                recording_token,
            )
            return {"accepted": True}
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="recording authorization failed") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/recordings/{recording_id}/extension/stop",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def stop_extension_recording(
        recording_id: UUID,
        recording_token: str = Header(alias="X-CommandCenter-Recording-Token"),
        service: Any = Depends(service_provider),
    ):
        try:
            return service.stop_extension_recording(
                recording_id,
                recording_token,
                enqueue_analysis=True,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="recording authorization failed") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="recording not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/recordings/{recording_id}/extension/abort",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def abort_extension_recording(
        recording_id: UUID,
        request: ExtensionAbortRequest,
        recording_token: str = Header(alias="X-CommandCenter-Recording-Token"),
        service: Any = Depends(service_provider),
    ):
        try:
            return service.abort_extension_recording(
                recording_id,
                recording_token,
                request.reason,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=401,
                detail="recording authorization failed",
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="recording not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/recordings/{recording_id}/stop",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def stop_recording(
        recording_id: UUID,
        service: Any = Depends(service_provider),
    ):
        try:
            return await service.stop_recording(recording_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/recordings/{recording_id}")
    def get_recording(
        recording_id: UUID,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.get_recording(recording_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/skills")
    def list_skills(
        status: Literal["published", "verified_candidate"] = "published",
        service: Any = Depends(service_provider),
    ):
        return service.list_skills(status=status)

    @router.get("/skills/{skill_id}")
    def get_skill(skill_id: UUID, service: Any = Depends(service_provider)):
        try:
            return service.get_skill(skill_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/task-sessions", status_code=status.HTTP_201_CREATED)
    def create_task_session(
        request: CreateTaskSessionRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.create_task_session(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="task permission denied") from exc
        except (PlanValidationError, InputSchemaError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/task-sessions/{session_id}/messages")
    def add_task_session_message(
        session_id: UUID,
        request: TaskSessionMessageRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.add_task_session_message(session_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task session not found") from exc
        except TaskSessionConflictError as exc:
            raise HTTPException(status_code=409, detail="task session version conflict") from exc
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail="confirmation is no longer valid") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="task permission denied") from exc
        except (PlanValidationError, InputSchemaError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/task-sessions/{session_id}/inputs")
    def submit_task_session_inputs(
        session_id: UUID,
        request: TaskSessionInputRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.submit_task_session_inputs(session_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task session not found") from exc
        except TaskSessionConflictError as exc:
            raise HTTPException(status_code=409, detail="task session version conflict") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="task permission denied") from exc
        except (PlanValidationError, InputSchemaError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/task-sessions/{session_id}/confirmations")
    def confirm_task_session(
        session_id: UUID,
        request: TaskSessionConfirmationRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.confirm_task_session(session_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task session not found") from exc
        except TaskSessionConflictError as exc:
            raise HTTPException(status_code=409, detail="task session version conflict") from exc
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail="confirmation is no longer valid") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="task permission denied") from exc
        except (PlanValidationError, InputSchemaError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/task-sessions/{session_id}")
    def get_task_session(
        session_id: UUID,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.get_task_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task session not found") from exc

    @router.post("/task-runs", status_code=status.HTTP_201_CREATED)
    def create_task_run(
        request: CreateTaskRunRequest,
        service: Any = Depends(service_provider),
    ):
        return service.create_task_run(request)

    @router.post("/task-runs/{run_id}/select-object")
    def select_object(
        run_id: UUID,
        request: SelectObjectRequest,
        service: Any = Depends(service_provider),
    ):
        return service.select_task_object(run_id, request.object_id)

    @router.post(
        "/task-runs/{run_id}/details",
        status_code=status.HTTP_201_CREATED,
    )
    def create_task_detail_run(
        run_id: UUID,
        request: CreateTaskDetailRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.create_task_detail_run(run_id, request.record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task run record not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/task-runs/{run_id}/purchase-progress",
        status_code=status.HTTP_201_CREATED,
    )
    def create_purchase_progress_run(
        run_id: UUID,
        request: CreatePurchaseProgressRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.create_purchase_progress_run(run_id, request.record_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="task run record not found",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/task-runs/{run_id}/purchase-follow-up",
        status_code=status.HTTP_201_CREATED,
    )
    def create_purchase_follow_up_run(
        run_id: UUID,
        request: CreatePurchaseFollowUpRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.create_purchase_follow_up_run(
                run_id, request.record_id, request.instruction
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task run record not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/task-runs/{run_id}/actions/{action_id}/execute",
        status_code=status.HTTP_201_CREATED,
    )
    def execute_task_action(
        run_id: UUID,
        action_id: str,
        request: ExecuteTaskActionRequest,
        service: Any = Depends(service_provider),
    ):
        try:
            return service.execute_task_action(run_id, action_id, request.record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task action not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/task-runs/{run_id}")
    def get_task_run(run_id: UUID, service: Any = Depends(service_provider)):
        try:
            return service.get_task_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/task-runs/{run_id}/events")
    def get_task_run_events(run_id: UUID, service: Any = Depends(service_provider)):
        run = service.get_task_run(run_id)
        return {"run_id": str(run_id), "events": run.get("events", [])}

    return router
