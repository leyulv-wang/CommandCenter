import httpx

from app.command_center.execution_graph import (
    ExecutionDependencies,
    LocalBusinessReader,
    build_execution_graph,
)
from app.command_center.schemas import (
    SkillDefinition,
    TaskMatchDecision,
    VerificationResult,
)
from app.command_center.testing import SkillRunResult
from tests.test_skill_runner import two_step_skill


class BusinessReader:
    def __init__(self, tasks):
        self.tasks = tasks

    def search_tasks(self, user_request):
        return self.tasks

    def observe(self, task):
        return {"task": {**task, "status": "processing"}, "purchase_count": 1}


class MatchingAgent:
    def __init__(self, task_ids):
        self.task_ids = task_ids

    def match_request(self, user_request, tasks, skills):
        return TaskMatchDecision(
            candidate_task_ids=self.task_ids,
            selected_skill_id=skills[0].skill_id,
            literals={},
            summary="匹配库存不足任务",
        )

    def verify_result(self, skill, step_results, observed_state):
        return VerificationResult(
            status="passed",
            side_effects={"purchase_count": 1},
            duplicate_detected=False,
            summary="采购创建并回写完成",
        )


class RecordingRunner:
    def __init__(self):
        self.tasks = []

    def run(self, skill, task, *, run_id, literals=None):
        self.tasks.append(task)
        return SkillRunResult(
            status="succeeded",
            step_results=[],
            outputs={"create_purchase": {"data": {"id": "WORKFLOW-0001"}}},
        )


def published_skill() -> SkillDefinition:
    return two_step_skill().model_copy(update={"status": "published"})


def test_execution_graph_requires_employee_choice_for_multiple_objects():
    tasks = [
        {"task_id": "OFFICE-1", "content": {"item_name": "签字笔"}},
        {"task_id": "OFFICE-2", "content": {"item_name": "打印纸"}},
    ]
    runner = RecordingRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [published_skill()],
            business_reader=BusinessReader(tasks),
            agents=MatchingAgent(["OFFICE-1", "OFFICE-2"]),
            runner=runner,
        )
    )

    result = graph.invoke({"user_request": "处理库存不足任务"})

    assert result["status"] == "needs_object_selection"
    assert len(result["candidate_objects"]) == 2
    assert runner.tasks == []


def test_execution_graph_executes_selected_skill_and_verifies_result():
    task = {
        "system_code": "onboarding_system",
        "task_id": "OFFICE-1",
        "content": {"item_name": "签字笔", "quantity": 10},
    }
    runner = RecordingRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [published_skill()],
            business_reader=BusinessReader([task]),
            agents=MatchingAgent(["OFFICE-1"]),
            runner=runner,
        )
    )

    result = graph.invoke({"user_request": "处理签字笔库存不足任务"})

    assert result["status"] == "succeeded"
    assert result["verification_result"].status == "passed"
    assert result["final_response"]["summary"] == "采购创建并回写完成"
    assert runner.tasks[0]["task_id"] == "OFFICE-1"


def test_local_business_reader_returns_pending_tasks_with_system_identity():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tasks":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "task_id": "OFFICE-1",
                            "content": {"item_name": "签字笔", "quantity": 10},
                            "status": "pending",
                        }
                    ]
                },
            )
        raise AssertionError(request.url)

    reader = LocalBusinessReader(
        httpx.Client(transport=httpx.MockTransport(handler)),
        {
            "onboarding_system": "http://onboarding",
            "connected_system": "http://connected",
        },
    )

    tasks = reader.search_tasks("处理签字笔库存不足任务")

    assert tasks[0]["system_code"] == "onboarding_system"
    assert tasks[0]["task_id"] == "OFFICE-1"
