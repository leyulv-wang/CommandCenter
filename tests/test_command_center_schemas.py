from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

import app.command_center.schemas as schemas
from app.command_center.schemas import (
    DemonstrationAnalysis,
    InputBinding,
    OperationTrace,
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


def existing_trace_payload() -> dict[str, object]:
    return {
        "trace_id": str(uuid4()),
        "recording_id": str(uuid4()),
        "objective": "observe a configured workflow",
        "source_task": {"object_id": "TASK-1"},
        "started_at": datetime.now(UTC).isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
    }


def valid_extension_batch() -> dict[str, object]:
    return {
        "recording_id": str(uuid4()),
        "events": [
            {
                "event_id": str(uuid4()),
                "client_sequence": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "event_type": "click",
                "page": {
                    "origin": "https://example.test",
                    "path": "/orders",
                    "title": "Orders",
                    "fingerprint": "hmac-sha256:" + "a" * 64,
                },
                "control": {
                    "role": "button",
                    "label": "Search",
                    "selector_fingerprint": "hmac-sha256:" + "b" * 64,
                },
            }
        ],
    }


def valid_page_mutation(client_sequence: int) -> dict[str, object]:
    return {
        "mutation_id": str(uuid4()),
        "client_sequence": client_sequence,
        "occurred_at": datetime.now(UTC).isoformat(),
        "page": {
            "origin": "https://example.test",
            "path": "/orders",
            "fingerprint": "hmac-sha256:" + "c" * 64,
        },
        "mutation_type": "dom_change",
        "changed_control_fingerprints": ["hmac-sha256:" + "d" * 64],
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


def test_old_operation_trace_remains_valid():
    trace = OperationTrace.model_validate(existing_trace_payload())

    assert trace.capture_source == "playwright"
    assert trace.page_mutations == []
    assert trace.redaction_summary.redacted_field_count == 0


def test_extension_batch_requires_one_recording_and_monotonic_client_sequence():
    payload = valid_extension_batch()
    payload["events"].append({**payload["events"][0], "event_id": str(uuid4())})

    with pytest.raises(ValidationError):
        schemas.ExtensionEventBatch.model_validate(payload)


def test_extension_batch_allows_interleaved_event_and_mutation_sequences():
    payload = valid_extension_batch()
    second_event = {**payload["events"][0], "event_id": str(uuid4()), "client_sequence": 3}
    payload["events"].append(second_event)
    payload["page_mutations"] = [valid_page_mutation(2)]

    batch = schemas.ExtensionEventBatch.model_validate(payload)

    assert [event.client_sequence for event in batch.events] == [1, 3]
    assert [mutation.client_sequence for mutation in batch.page_mutations] == [2]


def test_extension_batch_rejects_sequence_reused_across_evidence_types():
    payload = valid_extension_batch()
    payload["page_mutations"] = [valid_page_mutation(1)]

    with pytest.raises(ValidationError):
        schemas.ExtensionEventBatch.model_validate(payload)


def test_extension_batch_preserves_only_redacted_semantic_evidence():
    batch = schemas.ExtensionEventBatch.model_validate(valid_extension_batch())

    assert batch.events[0].page.query_parameter_names == []
    assert batch.events[0].value_fingerprint is None


def test_extension_evidence_rejects_sensitive_raw_values():
    payload = valid_extension_batch()
    payload["events"][0]["network"] = {
        "request": {"authorization": "Bearer raw-secret"}
    }

    with pytest.raises(ValidationError):
        schemas.ExtensionEventBatch.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin", "https://user:password@example.test"),
        ("origin", "https://example.test?session=private"),
        ("origin", "https://example.test\nprivate"),
        ("path", "/orders?token=private"),
        ("path", "/orders\nprivate"),
        ("fingerprint", "sha256:page"),
    ],
)
def test_extension_page_evidence_rejects_unbounded_url_and_fingerprint_values(
    field, value
):
    payload = valid_extension_batch()
    payload["events"][0]["page"][field] = value

    with pytest.raises(ValidationError):
        schemas.ExtensionEventBatch.model_validate(payload)


@pytest.mark.parametrize(
    "secret_label",
    [
        "Authorization: Bearer private",
        "Cookie=session=private",
        "X-Access-Token: private",
        "API key: private",
        "password: private",
        "captcha=private",
        "local-storage: private",
        "file-content: private",
    ],
)
def test_extension_control_text_rejects_sensitive_value_carriers(secret_label):
    payload = valid_extension_batch()
    payload["events"][0]["control"]["label"] = secret_label

    with pytest.raises(ValidationError):
        schemas.ExtensionEventBatch.model_validate(payload)


def test_extension_redaction_summary_has_fixed_non_sensitive_fields():
    payload = valid_extension_batch()
    payload["redaction_summary"] = {"authorization": 1}

    with pytest.raises(ValidationError):
        schemas.ExtensionEventBatch.model_validate(payload)


@pytest.mark.parametrize(
    "credential_like_value",
    [
        "Bearer private-secret-value",
        "Basic dXNlcjpwYXNzd29yZC1wcml2YXRl",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlLXVzZXIifQ.signaturevalue",
        "sk-1234567890abcdefghijklmnop",
        "ya29.a0AfH6SMCprivateGoogleToken",
        "ghp_1234567890abcdefghijklmnopqrstuv",
    ],
)
def test_evidence_identifiers_reject_common_credential_value_forms(
    credential_like_value,
):
    with pytest.raises(ValidationError):
        TypeAdapter(schemas.EvidenceIdentifier).validate_python(credential_like_value)


@pytest.mark.parametrize("identifier", ["access_token", "sk-stage", "github_token"])
def test_evidence_identifiers_allow_ordinary_parameter_names(identifier):
    assert TypeAdapter(schemas.EvidenceIdentifier).validate_python(identifier) == identifier


def test_skill_step_accepts_query_binding():
    payload = valid_skill_payload()
    payload["steps"][0]["input_bindings"] = {
        "query.apply_no": "literal.apply_no"
    }

    skill = SkillDefinition.model_validate(payload)

    assert skill.steps[0].input_bindings == {
        "query.apply_no": "literal.apply_no"
    }


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
