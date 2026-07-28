import json
from uuid import uuid4

from app.command_center.agents import AgentSuite
from app.command_center.model import StructuredModel
from app.command_center.schemas import DemonstrationAnalysis, TestPlan as SkillTestPlan
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
