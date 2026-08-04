from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.command_center.extension_recorder import ExtensionRecorder
from app.command_center.schemas import ExtensionEventBatch
from app.command_center.system_profiles import ProfileLimits, SystemProfile, ToolPermission
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition


FP = "hmac-sha256:" + "a" * 64


def profile() -> SystemProfile:
    return SystemProfile(
        system_code="yifeng_mes",
        display_name="MES",
        allowed_hosts={"yifeng.dtsum.com"},
        openapi_url="https://yifeng.dtsum.com/jeecg-boot/v2/api-docs",
        base_url="https://yifeng.dtsum.com",
        api_path_prefix="/jeecg-boot",
        credential_header="X-Access-Token",
        limits=ProfileLimits(
            request_timeout_seconds=10,
            max_response_bytes=100_000,
            max_requests_per_minute=30,
        ),
        value_capture_policy="fingerprint_by_default",
        sensitive_field_patterns=["(?i)token"],
        tool_permissions=[
            ToolPermission(
                method="GET",
                path="/jeecg-boot/purchase/apply/list",
                side_effect="read",
            )
        ],
    )


def recorder() -> ExtensionRecorder:
    return ExtensionRecorder(
        ToolCatalog(
            [
                ToolDefinition(
                    tool_id="yifeng_mes:listPurchaseApply",
                    system_code="yifeng_mes",
                    operation_id="listPurchaseApply",
                    method="GET",
                    base_url="https://yifeng.dtsum.com",
                    path_template="/jeecg-boot/purchase/apply/list",
                    content_type=None,
                    side_effect="read",
                    credential_header="X-Access-Token",
                )
            ]
        )
    )


def page(origin: str = "https://yifeng.dtsum.com") -> dict[str, object]:
    return {"origin": origin, "path": "/purchase/apply", "fingerprint": FP}


def browser_event(sequence: int = 1, origin: str = "https://yifeng.dtsum.com"):
    return {
        "event_id": str(uuid4()),
        "client_sequence": sequence,
        "occurred_at": datetime.now(UTC),
        "event_type": "click",
        "page": page(origin),
        "control": {"role": "button", "selector_fingerprint": FP},
    }


def network_event(sequence: int = 2, path: str = "/jeecg-boot/purchase/apply/list"):
    now = datetime.now(UTC)
    return {
        "exchange_id": str(uuid4()),
        "client_sequence": sequence,
        "started_at": now,
        "completed_at": now,
        "method": "GET",
        "path_template": path,
        "query_parameter_names": ["pageNo"],
        "request_fingerprint": FP,
        "response_status": 200,
        "response_fingerprint": FP,
    }


def batch(recording_id, *events, batch_id=None) -> ExtensionEventBatch:
    return ExtensionEventBatch.model_validate(
        {
            "batch_id": str(batch_id or uuid4()),
            "recording_id": str(recording_id),
            "events": list(events),
        }
    )


def test_extension_recorder_orders_events_and_matches_allowlisted_api():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询采购申请", {}, profile())

    target.ingest(
        recording_id,
        batch(recording_id, browser_event(), network_event()),
        grant.token,
    )
    trace = target.stop(recording_id, grant.token)

    assert trace.capture_source == "browser_extension"
    assert trace.ui_events[0].sequence < trace.api_exchanges[0].sequence
    assert trace.api_exchanges[0].matched_tool_id.endswith("listPurchaseApply")
    assert grant.token not in trace.model_dump_json()


def test_extension_recorder_rejects_bad_token_and_clears_credentials():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询", {}, profile())
    target.put_credential(
        recording_id, "X-Access-Token", SecretStr("private"), grant.token
    )

    with pytest.raises(PermissionError):
        target.ingest(recording_id, batch(recording_id, browser_event()), "wrong")

    assert target.credential_vault.headers_for(recording_id) == {}


def test_extension_recorder_rejects_duplicate_batch_and_sequence_conflict():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询", {}, profile())
    first = batch(recording_id, browser_event())
    target.ingest(recording_id, first, grant.token)

    with pytest.raises(ValueError, match="already ingested"):
        target.ingest(recording_id, first, grant.token)
    with pytest.raises(ValueError, match="sequence conflicts"):
        target.ingest(recording_id, batch(recording_id, browser_event()), grant.token)


def test_extension_recorder_rejects_wrong_host():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询", {}, profile())

    with pytest.raises(ValueError, match="origin is not allowed"):
        target.ingest(
            recording_id,
            batch(recording_id, browser_event(origin="https://other.example")),
            grant.token,
        )


def test_non_allowlisted_exchange_is_retained_as_not_allowed():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询", {}, profile())
    target.ingest(
        recording_id,
        batch(recording_id, network_event(path="/jeecg-boot/purchase/apply/audit")),
        grant.token,
    )

    trace = target.stop(recording_id, grant.token)

    assert trace.api_exchanges[0].match_status == "not_allowed"
    assert trace.api_exchanges[0].matched_tool_id is None


def test_stop_clears_vault_even_when_trace_finalization_fails():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询", {}, profile())
    target.put_credential(
        recording_id, "X-Access-Token", SecretStr("private"), grant.token
    )
    target.sessions[recording_id].builder.finalize = lambda: (_ for _ in ()).throw(
        RuntimeError("failed")
    )

    with pytest.raises(RuntimeError):
        target.stop(recording_id, grant.token)

    assert target.credential_vault.headers_for(recording_id) == {}
    assert recording_id not in target.sessions


def test_authorized_abort_rejects_bad_token_then_clears_session_and_credentials():
    recording_id = uuid4()
    target = recorder()
    grant = target.start(recording_id, "查询", {}, profile())
    target.put_credential(
        recording_id, "X-Access-Token", SecretStr("private"), grant.token
    )

    with pytest.raises(PermissionError):
        target.abort_authorized(recording_id, "wrong-token")

    assert recording_id in target.sessions

    target.abort_authorized(recording_id, grant.token)

    assert recording_id not in target.sessions
    assert target.credential_vault.headers_for(recording_id) == {}
