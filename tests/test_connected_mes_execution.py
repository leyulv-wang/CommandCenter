from uuid import uuid4

import httpx

from app.command_center.execution_graph import (
    ExecutionDependencies,
    UserRequestReader,
    build_execution_graph,
    executable_skill_set,
)
from app.command_center.schemas import (
    SkillDefinition,
    TaskMatchDecision,
    VerificationResult,
)
from app.command_center.testing import SkillRunner
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition, ToolParameter
from app.command_center.tool_executor import ToolExecutor


def verified_query_skill():
    return SkillDefinition.model_validate(
        {
            "skill_id": str(uuid4()),
            "version": 1,
            "name": "查询采购申请列表",
            "description": "分页查询 MES 采购申请",
            "status": "verified_candidate",
            "trigger_examples": ["查询采购申请列表"],
            "source_recording_id": str(uuid4()),
            "inputs": [
                {
                    "name": "pageNo",
                    "type": "integer",
                    "description": "页码",
                    "required": True,
                },
                {
                    "name": "pageSize",
                    "type": "integer",
                    "description": "每页数量",
                    "required": True,
                },
            ],
            "outputs": [],
            "steps": [
                {
                    "step_id": "query",
                    "name": "查询",
                    "tool_id": "yifeng_mes:listPurchaseApply",
                    "input_bindings": {
                        "query.pageNo": "task.content.pageNo",
                        "query.pageSize": "task.content.pageSize",
                    },
                    "side_effect": "read",
                }
            ],
            "success_conditions": [],
        }
    )


class QueryAgent:
    def match_request(self, user_request, tasks, skills):
        return TaskMatchDecision(
            candidate_task_ids=[tasks[0]["task_id"]],
            selected_skill_id=skills[0].skill_id,
            literals={"pageNo": 2, "pageSize": 5},
            summary="选择采购申请查询 Skill",
        )

    def verify_result(self, skill, step_results, observed_state):
        return VerificationResult(
            status="passed",
            summary="查询完成",
            side_effects={},
            duplicate_detected=False,
        )


def test_verified_mes_skill_executes_from_natural_language_with_saved_credential():
    observed = {}

    def handler(request):
        observed["method"] = request.method
        observed["query"] = dict(request.url.params)
        observed["token"] = request.headers.get("X-Access-Token")
        return httpx.Response(200, json={"result": {"records": [{"id": "A-1"}]}})

    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="yifeng_mes:listPurchaseApply",
                system_code="yifeng_mes",
                operation_id="listPurchaseApply",
                method="GET",
                base_url="https://mes.test",
                path_template="/purchase/apply/list",
                content_type=None,
                side_effect="read",
                credential_header="X-Access-Token",
                parameters=(
                    ToolParameter("pageNo", "query", "integer", True, "页码"),
                    ToolParameter("pageSize", "query", "integer", True, "每页数量"),
                ),
            )
        ]
    )
    skill = verified_query_skill()
    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [skill],
            business_reader=UserRequestReader(),
            agents=QueryAgent(),
            runner=SkillRunner(
                ToolExecutor(
                    catalog,
                    httpx.Client(transport=httpx.MockTransport(handler)),
                    credential_provider=lambda _: {
                        "X-Access-Token": "stored-test-credential"
                    },
                )
            ),
        )
    )

    result = graph.invoke({"user_request": "查询采购申请列表第二页，每页5条"})

    assert result["status"] == "succeeded"
    assert observed == {
        "method": "GET",
        "query": {"pageNo": "2", "pageSize": "5"},
        "token": "stored-test-credential",
    }
    assert result["final_response"]["outputs"]["query"]["result"]["records"] == [
        {"id": "A-1"}
    ]
    assert "stored-test-credential" not in str(result)


def test_missing_required_agent_input_fails_before_tool_execution():
    skill = verified_query_skill()

    class MissingInputAgent(QueryAgent):
        def match_request(self, user_request, tasks, skills):
            return TaskMatchDecision(
                candidate_task_ids=[tasks[0]["task_id"]],
                selected_skill_id=skills[0].skill_id,
                literals={"pageNo": 1},
                summary="缺少每页数量",
            )

    class NeverRunner:
        def run(self, *args, **kwargs):
            raise AssertionError("Tool must not run")

    graph = build_execution_graph(
        ExecutionDependencies(
            skills=lambda: [skill],
            business_reader=UserRequestReader(),
            agents=MissingInputAgent(),
            runner=NeverRunner(),
        )
    )

    result = graph.invoke({"user_request": "查询第一页采购申请"})

    assert result["status"] == "failed"
    assert result["errors"] == ["Skill 必填输入不完整"]


def test_verified_write_candidate_is_available_to_employee_execution():
    read_skill = verified_query_skill()
    write_step = read_skill.steps[0].model_copy(
        update={
            "side_effect": "write",
            "idempotency_key_template": "{skill_id}:{source_object_id}:{step_id}",
        }
    )
    write_skill = read_skill.model_copy(update={"steps": [write_step]})
    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="yifeng_mes:listPurchaseApply",
                system_code="yifeng_mes",
                operation_id="listPurchaseApply",
                method="GET",
                base_url="https://mes.test",
                path_template="/purchase/apply/list",
                content_type=None,
                side_effect="write",
            )
        ]
    )

    assert executable_skill_set([], [write_skill], catalog) == [write_skill]
