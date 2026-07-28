from app.command_center.tool_catalog import ToolCatalog


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
