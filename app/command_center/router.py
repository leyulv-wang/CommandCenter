from __future__ import annotations

from typing import Any, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field


class CreateRecordingRequest(BaseModel):
    objective: str = Field(min_length=1)
    source_system: str
    source_task_id: str


class CreateTaskRunRequest(BaseModel):
    user_request: str = Field(min_length=1)


class SelectObjectRequest(BaseModel):
    object_id: str


def create_router(service_provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

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
    def list_skills(service: Any = Depends(service_provider)):
        return service.list_skills()

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
