from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.command_center.schemas import ExtensionEventBatch


FP = "hmac-sha256:" + "a" * 64


def browser_bc_adapter_payload() -> dict[str, object]:
    recording_id = uuid4()
    return {
        "batch_id": str(uuid4()),
        "recording_id": str(recording_id),
        "events": [
            {
                "event_id": str(uuid4()),
                "client_sequence": 1,
                "occurred_at": "2026-08-07T01:00:00.000Z",
                "event_type": "click",
                "page": {
                    "origin": "http://yifeng.dtsum.com",
                    "path": "/purchase/apply",
                    "query_parameter_names": ["pageNo"],
                    "fingerprint": FP,
                },
                "control": {
                    "role": "button",
                    "accessible_name": "查询",
                    "selector_fingerprint": FP,
                },
            },
            {
                "exchange_id": str(uuid4()),
                "client_sequence": 2,
                "started_at": "2026-08-07T01:00:00.010Z",
                "completed_at": "2026-08-07T01:00:00.030Z",
                "method": "GET",
                "path_template": "/jeecg-boot/purchase/apply/list",
                "query_parameter_names": ["pageNo"],
                "query_parameter_fingerprints": {"pageNo": [FP]},
                "request_fingerprint": FP,
                "response_status": 200,
                "endpoint_fingerprint": FP,
            },
        ],
        "page_mutations": [],
        "redaction_summary": {
            "redacted_field_count": 2,
            "fingerprinted_value_count": 4,
            "dropped_evidence_count": 0,
        },
    }


def test_browser_bc_adapter_payload_matches_extension_contract():
    payload = browser_bc_adapter_payload()

    batch = ExtensionEventBatch.model_validate(payload)

    assert str(batch.recording_id) == payload["recording_id"]
    assert batch.events[0].client_sequence < batch.events[1].client_sequence
    assert batch.events[1].path_template == "/jeecg-boot/purchase/apply/list"
    assert batch.events[1].query_parameter_fingerprints == {"pageNo": [FP]}


def test_browser_bc_adapter_contract_rejects_raw_token_fields():
    payload = browser_bc_adapter_payload()
    payload["events"][1]["authorization"] = "private-token"

    with pytest.raises(ValidationError):
        ExtensionEventBatch.model_validate(payload)


def test_browser_bc_adapter_contract_rejects_non_monotonic_sequences():
    payload = deepcopy(browser_bc_adapter_payload())
    payload["events"][0]["client_sequence"] = 2
    payload["events"][1]["client_sequence"] = 1

    with pytest.raises(ValidationError, match="monotonic"):
        ExtensionEventBatch.model_validate(payload)
