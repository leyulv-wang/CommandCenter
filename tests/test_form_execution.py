import json

import pytest

from app.agent.nodes import build_form_values_node
from app.forms.repository import FormTemplateRepository
from app.forms.schemas import FormTemplate
from app.forms.service import (
    build_api_payload,
    build_form_values,
    validate_submission,
)


def test_builds_workflow_payload_with_fd_template_id():
    repository = FormTemplateRepository()
    template = repository.get("after_sales")
    values = {
        "customer_name": "测试客户",
        "issue_description": "设备需要售后处理",
        "priority": "普通",
    }

    validate_submission(template, values)
    form_values = build_form_values(template, values)
    payload = build_api_payload(
        template=template,
        form_values=form_values,
        operator_id="demo-user-001",
    )

    assert payload["fdTemplateId"] == "template_after_sales_001"
    assert payload["docStatus"] == "20"
    assert json.loads(payload["formValues"]) == values


def test_builds_custom_url_payload_with_doc_operator():
    template = FormTemplate.model_validate(
        {
            "form_code": "custom_url_test",
            "form_name": "采购申请",
            "endpoint_type": "custom_url",
            "endpoint": {
                "url": "http://127.0.0.1:8102/api/forms/submit",
                "submit_mode": "http",
            },
            "fields": [
                {"label": "采购物品", "key": "fd_item_name", "type": "text", "required": True},
                {"label": "数量", "key": "fd_quantity", "type": "number", "required": True},
                {"label": "原因", "key": "fd_reason", "type": "textarea", "required": True},
            ],
        }
    )
    values = {
        "fd_item_name": "包装箱",
        "fd_quantity": 20,
        "fd_reason": "仓库库存不足",
    }

    validate_submission(template, values)
    form_values = build_form_values(template, values)
    payload = build_api_payload(
        template=template,
        form_values=form_values,
        operator_id="demo-user-001",
    )

    assert json.loads(payload["docOperator"]) == {
        "Id": "demo-user-001"
    }
    assert json.loads(payload["formValues"]) == values


def test_rejects_missing_required_field():
    repository = FormTemplateRepository()
    template = repository.get("hr_request")

    with pytest.raises(ValueError, match="开始时间"):
        validate_submission(template, {"request_type": "调休"})


def test_lists_sample_templates():
    repository = FormTemplateRepository()

    assert {"after_sales", "hr_request", "purchase_task_result", "office_supply_task_result"}.issubset(
        set(repository.list_codes())
    )


def test_office_supply_task_result_template_is_available():
    template = FormTemplateRepository().get("office_supply_task_result")

    assert str(template.endpoint.url) == "http://127.0.0.1:8102/api/tasks/complete"
    assert [field.key for field in template.fields] == ["decision", "comment"]


def test_build_form_values_node_keeps_runtime_context_outside_visible_fields():
    template = FormTemplateRepository().get("purchase_task_result")

    result = build_form_values_node(
        {
            "template": template,
            "values": {"decision": "通过", "comment": "数量核对无误"},
            "context_values": {"task_id": "PURCHASE-TASK-0001"},
        }
    )

    assert result["form_values"] == {
        "decision": "通过",
        "comment": "数量核对无误",
        "task_id": "PURCHASE-TASK-0001",
    }
