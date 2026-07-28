from uuid import uuid4

import httpx

from app.command_center.schemas import ExecutionCommand
from app.command_center.tool_catalog import ToolCatalog
from app.command_center.tool_executor import BindingResolver, ToolExecutor


def test_binding_resolver_reads_task_and_previous_step_output():
    context = {
        "task": {"content": {"item_name": "签字笔"}},
        "steps": {"create_purchase": {"output": {"data": {"id": "WORKFLOW-0001"}}}},
        "literal": {"status": "20"},
    }

    assert BindingResolver.resolve("task.content.item_name", context) == "签字笔"
    assert (
        BindingResolver.resolve(
            "steps.create_purchase.output.data.id",
            context,
        )
        == "WORKFLOW-0001"
    )
    assert BindingResolver.resolve("literal.status", context) == "20"


def test_executor_sends_idempotency_header_and_returns_normalized_output():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["headers"] = dict(request.headers)
        observed["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"status": "processing", "result_values": {"purchase_request_id": "W-1"}},
        )

    catalog = ToolCatalog.from_openapi_documents(
        {
            "onboarding_system": {
                "paths": {
                    "/api/tasks/{task_id}/purchase-link": {
                        "post": {
                            "operationId": "link_purchase",
                            "requestBody": {
                                "content": {"application/json": {"schema": {"type": "object"}}}
                            },
                        }
                    }
                }
            }
        },
        {"onboarding_system": "http://test"},
        {("onboarding_system", "link_purchase")},
    )
    command = ExecutionCommand(
        run_id=uuid4(),
        skill_id=uuid4(),
        skill_version=1,
        step_id="link",
        tool_id="onboarding_system:link_purchase",
        arguments={
            "path": {"task_id": "OFFICE-TASK-0001"},
            "body": {"purchase_request_id": "W-1"},
        },
        idempotency_key="skill:task:link",
        reason="回写采购单号",
    )
    executor = ToolExecutor(
        catalog,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = executor.execute(command)

    assert result.status == "succeeded"
    assert result.normalized_output["result_values"]["purchase_request_id"] == "W-1"
    assert observed["headers"]["idempotency-key"] == "skill:task:link"
    assert observed["url"] == "http://test/api/tasks/OFFICE-TASK-0001/purchase-link"
