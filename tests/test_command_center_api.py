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
        self.create_recording_request = request
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

    def fail_extension_recording(self, recording_id, token, issues):
        if token != "one-time-recording-token":
            raise PermissionError("extension recording authorization failed")
        self.recording["status"] = "upload_failed"
        self.recording["failure_stage"] = "upload"
        self.recording["validation_issues"] = issues
        return self.recording

    def abort_extension_recording(self, recording_id, token, reason):
        if token != "one-time-recording-token":
            raise PermissionError("extension recording authorization failed")
        self.abort_reason = reason
        self.recording["status"] = "upload_failed"
        self.recording["failure_stage"] = "upload"
        self.recording["failure_reasons"] = ["浏览器未采集到可用证据，请重新录制。"]
        return self.recording

    def put_extension_credential(self, recording_id, name, secret, token):
        assert token == "one-time-recording-token"
        self.credential_name = name

    def stop_extension_recording(self, recording_id, token, *, enqueue_analysis=False):
        assert token == "one-time-recording-token"
        self.recording["status"] = "analyzing" if enqueue_analysis else "recorded"
        return self.recording

    def get_recording(self, recording_id):
        return self.recording

    def list_recordings(self, capture_source=None, limit=10):
        self.requested_recording_source = capture_source
        self.requested_recording_limit = limit
        return [self.recording]

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

    def create_task_detail_run(self, run_id, record_id):
        return {
            "run_id": str(uuid4()),
            "parent_run_id": str(run_id),
            "status": "succeeded",
            "selected_record_id": record_id,
        }

    def create_purchase_progress_run(self, run_id, record_id):
        return {
            "run_id": str(uuid4()),
            "parent_run_id": str(run_id),
            "status": "succeeded",
            "selected_record_id": record_id,
            "final_response": {
                "summary": "采购链路已追踪",
                "progress": {
                    "status": "complete",
                    "summary": "采购链路已追踪",
                    "stages": [],
                },
            },
        }

    def get_task_run(self, run_id):
        return {"run_id": str(run_id), "status": "succeeded"}

    def begin_system_connection(self, system_code):
        return {
            "system_code": system_code,
            "display_name": "益丰 MES",
            "connection_token": "one-time-connection-token",
        }

    def put_system_credential(self, system_code, name, secret, token):
        assert token == "one-time-connection-token"
        self.system_credential_name = name
        return {
            "system_code": system_code,
            "display_name": "益丰 MES",
            "status": "connected",
            "credential_source": "windows_keyring",
        }

    def get_system_connection(self, system_code):
        return {
            "system_code": system_code,
            "display_name": "益丰 MES",
            "status": "connected",
            "credential_source": "windows_keyring",
        }

    def disconnect_system(self, system_code):
        return {
            "system_code": system_code,
            "display_name": "益丰 MES",
            "status": "disconnected",
            "credential_source": "windows_keyring",
        }

    def verify_latest_system_skill(self, system_code):
        self.verified_system_code = system_code
        return {
            "system_code": system_code,
            "recording_id": str(self.recording_id),
            "skill_id": str(uuid4()),
            "skill_version": 1,
            "status": "verified_candidate",
            "test_results": [],
        }


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


def test_multi_system_recording_request_is_normalized_before_service_call():
    service = FakeCommandCenterService()
    client = client_for(service)

    response = client.post(
        "/recordings",
        json={
            "objective": "查询 MES 采购申请并创建本地后续处理单",
            "source_system": "yifeng_mes",
            "source_systems": ["yifeng_mes", "connected_system"],
            "recording_mode": "multi_system",
            "source_task_id": "joint-demo",
            "capture_source": "browser_extension",
        },
    )

    assert response.status_code == 201
    request = service.create_recording_request
    assert request.recording_mode == "multi_system"
    assert request.source_systems == ["yifeng_mes", "connected_system"]


def test_multi_system_recording_request_rejects_duplicate_systems():
    response = client_for(FakeCommandCenterService()).post(
        "/recordings",
        json={
            "objective": "联合演示",
            "source_system": "yifeng_mes",
            "source_systems": ["yifeng_mes", "yifeng_mes"],
            "recording_mode": "multi_system",
            "source_task_id": "joint-demo",
            "capture_source": "browser_extension",
        },
    )

    assert response.status_code == 422


def test_task_run_accepts_natural_language_request():
    response = client_for(FakeCommandCenterService()).post(
        "/task-runs",
        json={"user_request": "处理签字笔库存不足任务"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"
    assert response.json()["final_response"]["summary"] == "采购创建并回写完成"


def test_task_detail_run_accepts_only_selected_record_id():
    parent_run_id = uuid4()
    response = client_for(FakeCommandCenterService()).post(
        f"/task-runs/{parent_run_id}/details",
        json={"record_id": "2037430718812770305"},
    )

    assert response.status_code == 201
    assert response.json()["parent_run_id"] == str(parent_run_id)
    assert response.json()["selected_record_id"] == "2037430718812770305"


def test_task_detail_run_rejects_browser_supplied_record_payload():
    response = client_for(FakeCommandCenterService()).post(
        f"/task-runs/{uuid4()}/details",
        json={
            "record_id": "row-1",
            "selected_record": {"id": "row-other", "applyBy": "伪造值"},
        },
    )

    assert response.status_code == 422


def test_task_detail_run_maps_missing_saved_record_to_404():
    class MissingRecordService(FakeCommandCenterService):
        def create_task_detail_run(self, run_id, record_id):
            raise KeyError(record_id)

    response = client_for(MissingRecordService()).post(
        f"/task-runs/{uuid4()}/details",
        json={"record_id": "not-saved"},
    )

    assert response.status_code == 404
    assert "not-saved" not in response.text


def test_purchase_progress_endpoint_returns_persisted_child_run():
    parent_run_id = uuid4()

    response = client_for(FakeCommandCenterService()).post(
        f"/task-runs/{parent_run_id}/purchase-progress",
        json={"record_id": "application-1"},
    )

    assert response.status_code == 201
    assert response.json()["parent_run_id"] == str(parent_run_id)
    assert response.json()["final_response"]["progress"]["status"] == "complete"


def test_purchase_progress_endpoint_rejects_browser_supplied_record_payload():
    response = client_for(FakeCommandCenterService()).post(
        f"/task-runs/{uuid4()}/purchase-progress",
        json={
            "record_id": "application-1",
            "selected_application": {"id": "forged", "applyNo": "FORGED"},
        },
    )

    assert response.status_code == 422


def test_purchase_progress_endpoint_maps_missing_saved_record_to_404():
    class MissingRecordService(FakeCommandCenterService):
        def create_purchase_progress_run(self, run_id, record_id):
            raise KeyError(record_id)

    response = client_for(MissingRecordService()).post(
        f"/task-runs/{uuid4()}/purchase-progress",
        json={"record_id": "not-saved"},
    )

    assert response.status_code == 404
    assert "not-saved" not in response.text


def test_system_connection_api_never_returns_the_submitted_credential():
    service = FakeCommandCenterService()
    client = client_for(service)

    begun = client.post('/system-connections/yifeng_mes/begin')
    token = begun.json()['connection_token']
    connected = client.put(
        '/system-connections/yifeng_mes/credential',
        headers={'X-CommandCenter-Connection-Token': token},
        json={'name': 'X-Access-Token', 'secret': 'raw-private-token'},
    )
    status = client.get('/system-connections/yifeng_mes')
    disconnected = client.delete('/system-connections/yifeng_mes')

    assert begun.status_code == 201
    assert connected.status_code == 202
    assert status.json()['status'] == 'connected'
    assert disconnected.json()['status'] == 'disconnected'
    assert service.system_credential_name == 'X-Access-Token'
    assert 'raw-private-token' not in connected.text
    assert 'raw-private-token' not in status.text


def test_system_connection_can_verify_the_latest_saved_candidate():
    service = FakeCommandCenterService()
    response = client_for(service).post(
        "/system-connections/yifeng_mes/verify-latest-skill"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "verified_candidate"
    assert service.verified_system_code == "yifeng_mes"


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
    assert stopped.status_code == 202
    assert stopped.json()["status"] == "analyzing"
    assert "raw-private-token" not in stopped.text
    assert "one-time-recording-token" not in stopped.text


def test_verified_candidate_query_is_explicit_and_default_stays_published():
    service = FakeCommandCenterService()
    client = client_for(service)

    assert client.get("/skills").status_code == 200
    assert service.requested_skill_status == "published"
    assert client.get("/skills?status=verified_candidate").status_code == 200
    assert service.requested_skill_status == "verified_candidate"


def test_invalid_extension_evidence_becomes_safe_terminal_failure():
    service = FakeCommandCenterService()
    client = client_for(service)
    client.post(f"/recordings/{service.recording_id}/extension/start")
    response = client.post(
        f"/recordings/{service.recording_id}/extension/events",
        headers={"X-CommandCenter-Recording-Token": "one-time-recording-token"},
        json={
            "batch_id": str(uuid4()),
            "recording_id": str(service.recording_id),
            "events": [
                {
                    "exchange_id": str(uuid4()),
                    "client_sequence": 1,
                    "started_at": datetime.now(UTC).isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "method": "GET",
                    "path_template": "/api/orders",
                    "query_parameter_names": ["_t"],
                    "response_status": 200,
                }
            ],
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_extension_evidence"
    assert detail["issues"]
    assert all(set(issue) == {"location", "type"} for issue in detail["issues"])
    assert '"_t"' not in response.text
    assert '"input"' not in response.text
    assert service.recording["status"] == "upload_failed"


def test_invalid_extension_evidence_cannot_change_state_with_bad_token():
    service = FakeCommandCenterService()
    service.recording["status"] = "recording"
    response = client_for(service).post(
        f"/recordings/{service.recording_id}/extension/events",
        headers={"X-CommandCenter-Recording-Token": "wrong-token"},
        json={"recording_id": str(service.recording_id), "events": []},
    )

    assert response.status_code == 401
    assert service.recording["status"] == "recording"


def test_extension_can_abort_empty_local_capture_with_safe_reason():
    service = FakeCommandCenterService()
    service.recording["status"] = "recording"
    response = client_for(service).post(
        f"/recordings/{service.recording_id}/extension/abort",
        headers={"X-CommandCenter-Recording-Token": "one-time-recording-token"},
        json={"reason": "no_uploadable_evidence"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "upload_failed"
    assert service.abort_reason == "no_uploadable_evidence"
    assert "recording-token" not in response.text


def test_extension_abort_with_bad_token_keeps_recording_active():
    service = FakeCommandCenterService()
    service.recording["status"] = "recording"
    response = client_for(service).post(
        f"/recordings/{service.recording_id}/extension/abort",
        headers={"X-CommandCenter-Recording-Token": "wrong-token"},
        json={"reason": "upload_failed"},
    )

    assert response.status_code == 401
    assert service.recording["status"] == "recording"


def test_recent_recordings_endpoint_forwards_safe_filters():
    service = FakeCommandCenterService()
    response = client_for(service).get(
        "/recordings?capture_source=browser_extension&limit=1"
    )

    assert response.status_code == 200
    assert response.json()[0]["recording_id"] == str(service.recording_id)
    assert service.requested_recording_source == "browser_extension"
    assert service.requested_recording_limit == 1
