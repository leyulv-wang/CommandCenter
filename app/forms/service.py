import json
from typing import Any

from app.forms.schemas import FormField, FormTemplate


def validate_submission(template: FormTemplate, values: dict[str, Any]) -> None:
    for field in template.fields:
        _validate_field(field, values.get(field.key), values)


def build_form_values(template: FormTemplate, values: dict[str, Any]) -> dict[str, Any]:
    validate_submission(template, values)
    return {field.key: values[field.key] for field in template.fields if field.key in values}


def build_api_payload(
    template: FormTemplate, form_values: dict[str, Any], operator_id: str
) -> dict[str, Any]:
    form_values_json = json.dumps(form_values, ensure_ascii=False, separators=(",", ":"))

    if template.endpoint_type == "workflow":
        return {
            "docSubject": _build_doc_subject(template, form_values),
            "fdTemplateId": template.endpoint.fdTemplateId,
            "formValues": form_values_json,
            "docCreator": operator_id,
            "docStatus": template.endpoint.default_docStatus,
        }

    if template.endpoint_type == "custom_url":
        return {
            template.endpoint.operator_param: json.dumps(
                {"Id": operator_id}, ensure_ascii=False, separators=(",", ":")
            ),
            template.endpoint.values_param: form_values_json,
        }

    raise ValueError(f"Unsupported endpoint type: {template.endpoint_type}")


def _validate_field(field: FormField, value: Any, all_values: dict[str, Any]) -> None:
    if field.required and _is_empty(value):
        raise ValueError(f"缺少必填字段：{field.label}")

    if _is_empty(value):
        return

    if field.type == "number" and not isinstance(value, int | float):
        raise ValueError(f"字段类型错误：{field.label} 需要数字")

    if field.type == "list":
        if not isinstance(value, list):
            raise ValueError(f"字段类型错误：{field.label} 需要明细列表")
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"字段类型错误：{field.label} 第 {index + 1} 行需要对象")
            for item_field in field.item_fields:
                _validate_field(item_field, item.get(item_field.key), item)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _build_doc_subject(template: FormTemplate, form_values: dict[str, Any]) -> str:
    first_value = next((value for value in form_values.values() if not isinstance(value, list)), "")
    return f"{template.form_name}：{first_value}" if first_value else template.form_name
