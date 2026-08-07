from __future__ import annotations

from typing import Any, Callable, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.command_center.schemas import EvidenceIdentifier, ExtensionEventBatch


class CreateRecordingRequest(BaseModel):
    objective: str = Field(min_length=1)
    source_system: str
    source_task_id: str
    capture_source: Literal["playwright", "browser_extension"] = "playwright"


class ExtensionCredentialRequest(BaseModel):
    name: EvidenceIdentifier
    secret: SecretStr


class CreateTaskRunRequest(BaseModel):
    user_request: str = Field(min_length=1)


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
