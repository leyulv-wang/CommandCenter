from typing import Any, TypedDict

from app.forms.schemas import FormTemplate


class FormExecutionState(TypedDict, total=False):
    form_code: str
    operator_id: str
    values: dict[str, Any]
    context_values: dict[str, Any]
    template: FormTemplate
    form_values: dict[str, Any]
    payload: dict[str, Any]
    result: dict[str, Any]
