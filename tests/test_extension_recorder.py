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


def local_profile() -> SystemProfile:
    return SystemProfile(
        system_code="connected_system",
        display_name="本地采购系统",
        allowed_hosts={"127.0.0.1"},
        openapi_url="http://127.0.0.1:8101/openapi.json",
        base_url="http://127.0.0.1:8101",
        api_path_prefix="/api",
        credential_header=None,
        limits=ProfileLimits(
            request_timeout_seconds=10,
            max_response_bytes=100_000,
            max_requests_per_minute=30,
        ),
        value_capture_policy="fingerprint_by_default",
        sensitive_field_patterns=["(?i)token"],
        tool_permissions=[
            ToolPermission(
                method="POST",
                path="/api/purchase-follow-ups",
                side_effect="write",
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


def multi_recorder() -> ExtensionRecorder:
    catalogs = {
        "yifeng_mes": ToolCatalog(
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
        ),
        "connected_system": ToolCatalog(
            [
                ToolDefinition(
                    tool_id="connected_system:createPurchaseFollowUp",
                    system_code="connected_system",
                    operation_id="createPurchaseFollowUp",
                    method="POST",
                    base_url="http://127.0.0.1:8101",
                    path_template="/api/purchase-follow-ups",
                    content_type="application/json",
                    side_effect="write",
                )
            ]
        ),
    }
    return ExtensionRecorder(catalog_provider=lambda item: catalogs[item.system_code])


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
        "query_parameter_fingerprints": {"pageNo": [FP]},
        "request_fingerprint": FP,
        "response_status": 200,
        "response_fingerprint": FP,
    }


def identified(event: dict, system_code: str, tab_id: int) -> dict:
    return {**event, "system_code": system_code, "tab_id": tab_id}


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
    assert trace.api_exchanges[0].request_body["query_parameter_fingerprints"] == {
        "pageNo": [FP]
    }
    assert grant.token not in trace.model_dump_json()


def test_multi_system_recorder_routes_events_into_one_ordered_trace():
    recording_id = uuid4()
    target = multi_recorder()
    grant = target.start(
        recording_id,
        "查询 MES 采购申请并创建本地后续处理单",
        {},
        [profile(), local_profile()],
    )
    local_network = identified(
        network_event(4, "/api/purchase-follow-ups"),
        "connected_system",
        22,
    )
    local_network["method"] = "POST"
    local_network["body_field_fingerprints"] = {
        "/assignee": [FP],
        "/items/0/material_code": [FP],
    }

    target.ingest(
        recording_id,
        batch(
            recording_id,
            identified(browser_event(1), "yifeng_mes", 11),
            identified(network_event(2), "yifeng_mes", 11),
            identified(
                browser_event(3, "http://127.0.0.1:8101"),
                "connected_system",
                22,
            ),
            local_network,
        ),
        grant.token,
    )
    trace = target.stop(recording_id, grant.token)

    assert [exchange.system_code for exchange in trace.api_exchanges] == [
        "yifeng_mes",
        "connected_system",
    ]
    assert [exchange.matched_tool_id for exchange in trace.api_exchanges] == [
        "yifeng_mes:listPurchaseApply",
        "connected_system:createPurchaseFollowUp",
    ]
    assert trace.ui_events[0].target["system_code"] == "yifeng_mes"
    assert trace.ui_events[1].target["tab_id"] == 22
    assert trace.api_exchanges[1].request_body["body_field_fingerprints"] == {
        "/assignee": [FP],
        "/items/0/material_code": [FP],
    }


def test_multi_system_recorder_rejects_mismatched_identity_and_origin():
    recording_id = uuid4()
    target = multi_recorder()
    grant = target.start(recording_id, "联合操作", {}, [profile(), local_profile()])

    with pytest.raises(ValueError, match="origin is not allowed"):
        target.ingest(
            recording_id,
            batch(
                recording_id,
                identified(browser_event(), "connected_system", 11),
            ),
            grant.token,
        )


def test_multi_system_recorder_requires_identity_for_network_evidence():
    recording_id = uuid4()
    target = multi_recorder()
    grant = target.start(recording_id, "联合操作", {}, [profile(), local_profile()])

    with pytest.raises(ValueError, match="system identity"):
        target.ingest(
            recording_id,
            batch(recording_id, network_event()),
            grant.token,
        )


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
