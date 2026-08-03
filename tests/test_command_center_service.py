from datetime import UTC, datetime
from uuid import uuid4

from pydantic import SecretStr

from app.command_center.repository import CommandCenterRepository
from app.command_center.router import CreateRecordingRequest, CreateTaskRunRequest
from app.command_center.schemas import OperationTrace
from app.command_center.service import CommandCenterService
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
