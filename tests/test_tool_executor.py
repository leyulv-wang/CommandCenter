from uuid import uuid4

import httpx

from app.command_center.schemas import ExecutionCommand
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition
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
                            "x-command-center-idempotency": "header",
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


def test_executor_describes_known_write_without_exposing_idempotency_key():
    catalog = ToolCatalog.from_openapi_documents(
        {
            "business_system": {
                "paths": {
                    "/api/objects": {
                        "post": {
                            "operationId": "create_object",
                            "x-command-center-idempotency": "header",
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
        {"business_system": "http://test"},
        {("business_system", "create_object")},
    )
    command = ExecutionCommand(
        run_id=uuid4(),
        skill_id=uuid4(),
        skill_version=1,
        step_id="create",
        tool_id="business_system:create_object",
        arguments={"body": {"name": "test"}},
        idempotency_key="secret-idempotency-key",
        reason="创建业务对象",
    )
    executor = ToolExecutor(
        catalog,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"success": True, "data": {"id": "OBJECT-1"}},
                )
            )
        ),
    )

    result = executor.execute(command)

    assert result.side_effect == {
        "occurred": True,
        "operation": {
            "tool_id": "business_system:create_object",
            "method": "POST",
            "path": "/api/objects",
        },
        "idempotency": {
            "protected": True,
            "key_fingerprint": (
                "9ab3afd1220a87823137dd9a1803c652c5361facc5f279c6254889a295720341"
            ),
        },
    }
    assert "secret-idempotency-key" not in str(result.side_effect)


def test_executor_sends_query_and_ephemeral_token_without_returning_secret():
    observed = {}

    def handler(request):
        observed["query"] = dict(request.url.params)
        observed["token"] = request.headers.get("X-Access-Token")
        return httpx.Response(200, json={"result": {"records": []}})

    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:listPurchaseApply",
                system_code="mes",
                operation_id="listPurchaseApply",
                method="GET",
                base_url="https://mes.test",
                path_template="/api/apply/list",
                content_type=None,
                side_effect="read",
                credential_header="X-Access-Token",
            )
        ]
    )
    command = ExecutionCommand(
        run_id=uuid4(),
        skill_id=uuid4(),
        skill_version=1,
        step_id="query",
        tool_id="mes:listPurchaseApply",
        arguments={"query": {"applyNo": "CGSQ001"}},
        reason="查询采购申请",
    )
    result = ToolExecutor(
        catalog,
        httpx.Client(transport=httpx.MockTransport(handler)),
        credential_provider=lambda _: {"X-Access-Token": "private-secret"},
    ).execute(command)

    assert observed == {"query": {"applyNo": "CGSQ001"}, "token": "private-secret"}
    assert result.side_effect == {"occurred": False}
    assert result.retry_safe is True
    assert "private-secret" not in result.model_dump_json()


def test_allowlisted_get_declared_write_is_not_implicitly_safe():
    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:audit",
                system_code="mes",
                operation_id="audit",
                method="GET",
                base_url="https://mes.test",
                path_template="/api/audit",
                content_type=None,
                side_effect="write",
            )
        ]
    )
    command = ExecutionCommand(
        run_id=uuid4(),
        skill_id=uuid4(),
        skill_version=1,
        step_id="audit",
        tool_id="mes:audit",
        arguments={},
        reason="审核",
    )
    result = ToolExecutor(
        catalog,
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
        ),
    ).execute(command)

    assert result.side_effect["occurred"] is True
    assert result.retry_safe is False


def test_executor_invalidates_saved_credential_after_unauthorized_response():
    invalidated = []
    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:list",
                system_code="mes",
                operation_id="list",
                method="GET",
                base_url="https://mes.test",
                path_template="/list",
                content_type=None,
                side_effect="read",
                credential_header="X-Access-Token",
            )
        ]
    )

    result = ToolExecutor(
        catalog,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"detail": "expired"})
            )
        ),
        credential_provider=lambda _: {"X-Access-Token": "private-secret"},
        credential_invalidator=invalidated.append,
    ).execute(
        ExecutionCommand(
            run_id=uuid4(),
            skill_id=uuid4(),
            skill_version=1,
            step_id="query",
            tool_id="mes:list",
            arguments={},
            reason="查询",
        )
    )

    assert result.status == "failed"
    assert invalidated == ["mes"]
    assert "private-secret" not in result.model_dump_json()


def test_executor_rejects_a_response_larger_than_the_profile_limit():
    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:list",
                system_code="mes",
                operation_id="list",
                method="GET",
                base_url="https://mes.test",
                path_template="/list",
                content_type=None,
                side_effect="read",
                max_response_bytes=16,
            )
        ]
    )
    result = ToolExecutor(
        catalog,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"records": ["x" * 50]})
            )
        ),
    ).execute(
        ExecutionCommand(
            run_id=uuid4(),
            skill_id=uuid4(),
            skill_version=1,
            step_id="query",
            tool_id="mes:list",
            arguments={},
            reason="查询",
        )
    )

    assert result.status == "failed"
    assert result.error["code"] == "ResponseTooLarge"


def test_executor_omits_optional_nested_nulls_from_json_body():
    import json

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"follow_up_id": "FOLLOW-UP-1"})

    tool = ToolDefinition(
        tool_id="connected:create_follow_up",
        system_code="connected",
        operation_id="create_follow_up",
        method="POST",
        base_url="http://connected",
        path_template="/follow-ups",
        content_type="application/json",
        side_effect="write",
        idempotency_guarantee="header",
        body_schema={
            "type": "object",
            "required": ["title", "items"],
            "properties": {
                "title": {"type": "string"},
                "source_reference": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["material_code", "quantity", "unit"],
                        "properties": {
                            "material_code": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string"},
                            "remark": {"type": "string"},
                        },
                    },
                },
            },
        },
    )
    executor = ToolExecutor(
        ToolCatalog([tool]),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    command = ExecutionCommand(
        run_id=uuid4(),
        skill_id=uuid4(),
        skill_version=1,
        step_id="create",
        tool_id=tool.tool_id,
        arguments={
            "body": {
                "title": "follow-up",
                "source_reference": None,
                "items": [
                    {
                        "material_code": "M-1",
                        "quantity": 2,
                        "unit": "PCS",
                        "remark": None,
                    }
                ],
            }
        },
        idempotency_key="safe-key",
        reason="create follow-up",
    )

    result = executor.execute(command)

    assert result.status == "succeeded"
    assert captured == {
        "title": "follow-up",
        "items": [{"material_code": "M-1", "quantity": 2, "unit": "PCS"}],
    }


def test_executor_does_not_send_or_trust_key_for_undeclared_idempotency():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["idempotency"] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, json={"id": "created-1"})

    tool = ToolDefinition(
        tool_id="finance:create",
        system_code="finance",
        operation_id="create",
        method="POST",
        base_url="http://finance",
        path_template="/records",
        content_type="application/json",
        side_effect="write",
        idempotency_guarantee="none",
    )
    result = ToolExecutor(
        ToolCatalog([tool]),
        httpx.Client(transport=httpx.MockTransport(handler)),
    ).execute(
        ExecutionCommand(
            run_id=uuid4(),
            step_id="create",
            tool_id=tool.tool_id,
            arguments={"body": {}},
            idempotency_key="not-contractually-supported",
            reason="create",
        )
    )

    assert observed["idempotency"] is None
    assert result.retry_safe is False


def test_executor_classifies_business_failure_without_response_body():
    tool = ToolDefinition(
        tool_id="finance:create",
        system_code="finance",
        operation_id="create",
        method="POST",
        base_url="http://finance",
        path_template="/records",
        content_type="application/json",
        side_effect="write",
    )
    result = ToolExecutor(
        ToolCatalog([tool]),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(409, json={"secret": "do-not-persist"})
            )
        ),
    ).execute(
        ExecutionCommand(
            run_id=uuid4(),
            step_id="create",
            tool_id=tool.tool_id,
            arguments={"body": {}},
            reason="create",
        )
    )

    assert result.error["category"] == "business"
    assert result.error["status_code"] == 409
    assert "do-not-persist" not in result.model_dump_json()
