from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.command_center.direct_tool_runner import DirectToolRunResult
from app.command_center.execution_graph import (
    ExecutionDependencies,
    LocalBusinessReader,
    UserRequestReader,
    build_execution_graph,
)
from app.command_center.schemas import (
    DirectToolPlan,
    DirectToolVerification,
    SkillDefinition,
    StepResult,
    TaskMatchDecision,
    VerificationResult,
)
from app.command_center.testing import SkillRunResult
from app.command_center.tool_catalog import ToolDefinition, ToolParameter
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


def read_tool():
    return ToolDefinition(
        tool_id="yifeng_mes:queryPageListUsingGET_183",
        system_code="yifeng_mes",
        operation_id="queryPageListUsingGET_183",
        method="GET",
        base_url="https://mes.test",
        path_template="/jeecg-boot/purchase/apply/list",
        content_type=None,
        description="查询采购申请列表",
        side_effect="read",
        parameters=(
            ToolParameter("applyBy", "query", "string", False, "请购人"),
        ),
    )


class DirectAgent(MatchingAgent):
    def __init__(self, plan_status="matched", direct_verification="passed"):
        super().__init__(["user-request"])
        self.plan_status = plan_status
        self.direct_verification = direct_verification
        self.direct_verification_calls = 0
        self.task_contexts = []

    def plan_tool_request(self, user_request, task_context, tools):
        self.task_contexts.append(task_context)
        if self.plan_status == "matched":
            return DirectToolPlan(
                status="matched",
                steps=[
                    {
                        "step_id": "query",
                        "tool_id": tools[0].tool_id,
                        "arguments": {"query": {"applyBy": "孟明佳"}},
                        "reason": "查询采购申请",
                    }
                ],
                summary="查询采购申请",
            )
        if self.plan_status == "needs_input":
            return DirectToolPlan(
                status="needs_input",
                missing_inputs=["请购人"],
                summary="缺少请购人",
            )
        return DirectToolPlan(
            status="not_applicable",
            summary="使用 Skill",
        )

    def verify_tool_result(self, user_request, plan, step_results):
        self.direct_verification_calls += 1
        return DirectToolVerification(
            status=self.direct_verification,
            summary="查询完成",
        )


class DirectRunner:
    def __init__(self, status="succeeded"):
        self.status = status
        self.calls = []

    def run(self, plan, *, run_id):
        self.calls.append((plan, run_id))
        now = datetime.now(UTC)
        step_result = StepResult(
            run_id=run_id,
            step_id="query",
            tool_id=plan.steps[0].tool_id,
            status=self.status,
            started_at=now,
            ended_at=now,
            normalized_output={"success": True, "result": {"records": []}},
        )
        return DirectToolRunResult(
            status=self.status,
            step_results=[step_result],
            outputs=(
                {"query": step_result.normalized_output}
                if self.status == "succeeded"
                else {}
            ),
            evidence=[
                {
                    "step_id": "query",
                    "tool_id": plan.steps[0].tool_id,
                    "arguments": plan.steps[0].arguments,
                    "status": self.status,
                    "request_summary": {"method": "GET", "path": "/list"},
                    "response_summary": {"status_code": 200},
                }
            ],
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


def test_execution_graph_merges_agent_inputs_into_generic_task_context():
    runner = RecordingRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [published_skill()],
            business_reader=UserRequestReader(),
            agents=MatchingAgent(["user-request"]),
            runner=runner,
        )
    )

    result = graph.invoke({"user_request": "查询第二页采购申请"})

    assert result["status"] == "succeeded"
    assert runner.tasks[0]["content"]["item_name"] == "打印纸"
    assert runner.tasks[0]["user_request"] == "查询第二页采购申请"


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


def test_execution_graph_uses_direct_tool_before_skill_matching():
    agents = DirectAgent()
    direct_runner = DirectRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [],
            business_reader=UserRequestReader(),
            agents=agents,
            runner=RecordingRunner(),
            tools=lambda: [read_tool()],
            direct_runner=direct_runner,
        )
    )

    result = graph.invoke({"user_request": "查询孟明佳的采购申请"})

    assert result["status"] == "succeeded"
    assert result["execution_mode"] == "tool"
    assert result["final_response"]["outputs"]["query"]["success"] is True
    assert result["final_response"]["tool_evidence"][0]["tool_id"].startswith(
        "yifeng_mes:"
    )
    assert len(direct_runner.calls) == 1


def test_execution_graph_falls_back_to_existing_skill_when_tool_not_applicable():
    agents = DirectAgent(plan_status="not_applicable")
    skill_runner = RecordingRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [published_skill()],
            business_reader=UserRequestReader(),
            agents=agents,
            runner=skill_runner,
            tools=lambda: [read_tool()],
            direct_runner=DirectRunner(),
        )
    )

    result = graph.invoke({"user_request": "创建采购申请"})

    assert result["status"] == "succeeded"
    assert result["execution_mode"] == "skill"
    assert len(skill_runner.tasks) == 1


def test_execution_graph_stops_when_direct_tool_needs_input():
    direct_runner = DirectRunner()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [published_skill()],
            business_reader=UserRequestReader(),
            agents=DirectAgent(plan_status="needs_input"),
            runner=RecordingRunner(),
            tools=lambda: [read_tool()],
            direct_runner=direct_runner,
        )
    )

    result = graph.invoke({"user_request": "查询一个人的采购申请"})

    assert result["status"] == "needs_input"
    assert result["errors"] == ["完成任务还需要：请购人"]
    assert direct_runner.calls == []


def test_execution_graph_does_not_verify_failed_direct_tool_run():
    agents = DirectAgent()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [],
            business_reader=UserRequestReader(),
            agents=agents,
            runner=RecordingRunner(),
            tools=lambda: [read_tool()],
            direct_runner=DirectRunner(status="failed"),
        )
    )

    result = graph.invoke({"user_request": "查询采购申请"})

    assert result["status"] == "failed"
    assert result["execution_mode"] == "tool"
    assert agents.direct_verification_calls == 0


def test_execution_graph_passes_trusted_selected_record_to_tool_planner():
    agents = DirectAgent()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [],
            business_reader=UserRequestReader(),
            agents=agents,
            runner=RecordingRunner(),
            tools=lambda: [read_tool()],
            direct_runner=DirectRunner(),
        )
    )

    graph.invoke(
        {
            "user_request": "查看所选采购申请详情",
            "task_context": {
                "selected_record": {"id": "row-1", "applyNo": "10"}
            },
        }
    )

    assert agents.task_contexts[0]["content"]["selected_record"] == {
        "id": "row-1",
        "applyNo": "10",
    }
