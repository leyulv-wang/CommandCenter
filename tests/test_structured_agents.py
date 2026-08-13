import json
from copy import deepcopy
from uuid import uuid4

import pytest

from app.command_center.agents import AgentSuite
from app.command_center.model import StructuredModel
from app.command_center.schemas import (
    APIAttributionAnalysis,
    DemonstrationAnalysis,
    FieldMappingAnalysis,
    SkillDefinition,
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
        if schema.__name__ == "TestPlan":
            skill = payload["skill"]
            return schema.model_validate(
                {
                    "skill_id": str(skill.skill_id),
                    "skill_version": skill.version,
                    "cases": [
                        {
                            "case_id": category,
                            "category": category,
                            "description": category,
                            "fixture": {},
                            "invocation": {},
                            "expected": {},
                        }
                        for category in (
                            "normal",
                            "parameter_variation",
                            "idempotency",
                        )
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


def test_test_design_agent_places_every_binding_namespace_in_executable_context():
    model = PromptCapturingModel()
    agents = AgentSuite(model)
    skill = SkillDefinition.model_validate(valid_skill_payload())

    agents.design_tests(skill)

    prompt = model.prompts[-1]
    assert "task.*" in prompt
    assert "fixture.source_task" in prompt
    assert "literal.*" in prompt
    assert "invocation" in prompt
    assert "steps.*" in prompt
    assert "前序步骤" in prompt


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


class FieldMappingPromptModel:
    def __init__(self):
        self.prompt = ""

    def generate(self, schema, system_prompt, payload):
        self.prompt = system_prompt
        return schema.model_validate(
            {"mappings": [], "uncertainties": [], "compilable": True}
        )


def test_field_mapping_agent_uses_query_fingerprint_equality_without_name_guessing():
    model = FieldMappingPromptModel()
    AgentSuite(model).map_fields(
        APIAttributionAnalysis.model_validate(
            {"segments": [], "uncertainties": [], "attributable": True}
        ),
        {"ui_events": [], "api_exchanges": []},
        {"tools": []},
    )

    assert "HMAC 指纹相同只能证明值相等" in model.prompt
    assert "控件语义、操作时序" in model.prompt
    assert "不能只根据字段名称" in model.prompt
    assert "指纹缺失或不相等" in model.prompt


class CrossSystemCompileModel:
    def generate(self, schema, system_prompt, payload):
        self.prompt = system_prompt
        candidate = valid_skill_payload()
        candidate["steps"][0]["tool_id"] = "yifeng_mes:listPurchaseApply"
        candidate["steps"][0]["side_effect"] = "read"
        candidate["steps"][0]["idempotency_key_template"] = None
        return schema.model_validate(candidate)


def test_cross_system_compilation_requires_each_primary_system_in_skill():
    model = CrossSystemCompileModel()
    agents = AgentSuite(model)
    attribution = APIAttributionAnalysis.model_validate(
        {
            "segments": [
                {
                    "segment_id": "mes_read",
                    "primary_tool_ids": ["yifeng_mes:listPurchaseApply"],
                    "evidence_summary": "MES 查询",
                },
                {
                    "segment_id": "local_write",
                    "primary_tool_ids": ["connected_system:createPurchaseFollowUp"],
                    "evidence_summary": "本地创建跟进单",
                },
            ],
            "attributable": True,
        }
    )
    catalog = {
        "tools": [
            {"tool_id": "yifeng_mes:listPurchaseApply", "system_code": "yifeng_mes"},
            {"tool_id": "connected_system:createPurchaseFollowUp", "system_code": "connected_system"},
        ]
    }

    with pytest.raises(ValueError, match="primary system"):
        agents.compile_skill(
            FieldMappingAnalysis.model_validate(
                {"mappings": [], "uncertainties": [], "compilable": True}
            ),
            attribution,
            {"api_exchanges": []},
            catalog,
        )


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


class SegmentationPromptModel:
    def __init__(self):
        self.prompt = ""

    def generate(self, schema, system_prompt, payload):
        self.prompt = system_prompt
        return schema.model_validate(
            {
                "summary": "核心 API 证据充分，局部导航仍有不确定性",
                "segments": [],
                "uncertainties": [],
                "conclusive": True,
            }
        )


def test_segmentation_prompt_separates_local_uncertainty_from_overall_learnability():
    model = SegmentationPromptModel()
    AgentSuite(model).segment_trace({"ui_events": [], "api_exchanges": []})

    assert "整体是否足以继续学习" in model.prompt
    assert "局部不确定性" in model.prompt
    assert "不能仅因非核心导航" in model.prompt


class TraceProjectionCaptureModel:
    def __init__(self):
        self.payload = None

    def generate(self, schema, system_prompt, payload):
        self.payload = payload
        return schema.model_validate(
            {
                "summary": "保留完整证据标识的精简轨迹",
                "segments": [],
                "uncertainties": [],
                "conclusive": True,
            }
        )


def test_segmentation_receives_a_bounded_projection_without_mutating_audit_trace():
    event_id = uuid4()
    exchange_id = uuid4()
    mutation_id = uuid4()
    verbose_label = "采购跟进表单 " * 200
    trace = {
        "trace_id": str(uuid4()),
        "recording_id": str(uuid4()),
        "objective": "跨系统创建采购跟进任务",
        "source_task": {"task_id": "demo-task"},
        "started_at": "2026-08-13T05:00:00Z",
        "ended_at": "2026-08-13T05:01:00Z",
        "ui_events": [
            {
                "event_id": str(event_id),
                "sequence": 1,
                "timestamp": "2026-08-13T05:00:01Z",
                "page_url": "http://127.0.0.1:8101/operations?verbose=transport",
                "action_type": "click",
                "target": {
                    "system_code": "connected_system",
                    "tab_id": 12,
                    "accessible_name": verbose_label,
                    "page_fingerprint": "hmac-sha256:" + "a" * 64,
                    "empty": None,
                },
                "value_ref": None,
                "screenshot_ref": "large-screenshot-reference",
            }
        ],
        "api_exchanges": [
            {
                "exchange_id": str(exchange_id),
                "sequence": 2,
                "started_at": "2026-08-13T05:00:02Z",
                "completed_at": "2026-08-13T05:00:03Z",
                "system_code": "connected_system",
                "method": "POST",
                "path": "/api/purchase-follow-ups",
                "request_body": {
                    "query_parameter_names": [],
                    "query_parameter_fingerprints": {},
                    "request_fingerprint": "hmac-sha256:" + "b" * 64,
                    "endpoint_fingerprint": "hmac-sha256:" + "c" * 64,
                },
                "response_status": 201,
                "response_body": {"response_fingerprint": None},
                "matched_tool_id": "connected_system:create_purchase_follow_up",
                "match_status": "matched",
            }
        ],
        "page_mutations": [
            {
                "mutation_id": str(mutation_id),
                "client_sequence": 3,
                "occurred_at": "2026-08-13T05:00:04Z",
                "system_code": "connected_system",
                "tab_id": 12,
                "page": {"url": "http://127.0.0.1:8101/operations"},
                "mutation_type": "form_state_change",
                "changed_control_fingerprints": ["hmac-sha256:" + "d" * 64],
                "before_fingerprint": None,
                "after_fingerprint": "hmac-sha256:" + "e" * 64,
            }
        ],
        "redaction_summary": {"redacted_field_count": 2},
    }
    original = deepcopy(trace)
    model = TraceProjectionCaptureModel()

    AgentSuite(model).segment_trace(trace)

    projected = model.payload["trace"]
    assert trace == original
    assert projected["ui_events"][0]["event_id"] == str(event_id)
    assert projected["api_exchanges"][0]["exchange_id"] == str(exchange_id)
    assert projected["page_mutations"][0]["mutation_id"] == str(mutation_id)
    assert projected["ui_events"][0]["target"]["system_code"] == "connected_system"
    assert projected["api_exchanges"][0]["matched_tool_id"].startswith(
        "connected_system:"
    )
    assert len(projected["ui_events"][0]["target"]["accessible_name"]) <= 320
    assert projected["ui_events"][0]["page_path"] == "/operations"
    assert "page_url" not in projected["ui_events"][0]
    assert "page_fingerprint" not in projected["ui_events"][0]["target"]
    assert "changed_control_fingerprints" not in projected["page_mutations"][0]
    assert projected["page_mutations"][0]["changed_control_count"] == 1
    assert "timestamp" not in projected["ui_events"][0]
    assert "screenshot_ref" not in projected["ui_events"][0]
    assert "started_at" not in projected["api_exchanges"][0]
    assert len(json.dumps(projected, ensure_ascii=False)) < len(
        json.dumps(trace, ensure_ascii=False)
    ) / 2


class MultiSystemSegmentationModel:
    def __init__(self):
        self.payloads = []

    def generate(self, schema, system_prompt, payload):
        self.payloads.append(payload)
        if "system_analyses" in payload:
            event_ids = [
                event["event_id"]
                for analysis in payload["system_analyses"]
                for segment in analysis["analysis"]["segments"]
                for event in [
                    {"event_id": segment["source_ui_event_ids"][0]}
                ]
            ]
            return schema.model_validate(
                {
                    "summary": "协调两个系统的阶段结论",
                    "segments": [
                        {
                            "segment_id": f"cross_{index}",
                            "sequence": index,
                            "classification": "business_action",
                            "summary": "系统阶段",
                            "source_ui_event_ids": [event_id],
                        }
                        for index, event_id in enumerate(event_ids, 1)
                    ],
                    "conclusive": True,
                }
            )
        event = payload["trace"]["ui_events"][0]
        return schema.model_validate(
            {
                "summary": "单系统阶段",
                "segments": [
                    {
                        "segment_id": "local_segment",
                        "sequence": 1,
                        "classification": "business_action",
                        "summary": "系统操作",
                        "source_ui_event_ids": [event["event_id"]],
                    }
                ],
                "conclusive": True,
            }
        )


def test_multi_system_segmentation_uses_per_system_agents_before_coordination():
    mes_event_id = uuid4()
    local_event_id = uuid4()
    trace = {
        "objective": "跨系统创建采购跟进任务",
        "ui_events": [
            {
                "event_id": str(mes_event_id),
                "sequence": 1,
                "action_type": "click",
                "page_url": "http://mes.example/purchase",
                "target": {"system_code": "yifeng_mes", "accessible_name": "查询"},
            },
            {
                "event_id": str(local_event_id),
                "sequence": 2,
                "action_type": "submit",
                "page_url": "http://127.0.0.1:8101/",
                "target": {
                    "system_code": "connected_system",
                    "accessible_name": "创建跟进任务",
                },
            },
        ],
        "api_exchanges": [],
        "page_mutations": [],
    }
    model = MultiSystemSegmentationModel()

    result = AgentSuite(model).segment_trace(trace)

    assert len(model.payloads) == 3
    subsystem_payloads = model.payloads[:2]
    assert [
        payload["system_code"] for payload in subsystem_payloads
    ] == ["yifeng_mes", "connected_system"]
    assert all(len(payload["trace"]["ui_events"]) == 1 for payload in subsystem_payloads)
    coordinator = model.payloads[2]
    assert [
        item["system_code"] for item in coordinator["system_analyses"]
    ] == ["yifeng_mes", "connected_system"]
    assert {str(event_id) for segment in result.segments for event_id in segment.source_ui_event_ids} == {
        str(mes_event_id),
        str(local_event_id),
    }
