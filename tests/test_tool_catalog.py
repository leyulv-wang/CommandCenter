import pytest

from app.command_center.system_profiles import SystemProfile
from app.command_center.tool_catalog import (
    ToolCatalog,
    ToolDefinition,
    ToolParameter,
    validate_tool_arguments,
)


def profile_for(
    method: str,
    path: str,
    *,
    side_effect: str,
) -> SystemProfile:
    return SystemProfile.model_validate(
        {
            "system_code": "yifeng_mes",
            "display_name": "MES",
            "allowed_hosts": ["mes.example.test"],
            "openapi_url": "http://mes.example.test/v2/api-docs",
            "base_url": "http://mes.example.test",
            "api_path_prefix": "/jeecg-boot/",
            "credential_header": "X-Access-Token",
            "limits": {
                "request_timeout_seconds": 10,
                "max_response_bytes": 1_024,
                "max_requests_per_minute": 30,
            },
            "value_capture_policy": "fingerprint_by_default",
            "sensitive_field_patterns": ["token"],
            "tool_permissions": [
                {"method": method, "path": path, "side_effect": side_effect}
            ],
        }
    )


def parameterized_tool(*, side_effect: str = "read") -> ToolDefinition:
    return ToolDefinition(
        tool_id="yifeng_mes:purchase_orders",
        system_code="yifeng_mes",
        operation_id="purchase_orders",
        method="GET",
        base_url="http://mes.example.test",
        path_template="/jeecg-boot/purchase/orders",
        content_type=None,
        side_effect=side_effect,
        parameters=(
            ToolParameter(
                name="sourceCode",
                location="query",
                type="string",
                required=False,
                description="采购申请来源单号",
            ),
        ),
    )


def test_validate_tool_arguments_rejects_unknown_query_parameter():
    with pytest.raises(ValueError, match="unknown parameter"):
        validate_tool_arguments(
            parameterized_tool(),
            {"query": {"madeUp": "CGSQ01"}},
        )


def test_validate_tool_arguments_rejects_non_read_tool():
    with pytest.raises(ValueError, match="read-only"):
        validate_tool_arguments(
            parameterized_tool(side_effect="write"),
            {"query": {"sourceCode": "CGSQ01"}},
        )


def test_swagger2_query_parameters_enter_allowlisted_tool():
    profile = profile_for(
        "GET", "/jeecg-boot/purchase/apply/list", side_effect="read"
    )
    document = {
        "swagger": "2.0",
        "consumes": ["application/json"],
        "paths": {
            "/jeecg-boot/purchase/apply/list": {
                "get": {
                    "operationId": "listPurchaseApply",
                    "summary": "采购申请-分页列表查询",
                    "parameters": [
                        {
                            "name": "applyNo",
                            "in": "query",
                            "type": "string",
                            "description": "申请单号",
                        },
                        {
                            "name": "X-Tenant-Id",
                            "in": "header",
                            "type": "string",
                            "required": True,
                        },
                    ],
                }
            },
            "/jeecg-boot/purchase/apply/audit": {
                "get": {"operationId": "auditPurchaseApply"}
            },
        },
    }

    catalog = ToolCatalog.from_system_profile(document, profile)
    tool = catalog.get("yifeng_mes:listPurchaseApply")

    assert tool.description == "采购申请-分页列表查询"
    assert tool.side_effect == "read"
    assert tool.query_parameters["applyNo"].type == "string"
    assert tool.content_type is None
    assert {(parameter.name, parameter.location) for parameter in tool.parameters} == {
        ("applyNo", "query"),
        ("X-Tenant-Id", "header"),
    }
    assert tool.credential_header == "X-Access-Token"
    assert tool.max_response_bytes == 1_024
    with pytest.raises(KeyError):
        catalog.get("yifeng_mes:auditPurchaseApply")


def test_catalog_exposes_an_immutable_definition_snapshot():
    catalog = ToolCatalog.from_system_profile(
        {
            "swagger": "2.0",
            "paths": {
                "/jeecg-boot/purchase/apply/list": {
                    "get": {"operationId": "listPurchaseApply"}
                }
            },
        },
        profile_for(
            "GET", "/jeecg-boot/purchase/apply/list", side_effect="read"
        ),
    )

    definitions = catalog.definitions()

    assert isinstance(definitions, tuple)
    assert definitions[0].tool_id == "yifeng_mes:listPurchaseApply"


def test_swagger2_permission_requires_exact_method_and_path():
    profile = profile_for(
        "POST", "/jeecg-boot/purchase/apply/list", side_effect="write"
    )
    document = {
        "swagger": "2.0",
        "paths": {
            "/jeecg-boot/purchase/apply/list": {
                "get": {"operationId": "listPurchaseApply"}
            }
        },
    }

    catalog = ToolCatalog.from_system_profile(document, profile)

    with pytest.raises(KeyError):
        catalog.get("yifeng_mes:listPurchaseApply")


def test_swagger2_body_schema_and_path_parameter_are_preserved():
    path = "/api/orders/{order_id}"
    profile = profile_for("POST", path, side_effect="write")
    document = {
        "swagger": "2.0",
        "consumes": ["application/json"],
        "paths": {
            path: {
                "parameters": [
                    {
                        "name": "order_id",
                        "in": "path",
                        "type": "string",
                        "required": True,
                    }
                ],
                "post": {
                    "operationId": "updateOrder",
                    "description": "Update one order",
                    "parameters": [
                        {
                            "name": "payload",
                            "in": "body",
                            "required": True,
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string"}},
                            },
                        }
                    ],
                },
            }
        },
    }

    tool = ToolCatalog.from_system_profile(document, profile).get(
        "yifeng_mes:updateOrder"
    )

    assert tool.side_effect == "write"
    assert tool.content_type == "application/json"
    assert tool.body_schema == {
        "type": "object",
        "properties": {"status": {"type": "string"}},
    }
    assert {(parameter.name, parameter.location) for parameter in tool.parameters} == {
        ("order_id", "path"),
        ("payload", "body"),
    }


def test_swagger2_path_level_body_parameter_provides_body_schema():
    path = "/api/orders"
    profile = profile_for("POST", path, side_effect="write")
    document = {
        "swagger": "2.0",
        "consumes": ["application/json"],
        "paths": {
            path: {
                "parameters": [
                    {
                        "name": "payload",
                        "in": "body",
                        "required": True,
                        "schema": {
                            "type": "object",
                            "properties": {"quantity": {"type": "integer"}},
                        },
                    }
                ],
                "post": {"operationId": "createOrder"},
            }
        },
    }

    tool = ToolCatalog.from_system_profile(document, profile).get(
        "yifeng_mes:createOrder"
    )

    assert tool.content_type == "application/json"
    assert tool.body_schema == {
        "type": "object",
        "properties": {"quantity": {"type": "integer"}},
    }


def test_swagger2_operation_body_parameter_overrides_path_level_schema():
    path = "/api/orders"
    profile = profile_for("POST", path, side_effect="write")
    document = {
        "swagger": "2.0",
        "consumes": ["application/json"],
        "paths": {
            path: {
                "parameters": [
                    {
                        "name": "payload",
                        "in": "body",
                        "schema": {"type": "object", "required": ["legacy"]},
                    }
                ],
                "post": {
                    "operationId": "createOrder",
                    "parameters": [
                        {
                            "name": "payload",
                            "in": "body",
                            "schema": {"type": "object", "required": ["current"]},
                        }
                    ],
                },
            }
        },
    }

    tool = ToolCatalog.from_system_profile(document, profile).get(
        "yifeng_mes:createOrder"
    )

    assert tool.body_schema == {"type": "object", "required": ["current"]}


def test_catalog_matches_only_explicitly_allowlisted_operations():
    document = {
        "paths": {
            "/api/workflows/start": {
                "post": {
                    "operationId": "start_workflow_api_workflows_start_post",
                    "requestBody": {
                        "content": {
                            "application/x-www-form-urlencoded": {"schema": {"type": "object"}}
                        }
                    },
                }
            },
            "/api/demo/reset": {
                "post": {"operationId": "reset_demo_api_demo_reset_post"}
            },
        }
    }
    catalog = ToolCatalog.from_openapi_documents(
        {"connected_system": document},
        {"connected_system": "http://127.0.0.1:8101"},
        {("connected_system", "start_workflow_api_workflows_start_post")},
    )

    matched = catalog.match_exchange(
        "connected_system",
        "POST",
        "/api/workflows/start",
    )

    assert matched is not None
    assert matched.tool_id == "connected_system:start_workflow_api_workflows_start_post"
    assert catalog.match_exchange("connected_system", "POST", "/api/demo/reset") is None


def test_catalog_matches_templated_task_path():
    document = {
        "paths": {
            "/api/tasks/{task_id}/purchase-link": {
                "post": {
                    "operationId": "link_purchase_request_api_tasks__task_id__purchase_link_post"
                }
            }
        }
    }
    catalog = ToolCatalog.from_openapi_documents(
        {"onboarding_system": document},
        {"onboarding_system": "http://127.0.0.1:8102"},
        {
            (
                "onboarding_system",
                "link_purchase_request_api_tasks__task_id__purchase_link_post",
            )
        },
    )

    matched = catalog.match_exchange(
        "onboarding_system",
        "POST",
        "/api/tasks/OFFICE-TASK-0001/purchase-link",
    )

    assert matched is not None
    assert matched.path_parameters == {"task_id": "OFFICE-TASK-0001"}


def test_purchase_tracking_catalog_preserves_cross_object_query_parameters():
    paths = {
        "/jeecg-boot/jiafang.purchase.order/order/list": (
            "queryPageListUsingGET_124",
            ["sourceCode", "pageNo", "pageSize"],
        ),
        "/jeecg-boot/jiafang.purchase.order/order/listOrderDetailByMainId": (
            "listOrderDetailByMainIdUsingGET",
            ["mainCode", "pageNo", "pageSize"],
        ),
        "/jeecg-boot/jiafang.purchase.order/order/receivingRecords": (
            "receivingRecordsUsingGET_1",
            ["orderNumber", "pageNo", "pageSize"],
        ),
        "/jeecg-boot/jiafang.purchase.warehouse/purchaseWarehouse/list": (
            "queryPageListUsingGET_185",
            ["purchaseOrder", "sourceCode", "pageNo", "pageSize"],
        ),
        "/jeecg-boot/jiafang.purchase.warehouse/purchaseWarehouse/listPurchaseWarehouseDetailByMainId": (
            "listPurchaseWarehouseDetailByMainIdUsingGET",
            ["mainCode", "pageNo", "pageSize"],
        ),
    }
    profile = SystemProfile.model_validate(
        {
            **profile_for("GET", next(iter(paths)), side_effect="read").model_dump(),
            "tool_permissions": [
                {"method": "GET", "path": path, "side_effect": "read"}
                for path in paths
            ],
        }
    )
    document = {
        "swagger": "2.0",
        "paths": {
            path: {
                "get": {
                    "operationId": operation_id,
                    "summary": operation_id,
                    "parameters": [
                        {
                            "name": name,
                            "in": "query",
                            "type": "integer" if name in {"pageNo", "pageSize"} else "string",
                            "required": False,
                        }
                        for name in parameter_names
                    ],
                }
            }
            for path, (operation_id, parameter_names) in paths.items()
        },
    }

    catalog = ToolCatalog.from_system_profile(document, profile)

    for operation_id, parameter_names in paths.values():
        tool = catalog.get(f"yifeng_mes:{operation_id}")
        assert set(tool.query_parameters) == set(parameter_names)
        assert tool.side_effect == "read"
