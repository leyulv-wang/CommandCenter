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
from tests.test_command_center_schemas import valid_skill_payload


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
            literals={
                "applicant": "行政部",
                "item_name": "打印纸",
                "quantity": 10,
                "reason": "办公使用",
            },
            summary="匹配创建采购申请 Skill",
        )

    def verify_result(self, skill, step_results, observed_state):
        return VerificationResult(
            status="passed",
            side_effects={"purchase_count": 1},
            duplicate_detected=False,
            summary="采购申请创建完成",
        )


class RecordingRunner:
    def __init__(self):
        self.tasks = []
        self.literals = []

    def run(self, skill, task, *, run_id, literals=None):
        self.tasks.append(task)
        self.literals.append(literals)
        return SkillRunResult(
            status="succeeded",
            step_results=[],
            outputs={"create_purchase": {"data": {"id": "WORKFLOW-0001"}}},
        )


def published_skill() -> SkillDefinition:
    payload = valid_skill_payload()
    payload["status"] = "published"
    payload["name"] = "创建采购申请"
    payload["steps"] = [
        {
            "step_id": "create_purchase",
            "name": "创建采购申请",
            "tool_id": "connected_system:create_purchase",
            "input_bindings": {
                "body.applicant": "literal.applicant",
                "body.item_name": "literal.item_name",
                "body.quantity": "literal.quantity",
                "body.reason": "literal.reason",
            },
            "output_bindings": {},
            "side_effect": "write",
            "idempotency_key_template": "fixed",
        }
    ]
    return SkillDefinition.model_validate(payload)


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
        "system_code": "connected_system",
        "task_id": "purchase-request-input",
        "content": {},
    }
    runner = RecordingRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [published_skill()],
            business_reader=BusinessReader([task]),
            agents=MatchingAgent(["purchase-request-input"]),
            runner=runner,
        )
    )

    result = graph.invoke({"user_request": "帮我为行政部采购10箱打印纸"})

    assert result["status"] == "succeeded"
    assert result["verification_result"].status == "passed"
    assert result["final_response"]["summary"] == "采购申请创建完成"
    assert runner.tasks[0]["system_code"] == "connected_system"
    assert runner.literals[0]["item_name"] == "打印纸"


def test_local_business_reader_builds_procurement_input_without_task_api():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"items": []})

    reader = LocalBusinessReader(
        httpx.Client(transport=httpx.MockTransport(handler)),
        {
            "onboarding_system": "http://onboarding",
            "connected_system": "http://connected",
        },
    )

    tasks = reader.search_tasks("帮我为行政部采购10箱打印纸")

    assert calls == []
    assert tasks == [
        {
            "system_code": "connected_system",
            "task_id": tasks[0]["task_id"],
            "content": {},
            "user_request": "帮我为行政部采购10箱打印纸",
        }
    ]
