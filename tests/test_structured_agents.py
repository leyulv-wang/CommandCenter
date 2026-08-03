import json
from uuid import uuid4

from app.command_center.agents import AgentSuite
from app.command_center.model import StructuredModel
from app.command_center.schemas import (
    APIAttributionAnalysis,
    DemonstrationAnalysis,
    FieldMappingAnalysis,
    TestPlan as SkillTestPlan,
)
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
        if schema.__name__ == "VerificationResult":
            return schema.model_validate(
                {
                    "status": "passed",
                    "conditions": [],
                    "side_effects": {},
                    "duplicate_detected": False,
                    "summary": "状态变化与执行结果一致",
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


def test_compilation_agent_requires_reusable_success_conditions():
    model = PromptCapturingModel()
    agents = AgentSuite(model)
    analysis = agents.analyze_demonstration(
        {"trace_id": str(uuid4())},
        {"tools": []},
    )

    agents.compile_skill(
        analysis,
        {
            "api_exchanges": [
                {"response_body": {"data": {"id": "DEMO-OBJECT-0001"}}}
            ]
        },
        {"tools": []},
    )

    compilation_prompt = model.prompts[-1]
    assert "成功条件必须描述可复用的业务不变量" in compilation_prompt
    assert "不得把演示返回的业务对象 ID" in compilation_prompt
    assert "新执行产生的对象标识允许变化" in compilation_prompt


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


def test_verifier_treats_declared_write_as_known_effect_not_unknown_effect():
    model = PromptCapturingModel()
    agents = AgentSuite(model)

    agents.verify_result(
        valid_skill_payload(),
        [],
        {
            "_execution_evidence": {
                "before_state": {"objects": []},
                "after_state": {"objects": [{"id": "OBJECT-1"}]},
            }
        },
    )

    prompt = model.prompts[-1]
    assert "occurred=true 表示已知写操作" in prompt
    assert "不能仅因发生写操作而判定为未知副作用" in prompt
    assert "执行前后状态" in prompt


def test_api_attribution_and_query_field_mapping_are_structured():
    exchange_id = uuid4()
    ui_event_id = uuid4()
    attribution = APIAttributionAnalysis.model_validate(
        {
            "segments": [
                {
                    "segment_id": "query_purchase",
                    "primary_tool_ids": ["yifeng_mes:listPurchaseApply"],
                    "primary_exchange_ids": [str(exchange_id)],
                    "evidence_summary": "页面查询动作紧邻采购申请列表请求",
                }
            ],
            "attributable": True,
        }
    )
    mapping = FieldMappingAnalysis.model_validate(
        {
            "mappings": [
                {
                    "skill_input_name": "apply_no",
                    "api_target": "query.applyNo",
                    "source_ui_event_ids": [str(ui_event_id)],
                    "source_exchange_ids": [str(exchange_id)],
                    "transformation": "identity",
                    "evidence_summary": "页面申请单号与请求 applyNo 相同",
                }
            ],
            "uncertainties": [],
            "compilable": True,
        }
    )

    assert attribution.segments[0].primary_tool_ids == [
        "yifeng_mes:listPurchaseApply"
    ]
    assert mapping.mappings[0].api_target == "query.applyNo"


class SegmentationOnlyModel:
    def generate(self, schema, system_prompt, payload):
        return schema.model_validate(
            {
                "summary": "一个片段",
                "segments": [
                    {
                        "segment_id": "segment_1",
                        "sequence": 1,
                        "classification": "business_action",
                        "summary": "查询",
                        "source_ui_event_ids": [str(uuid4())],
                    }
                ],
                "conclusive": True,
            }
        )


def test_segmentation_rejects_evidence_ids_missing_from_trace():
    agents = AgentSuite(SegmentationOnlyModel())

    try:
        agents.segment_trace({"ui_events": [], "api_exchanges": []})
    except ValueError as error:
        assert "unknown UI event" in str(error)
    else:
        raise AssertionError("unknown evidence reference was accepted")
