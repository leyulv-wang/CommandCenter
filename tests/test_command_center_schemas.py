from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.command_center.schemas import SkillDefinition


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
                "input_bindings": {"item_name": "task.content.item_name"},
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
