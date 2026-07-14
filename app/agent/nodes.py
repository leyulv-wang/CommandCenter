from app.adapters.http_flow import HttpExternalSubmitter
from app.adapters.mock_flow import MockExternalSubmitter
from app.agent.state import FormExecutionState
from app.forms.repository import FormTemplateRepository
from app.forms.service import build_api_payload, build_form_values, validate_submission


def load_form_config(state: FormExecutionState) -> FormExecutionState:
    template = FormTemplateRepository().get(state["form_code"])
    return {"template": template}


def validate_submission_node(state: FormExecutionState) -> FormExecutionState:
    validate_submission(state["template"], state["values"])
    return {}


def build_form_values_node(state: FormExecutionState) -> FormExecutionState:
    form_values = build_form_values(state["template"], state["values"])
    form_values.update(state.get("context_values", {}))
    return {"form_values": form_values}


def build_api_payload_node(state: FormExecutionState) -> FormExecutionState:
    payload = build_api_payload(
        template=state["template"],
        form_values=state["form_values"],
        operator_id=state["operator_id"],
    )
    return {"payload": payload}


def submit_external_api_node(state: FormExecutionState) -> FormExecutionState:
    template = state["template"]
    if template.endpoint.submit_mode == "http":
        result = HttpExternalSubmitter().submit(
            endpoint_type=template.endpoint_type,
            method=template.endpoint.method,
            url=str(template.endpoint.url),
            payload=state["payload"],
            content_type=template.endpoint.content_type,
            timeout_seconds=template.endpoint.timeout_seconds,
        )
    else:
        result = MockExternalSubmitter().submit(
            endpoint_type=template.endpoint_type,
            url=str(template.endpoint.url),
            payload=state["payload"],
        )
    return {"result": result}
