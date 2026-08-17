from uuid import uuid4

import pytest

from app.command_center.schemas import SkillDefinition
from app.command_center.task_session_inputs import (
    InputSchemaError,
    collect_skill_inputs,
)


def _skill(inputs):
    return SkillDefinition.model_validate(
        {
            "skill_id": str(uuid4()),
            "version": 1,
            "name": "测试能力",
            "description": "测试通用输入收集",
            "status": "published",
            "trigger_examples": ["测试"],
            "source_recording_id": str(uuid4()),
            "inputs": inputs,
            "outputs": [],
            "steps": [
                {
                    "step_id": "query",
                    "name": "查询",
                    "tool_id": "test:query",
                    "input_bindings": {},
                    "side_effect": "read",
                }
            ],
            "success_conditions": [],
        }
    )


def test_one_missing_scalar_returns_question():
    result = collect_skill_inputs(
        _skill(
            [
                {
                    "name": "amount",
                    "type": "number",
                    "description": "报销金额",
                }
            ]
        ),
        supplied={},
        trusted_context={},
    )

    assert result.complete is False
    assert result.interaction.type == "question"
    assert result.interaction.field_names == ["amount"]


def test_complex_array_returns_schema_form():
    result = collect_skill_inputs(
        _skill(
            [
                {
                    "name": "items",
                    "type": "array",
                    "description": "费用明细",
                    "json_schema": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["category", "amount"],
                            "properties": {
                                "category": {"type": "string"},
                                "amount": {"type": "number"},
                            },
                        },
                    },
                }
            ]
        ),
        supplied={},
        trusted_context={},
    )

    assert result.interaction.type == "form"
    assert result.interaction.schema_["properties"]["items"]["type"] == "array"


def test_trusted_context_value_records_provenance():
    result = collect_skill_inputs(
        _skill(
            [
                {
                    "name": "employee_id",
                    "type": "string",
                    "description": "员工编号",
                    "source_hint": "employee.id",
                }
            ]
        ),
        supplied={},
        trusted_context={"employee": {"id": "E-9"}},
    )

    assert result.values == {"employee_id": "E-9"}
    assert result.sources["employee_id"].kind == "trusted_context"


def test_complex_input_without_json_schema_is_not_guessed():
    with pytest.raises(InputSchemaError, match="json_schema"):
        collect_skill_inputs(
            _skill(
                [
                    {
                        "name": "items",
                        "type": "array",
                        "description": "明细",
                    }
                ]
            ),
            supplied={},
            trusted_context={},
        )


def test_unknown_input_is_rejected_instead_of_ignored():
    with pytest.raises(InputSchemaError, match="unknown Skill inputs"):
        collect_skill_inputs(
            _skill([]), supplied={"invented": 1}, trusted_context={}
        )


def test_unsupported_schema_composition_is_rejected():
    with pytest.raises(InputSchemaError, match="unsupported"):
        collect_skill_inputs(
            _skill(
                [
                    {
                        "name": "payload",
                        "type": "object",
                        "description": "对象",
                        "json_schema": {
                            "type": "object",
                            "oneOf": [{"type": "object"}],
                        },
                    }
                ]
            ),
            supplied={"payload": {}},
            trusted_context={},
        )
