from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


FieldType = Literal["text", "number", "textarea", "select", "datetime", "list"]
EndpointType = Literal["workflow", "custom_url"]
SubmitMode = Literal["mock", "http"]
ContentType = Literal["json", "form"]


class FormField(BaseModel):
    label: str
    key: str
    type: FieldType
    required: bool = False
    item_fields: list["FormField"] = Field(default_factory=list)


class EndpointConfig(BaseModel):
    method: str = "POST"
    url: HttpUrl
    fdTemplateId: str | None = None
    default_docStatus: str = "20"
    operator_param: str = "docOperator"
    values_param: str = "formValues"
    submit_mode: SubmitMode = "mock"
    content_type: ContentType = "form"
    timeout_seconds: int = 30


class FormTemplate(BaseModel):
    form_code: str
    form_name: str
    endpoint_type: EndpointType
    endpoint: EndpointConfig
    fields: list[FormField]


class FormSubmission(BaseModel):
    operator_id: str
    values: dict[str, Any]


class SubmitResult(BaseModel):
    ok: bool
    ticket_id: str
    endpoint_type: EndpointType
    payload: dict[str, Any]
