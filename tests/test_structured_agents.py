import json
from uuid import uuid4

from app.command_center.agents import AgentSuite
from app.command_center.model import StructuredModel
from app.command_center.schemas import DemonstrationAnalysis, TestPlan as SkillTestPlan
from app.command_center.tool_catalog import ToolCatalog
from tests.test_command_center_schemas import valid_skill_payload


def test_structured_model_retries_once_after_schema_validation_failure():
    responses = iter(
        [
            json.dumps({"summary": "缺少必要字段"}),
            json.dumps(
                {
                    "summary": "识别出采购创建和回写",
                    "business_actions": [],
                    "ignored_ui_event_ids": [],
                    "uncertainties": [],
                    "compilable": True,
                }
            ),
        ]
    )
    calls: list[list[dict[str, str]]] = []

    def complete(messages):
        calls.append(messages)
        return next(responses)

    model = StructuredModel(completion=complete)

    result = model.generate(
        DemonstrationAnalysis,
        "分析演示",
        {"trace": {"api_exchanges": []}},
    )

    assert result.compilable is True
    assert len(calls) == 2
    assert "校验失败" in calls[1][-1]["content"]


class SchemaAwareModel:
    def generate(self, schema, system_prompt, payload):
        if schema.__name__ == "DemonstrationAnalysis":
            return schema.model_validate(
                {
                    "summary": "创建采购并回写",
                    "business_actions": [],
                    "ignored_ui_event_ids": [],
                    "uncertainties": [],
                    "compilable": True,
                }
            )
        if schema.__name__ == "SkillDefinition":
            return schema.model_validate(valid_skill_payload())
        if schema.__name__ == "TestPlan":
            skill = payload["skill"]
            return schema.model_validate(
                {
                    "skill_id": str(skill.skill_id),
                    "skill_version": 1,
                    "cases": [
                        {
                            "case_id": category,
                            "category": category,
                            "description": category,
                            "fixture": {},
                            "invocation": {},
                            "expected": {},
                        }
                        for category in ("normal", "parameter_variation", "idempotency")
                    ],
                }
            )
        raise AssertionError(schema)


class PromptCapturingModel:
    def __init__(self):
        self.prompts = []

    def generate(self, schema, system_prompt, payload):
        self.prompts.append(system_prompt)
        if schema.__name__ == "DemonstrationAnalysis":
            return schema.model_validate(
                {
                    "summary": "识别到一个允许的业务动作",
                    "business_actions": [],
                    "ignored_ui_event_ids": [],
                    "uncertainties": [],
                    "compilable": True,
                }
            )
        if schema.__name__ == "SkillDefinition":
            return schema.model_validate(valid_skill_payload())
        raise AssertionError(schema)


def test_agent_suite_produces_three_required_test_categories():
    agents = AgentSuite(SchemaAwareModel())
    analysis = agents.analyze_demonstration({"trace_id": str(uuid4())}, {"tools": []})
    skill = agents.compile_skill(analysis, {"trace_id": str(uuid4())}, {"tools": []})

    plan = agents.design_tests(skill)

    assert isinstance(plan, SkillTestPlan)
    assert {case.category for case in plan.cases} == {
        "normal",
        "parameter_variation",
        "idempotency",
    }


def test_analysis_and_compilation_agents_share_generic_binding_protocol():
    model = PromptCapturingModel()
    agents = AgentSuite(model)
    analysis = agents.analyze_demonstration(
        {"trace_id": str(uuid4())},
        {"tools": []},
    )

    agents.compile_skill(
        analysis,
        {"trace_id": str(uuid4())},
        {"tools": []},
    )

    assert len(model.prompts) == 2
    for prompt in model.prompts:
        assert "task.content.quantity" in prompt
        assert "steps.create.output.data.id" in prompt
        assert "literal.item_name" in prompt
        assert "不能写成 literal(...)" in prompt
    analysis_prompt = model.prompts[0]
    assert "员工在 UI 或 API 请求中直接输入" in analysis_prompt
    assert "不要求预先存在于 task 上下文" in analysis_prompt
    assert "不能因此判定字段来源不确定" in analysis_prompt


def test_structured_model_serializes_tool_catalog_for_agent_prompt():
    captured = {}

    def complete(messages):
        captured["payload"] = json.loads(messages[1]["content"])
        return json.dumps(
            {
                "summary": "没有业务动作",
                "business_actions": [],
                "ignored_ui_event_ids": [],
                "uncertainties": [],
                "compilable": False,
            }
        )

    catalog = ToolCatalog.from_openapi_documents(
        {
            "connected_system": {
                "paths": {
                    "/api/workflows/start": {
                        "post": {"operationId": "start_workflow"}
                    }
                }
            }
        },
        {"connected_system": "http://127.0.0.1:8101"},
        {("connected_system", "start_workflow")},
    )

    StructuredModel(complete).generate(
        DemonstrationAnalysis,
        "分析演示",
        {"catalog": catalog},
    )

    assert captured["payload"]["catalog"]["tools"][0]["tool_id"] == (
        "connected_system:start_workflow"
    )
