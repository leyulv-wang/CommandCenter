from datetime import UTC, datetime
from uuid import uuid4

from app.command_center.repository import CommandCenterRepository
from app.command_center.router import CreateRecordingRequest, CreateTaskRunRequest
from app.command_center.schemas import OperationTrace
from app.command_center.service import CommandCenterService


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
