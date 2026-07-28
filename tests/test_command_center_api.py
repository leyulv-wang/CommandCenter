from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.command_center.router import create_router


class FakeCommandCenterService:
    def __init__(self):
        self.recording_id = uuid4()
        self.recording = {
            "recording_id": str(self.recording_id),
            "status": "created",
            "objective": "演示采购回写",
        }

    def create_recording(self, request):
        return self.recording

    async def start_recording(self, recording_id):
        self.recording["status"] = "recording"
        return self.recording

    async def stop_recording(self, recording_id):
        self.recording["status"] = "published"
        return self.recording

    def get_recording(self, recording_id):
        return self.recording

    def list_skills(self):
        return []

    def get_skill(self, skill_id):
        raise KeyError(skill_id)

    def create_task_run(self, request):
        return {
            "run_id": str(uuid4()),
            "status": "succeeded",
            "final_response": {"summary": "采购创建并回写完成"},
        }

    def select_task_object(self, run_id, object_id):
        return {"run_id": str(run_id), "status": "succeeded"}

    def get_task_run(self, run_id):
        return {"run_id": str(run_id), "status": "succeeded"}


def client_for(service):
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    return TestClient(app)


def test_recording_lifecycle_exposes_published_status():
    service = FakeCommandCenterService()
    client = client_for(service)

    created = client.post(
        "/recordings",
        json={
            "objective": "演示采购回写",
            "source_system": "onboarding_system",
            "source_task_id": "OFFICE-TASK-0001",
        },
    )
    started = client.post(f"/recordings/{service.recording_id}/start")
    stopped = client.post(f"/recordings/{service.recording_id}/stop")
    current = client.get(f"/recordings/{service.recording_id}")

    assert created.status_code == 201
    assert started.json()["status"] == "recording"
    assert stopped.status_code == 202
    assert current.json()["status"] == "published"


def test_task_run_accepts_natural_language_request():
    response = client_for(FakeCommandCenterService()).post(
        "/task-runs",
        json={"user_request": "处理签字笔库存不足任务"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"
    assert response.json()["final_response"]["summary"] == "采购创建并回写完成"
