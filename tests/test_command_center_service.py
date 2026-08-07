from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.command_center.repository import CommandCenterRepository
from app.command_center.router import CreateRecordingRequest, CreateTaskRunRequest
from app.command_center.schemas import OperationTrace
from app.command_center.service import CommandCenterService, _safe_prior_analysis_reasons
from app.command_center.extension_recorder import ExtensionRecorder
from app.command_center.schemas import ExtensionEventBatch
from app.command_center.system_profiles import ProfileLimits, SystemProfile, ToolPermission
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition


class Recorder:
    async def start(self, recording_id, objective, source_task, start_url):
        self.started = (recording_id, start_url)

    async def stop(self, recording_id):
        return OperationTrace(
            trace_id=uuid4(),
            recording_id=recording_id,
            objective="演示采购回写",
            source_task={"object_id": "OFFICE-1"},
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )


class Graph:
    def __init__(self, result):
        self.result = result

    def invoke(self, state):
        self.state = state
        return self.result


class FailingGraph:
    def invoke(self, state):
        raise RuntimeError("secret provider detail")


class AbortableExtension:
    def __init__(self):
        self.aborted = None

    def abort_authorized(self, recording_id, token):
        if token != "valid-token":
            raise PermissionError("extension recording authorization failed")
        self.aborted = recording_id


def test_prior_analysis_reasons_are_bounded_and_filter_sensitive_text():
    reasons = _safe_prior_analysis_reasons(
        {
            "api_learning_result": {
                "failure_reasons": [
                    "字段对应关系证据不足",
                    "Authorization token leaked",
                    "x" * 400,
                    "原因四",
                    "原因五",
                    "原因六",
                    "原因七",
                ]
            }
        }
    )

    assert reasons[0] == "字段对应关系证据不足"
    assert all("token" not in reason.lower() for reason in reasons)
    assert len(reasons) == 5
    assert max(map(len, reasons)) == 300


def test_service_connects_recording_stop_to_learning_graph(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    recorder = Recorder()
    learning = Graph({"final_status": "published", "test_results": []})
    service = CommandCenterService(
        repository=repository,
        recorder=recorder,
        learning_graph=learning,
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )

    import asyncio

    asyncio.run(service.start_recording(created["recording_id"]))
    stopped = asyncio.run(service.stop_recording(created["recording_id"]))

    assert recorder.started[1] == "http://127.0.0.1:8101"
    assert stopped["status"] == "published"
    assert learning.state["trace"]["objective"] == "演示采购回写"
    assert repository.get_recording(created["recording_id"])["status"] == "published"


def test_service_persists_learning_rejection_feedback(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph(
            {
                "final_status": "rejected",
                "failure_stage": "analysis",
                "failure_reasons": ["未观察到创建采购申请接口"],
            }
        ),
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )

    import asyncio

    asyncio.run(service.start_recording(created["recording_id"]))
    stopped = asyncio.run(service.stop_recording(created["recording_id"]))

    assert stopped["status"] == "needs_reteach"
    assert stopped["failure_stage"] == "analysis"
    assert stopped["failure_reasons"] == ["未观察到创建采购申请接口"]
    persisted = repository.get_recording(created["recording_id"])
    assert persisted["failure_stage"] == "analysis"
    assert persisted["failure_reasons"] == ["未观察到创建采购申请接口"]


def test_service_sanitizes_learning_system_failure(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=FailingGraph(),
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )

    import asyncio

    asyncio.run(service.start_recording(created["recording_id"]))
    stopped = asyncio.run(service.stop_recording(created["recording_id"]))

    assert stopped["status"] == "needs_reteach"
    assert stopped["failure_stage"] == "system"
    assert stopped["failure_reasons"] == [
        "系统处理演示时发生错误，请检查模型配置和服务日志后重试。"
    ]
    assert "secret provider detail" not in str(stopped)
    assert repository.get_recording(created["recording_id"]) == stopped


def test_service_persists_natural_language_task_run(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    execution = Graph(
        {
            "status": "succeeded",
            "final_response": {"summary": "采购创建并回写完成"},
        }
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )

    run = service.create_task_run(
        CreateTaskRunRequest(user_request="处理签字笔库存不足任务")
    )

    assert run["status"] == "succeeded"
    assert repository.get_task_run(run["run_id"])["final_response"]["summary"] == (
        "采购创建并回写完成"
    )


def test_service_persists_safe_extension_upload_failure(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    extension = AbortableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording["status"] = "recording"
    repository.save_recording(created["recording_id"], recording)
    issues = [{"location": "events.0.query_parameter_names.0", "type": "string_pattern_mismatch"}]

    failed = service.fail_extension_recording(
        created["recording_id"], "valid-token", issues
    )

    assert failed["status"] == "upload_failed"
    assert failed["failure_stage"] == "upload"
    assert failed["validation_issues"] == issues
    assert extension.aborted is not None
    assert repository.get_recording(created["recording_id"]) == failed


def test_service_aborts_extension_capture_with_fixed_safe_reason(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    extension = AbortableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording["status"] = "recording"
    repository.save_recording(created["recording_id"], recording)

    failed = service.abort_extension_recording(
        created["recording_id"], "valid-token", "no_uploadable_evidence"
    )

    assert failed["status"] == "upload_failed"
    assert failed["failure_stage"] == "upload"
    assert failed["failure_reasons"] == ["浏览器未采集到可用证据，请重新录制。"]
    assert extension.aborted is not None


def test_service_rejects_unauthorized_extension_abort_without_state_change(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=AbortableExtension(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording["status"] = "recording"
    repository.save_recording(created["recording_id"], recording)

    with pytest.raises(PermissionError):
        service.abort_extension_recording(
            created["recording_id"], "wrong-token", "upload_failed"
        )

    assert repository.get_recording(created["recording_id"])["status"] == "recording"


def test_service_lists_only_safe_recent_recording_fields(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    assert created["created_at"]
    assert created["updated_at"]
    stored = repository.get_recording(created["recording_id"])
    stored["trace"] = {"secret_marker": "must-not-leak"}
    stored["learning_result"] = {"private": "must-not-leak"}
    repository.save_recording(created["recording_id"], stored)

    listed = service.list_recordings(capture_source="browser_extension", limit=1)

    assert len(listed) == 1
    assert set(listed[0]) == {
        "recording_id",
        "status",
        "objective",
        "source_system",
        "capture_source",
        "created_at",
        "updated_at",
            "failure_reasons",
            "analysis_stage",
        }
    assert "must-not-leak" not in str(listed)


def test_service_extension_recording_never_persists_token_or_credential(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    profile = SystemProfile(
        system_code="mes",
        display_name="MES",
        allowed_hosts={"mes.example.test"},
        openapi_url="https://mes.example.test/api-docs",
        base_url="https://mes.example.test",
        api_path_prefix="/api",
        credential_header="X-Access-Token",
        limits=ProfileLimits(
            request_timeout_seconds=10,
            max_response_bytes=1000,
            max_requests_per_minute=10,
        ),
        value_capture_policy="fingerprint_by_default",
        sensitive_field_patterns=["(?i)token"],
        tool_permissions=[
            ToolPermission(method="GET", path="/api/orders", side_effect="read")
        ],
    )
    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:listOrders",
                system_code="mes",
                operation_id="listOrders",
                method="GET",
                base_url="https://mes.example.test",
                path_template="/api/orders",
                content_type=None,
                side_effect="read",
            )
        ]
    )
    extension = ExtensionRecorder(catalog)
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        system_profiles={"mes": profile},
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    started = service.start_extension_recording(created["recording_id"])
    recording_id = created["recording_id"]
    token = started["recording_token"]
    fingerprint = "hmac-sha256:" + "a" * 64
    service.ingest_extension_events(
        recording_id,
        ExtensionEventBatch.model_validate(
            {
                "batch_id": str(uuid4()),
                "recording_id": recording_id,
                "events": [
                    {
                        "event_id": str(uuid4()),
                        "client_sequence": 1,
                        "occurred_at": datetime.now(UTC),
                        "event_type": "click",
                        "page": {
                            "origin": "https://mes.example.test",
                            "path": "/orders",
                            "fingerprint": fingerprint,
                        },
                    }
                ],
            }
        ),
        token,
    )
    service.put_extension_credential(
        recording_id,
        "X-Access-Token",
        SecretStr("raw-private-token"),
        token,
    )
    stopped = service.stop_extension_recording(recording_id, token)
    persisted = repository.get_recording(recording_id)

    assert stopped["status"] == "recorded"
    assert persisted["trace"]["capture_source"] == "browser_extension"
    assert "raw-private-token" not in str(persisted)
    assert token not in str(persisted)


def test_extension_analysis_queue_returns_before_learning_finishes(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    started = Event()
    release = Event()

    class BlockingGraph:
        def invoke(self, state):
            started.set()
            assert release.wait(timeout=5)
            return {"final_status": "verified_candidate"}

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            self.cleared = recording_id

    extension = ClearableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        learning_graph_factory=lambda _system_code, _recording_id: BlockingGraph(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update({"status": "recorded", "trace": {"ui_events": []}})
    repository.save_recording(created["recording_id"], recording)

    queued = service.enqueue_extension_analysis(created["recording_id"])

    assert queued["status"] == "analyzing"
    assert started.wait(timeout=2)
    assert repository.get_recording(created["recording_id"])["status"] == "analyzing"
    release.set()
    deadline = monotonic() + 3
    while monotonic() < deadline:
        current = repository.get_recording(created["recording_id"])
        if current["status"] == "verified_candidate":
            break
        sleep(0.01)
    assert current["analysis_stage"] == "completed"
    assert extension.cleared is not None


def test_ui_only_trace_becomes_browser_candidate_without_api_verification(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class BrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            self.origins = allowed_origins
            return {
                "name": "查询订单",
                "execution_mode": "browser",
                "status": "candidate",
                "source_recording_id": trace["recording_id"],
                "steps": [{"action": "click"}],
            }

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            self.cleared = recording_id

    distiller = BrowserDistiller()
    extension = ClearableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        learning_graph_factory=lambda _system_code, _recording_id: FailingGraph(),
        browser_skill_distiller=distiller,
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "failure_stage": "system",
            "failure_reasons": ["旧的系统失败"],
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/orders",
                    }
                ],
                "api_exchanges": [],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "browser_candidate"
    assert result["analysis_stage"] == "awaiting_browser_verification"
    assert "failure_stage" not in result
    assert "failure_reasons" not in result
    assert result["learning_result"]["execution_mode"] == "browser"
    assert result["learning_result"]["verification_status"] == "pending_isolated_browser"
    assert distiller.origins == ["https://mes.example.test"]
    assert extension.cleared is not None


def test_api_rejection_is_preserved_when_browser_fallback_is_created(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class BrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            return {
                "name": "查询订单",
                "execution_mode": "browser",
                "status": "candidate",
                "source_recording_id": trace["recording_id"],
                "steps": [{"action": "click"}],
            }

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            pass

    api_rejection = {
        "final_status": "rejected",
        "failure_stage": "analysis",
        "failure_reasons": ["无法确认主业务 API。"],
    }
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=ClearableExtension(),
        learning_graph_factory=lambda _system_code, _recording_id: Graph(api_rejection),
        browser_skill_distiller=BrowserDistiller(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/orders",
                    }
                ],
                "api_exchanges": [{"exchange_id": str(uuid4())}],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "browser_candidate"
    assert result["api_learning_result"] == api_rejection


def test_api_rejection_reason_survives_crashed_browser_fallback(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class CrashingBrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            raise RuntimeError("private model provider response")

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            pass

    api_rejection = {
        "final_status": "rejected",
        "failure_stage": "analysis",
        "failure_reasons": ["字段对应关系证据不足"],
    }
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=ClearableExtension(),
        learning_graph_factory=lambda _system_code, _recording_id: Graph(api_rejection),
        browser_skill_distiller=CrashingBrowserDistiller(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/orders",
                    }
                ],
                "api_exchanges": [{"exchange_id": str(uuid4())}],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "needs_reteach"
    assert result["failure_reasons"] == ["字段对应关系证据不足"]
    assert "private model provider response" not in str(result)
