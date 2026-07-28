from datetime import UTC, datetime
from uuid import uuid4

from app.command_center.recorder import OperationTraceBuilder
from app.command_center.tool_catalog import ToolCatalog


def test_trace_builder_orders_ui_and_matches_allowlisted_api():
    catalog = ToolCatalog.from_openapi_documents(
        {
            "onboarding_system": {
                "paths": {
                    "/api/tasks/{task_id}/purchase-link": {
                        "post": {"operationId": "link_purchase"}
                    }
                }
            }
        },
        {"onboarding_system": "http://127.0.0.1:8102"},
        {("onboarding_system", "link_purchase")},
    )
    builder = OperationTraceBuilder(
        recording_id=uuid4(),
        objective="创建采购并回写",
        source_task={"system_code": "onboarding_system", "object_id": "OFFICE-1"},
        catalog=catalog,
        started_at=datetime.now(UTC),
    )

    builder.add_ui_event(
        page_url="http://127.0.0.1:8102",
        action_type="click",
        target={"tag": "button", "accessible_name": "回写采购单号"},
    )
    builder.add_api_exchange(
        system_code="onboarding_system",
        method="POST",
        path="/api/tasks/OFFICE-1/purchase-link",
        request_body={"purchase_request_id": "WORKFLOW-1"},
        response_status=200,
        response_body={"status": "processing"},
    )
    trace = builder.finalize()

    assert trace.ui_events[0].sequence == 1
    assert trace.api_exchanges[0].sequence == 2
    assert trace.api_exchanges[0].match_status == "matched"
    assert trace.api_exchanges[0].matched_tool_id == "onboarding_system:link_purchase"


def test_unknown_api_is_kept_as_non_allowlisted_evidence():
    catalog = ToolCatalog([])
    builder = OperationTraceBuilder(
        recording_id=uuid4(),
        objective="演示",
        source_task={},
        catalog=catalog,
        started_at=datetime.now(UTC),
    )

    builder.add_api_exchange(
        system_code="onboarding_system",
        method="POST",
        path="/api/demo/reset",
        request_body={},
        response_status=200,
        response_body={},
    )

    assert builder.finalize().api_exchanges[0].match_status == "not_allowed"
