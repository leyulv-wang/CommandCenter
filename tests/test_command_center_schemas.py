from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.command_center.schemas import (
    DemonstrationAnalysis,
    InputBinding,
    SkillDefinition,
)


def valid_skill_payload() -> dict[str, object]:
    return {
        "skill_id": str(uuid4()),
        "version": 1,
        "name": "创建采购并回写",
        "description": "根据办公用品任务创建采购申请并回写单号",
        "status": "candidate",
        "trigger_examples": ["处理签字笔库存不足任务"],
        "source_recording_id": str(uuid4()),
        "inputs": [
            {
                "name": "item_name",
                "type": "string",
                "description": "物品名称",
                "required": True,
            }
        ],
        "outputs": [],
        "steps": [
            {
                "step_id": "create_purchase",
                "name": "创建采购申请",
                "tool_id": "connected_system:start_workflow",
                "input_bindings": {"body.item_name": "task.content.item_name"},
                "output_bindings": {"purchase_request_id": "data.id"},
                "side_effect": "write",
                "idempotency_key_template": "{skill_id}:{source_object_id}:{step_id}",
            }
        ],
        "success_conditions": [],
    }


def test_skill_rejects_arbitrary_binding_code():
    payload = valid_skill_payload()
    payload["steps"][0]["input_bindings"]["item_name"] = "python:__import__('os')"

    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(payload)


def test_write_step_requires_idempotency_template():
    payload = valid_skill_payload()
    payload["steps"][0]["idempotency_key_template"] = None

    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(payload)


def test_tool_binding_target_must_identify_path_or_body():
    payload = valid_skill_payload()
    payload["steps"][0]["input_bindings"] = {
        "item_name": "task.content.item_name"
    }

    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(payload)


def test_demonstration_analysis_exposes_binding_pattern_to_agents():
    schema = DemonstrationAnalysis.model_json_schema()
    expression = schema["$defs"]["InputBinding"]["properties"]["expression"]

    assert expression["pattern"] == r"^(task|steps|literal)\..+$"


def test_skill_definition_exposes_same_binding_pattern_to_agents():
    schema = SkillDefinition.model_json_schema()
    values = schema["$defs"]["SkillStep"]["properties"]["input_bindings"]

    assert values["additionalProperties"]["pattern"] == (
        r"^(task|steps|literal)\..+$"
    )


@pytest.mark.parametrize(
    "expression",
    [
        "task.content.quantity",
        "steps.create.output.data.id",
        "literal.item_name",
    ],
)
def test_binding_protocol_accepts_all_generic_sources(expression):
    binding = InputBinding(
        tool_field="body.value",
        expression=expression,
    )

    assert binding.expression == expression


@pytest.mark.parametrize(
    "expression",
    ["literal('value')", "raw-value", "python:run()"],
)
def test_binding_protocol_rejects_non_path_expressions(expression):
    with pytest.raises(ValidationError):
        InputBinding(tool_field="body.value", expression=expression)
