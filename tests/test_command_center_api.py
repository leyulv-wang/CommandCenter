from datetime import UTC, datetime
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

    def start_extension_recording(self, recording_id):
        self.recording["status"] = "recording"
        return {**self.recording, "recording_token": "one-time-recording-token"}

    def ingest_extension_events(self, recording_id, batch, token):
        assert token == "one-time-recording-token"
        self.batch = batch

    def put_extension_credential(self, recording_id, name, secret, token):
        assert token == "one-time-recording-token"
        self.credential_name = name

    def stop_extension_recording(self, recording_id, token):
        assert token == "one-time-recording-token"
        self.recording["status"] = "recorded"
        return self.recording

    def get_recording(self, recording_id):
        return self.recording

    def list_skills(self, status="published"):
        self.requested_skill_status = status
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


def test_extension_api_separates_evidence_and_plaintext_credential():
    service = FakeCommandCenterService()
    client = client_for(service)
    started = client.post(f"/recordings/{service.recording_id}/extension/start")
    token = started.json()["recording_token"]
    headers = {"X-CommandCenter-Recording-Token": token}
    fingerprint = "hmac-sha256:" + "a" * 64
    events = client.post(
        f"/recordings/{service.recording_id}/extension/events",
        headers=headers,
        json={
            "batch_id": str(uuid4()),
            "recording_id": str(service.recording_id),
            "events": [
                {
                    "event_id": str(uuid4()),
                    "client_sequence": 1,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "event_type": "click",
                    "page": {
                        "origin": "https://example.test",
                        "path": "/orders",
                        "fingerprint": fingerprint,
                    },
                }
            ],
        },
    )
    credential = client.put(
        f"/recordings/{service.recording_id}/extension/credential",
        headers=headers,
        json={"name": "X-Access-Token", "secret": "raw-private-token"},
    )
    stopped = client.post(
        f"/recordings/{service.recording_id}/extension/stop", headers=headers
    )

    assert started.status_code == 200
    assert events.status_code == 202
    assert credential.status_code == 202
    assert stopped.status_code == 200
    assert "raw-private-token" not in stopped.text
    assert "one-time-recording-token" not in stopped.text


def test_verified_candidate_query_is_explicit_and_default_stays_published():
    service = FakeCommandCenterService()
    client = client_for(service)

    assert client.get("/skills").status_code == 200
    assert service.requested_skill_status == "published"
    assert client.get("/skills?status=verified_candidate").status_code == 200
    assert service.requested_skill_status == "verified_candidate"
