import httpx
from fastapi.testclient import TestClient

import app.main as main_module
from app.external_systems import ExternalSystemClient, ExternalSystemRegistry
from app.forms.repository import FormTemplateRepository
from app.main import app


client = TestClient(app)


def test_registry_persists_automatic_onboarding_and_reset(tmp_path):
    state_path = tmp_path / "external_systems.json"
    registry = ExternalSystemRegistry(state_path=state_path)

    assert registry.get("onboarding_system")["role"] == "onboarding"

    connected = registry.connect_form_by_endpoint(
        "http://127.0.0.1:8102/api/forms/submit",
        "office_supply_request",
    )

    assert connected["system_code"] == "onboarding_system"
    assert connected["role"] == "connected"
    assert connected["form_codes"] == ["office_supply_request"]

    reloaded = ExternalSystemRegistry(state_path=state_path)
    assert reloaded.get("onboarding_system")["role"] == "connected"
    assert reloaded.get("onboarding_system")["form_codes"] == ["office_supply_request"]

    reloaded.reset_onboarding("onboarding_system")
    reset = ExternalSystemRegistry(state_path=state_path).get("onboarding_system")
    assert reset["role"] == "onboarding"
    assert reset["form_codes"] == []


def test_default_registry_starts_both_demo_systems_as_onboarding(tmp_path):
    registry = ExternalSystemRegistry(state_path=tmp_path / "external_systems.json")

    assert {system["system_code"]: system["role"] for system in registry.list()} == {
        "connected_system": "onboarding",
        "onboarding_system": "onboarding",
    }


def test_lists_external_systems():
    response = client.get("/external-systems")

    assert response.status_code == 200
    codes = [item["system_code"] for item in response.json()]
    assert "connected_system" in codes
    assert "onboarding_system" in codes


def test_reads_external_system_submissions_through_central_api(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://demo.local/api/submissions"
        return httpx.Response(
            200,
            json={
                "system_name": "演示系统",
                "items": [
                    {
                        "id": 1,
                        "ticket_id": "DEMO-0001",
                        "operator_id": "u001",
                        "form_values": {"name": "测试"},
                        "source": "seed",
                        "created_at": "2026-07-01T10:00:00",
                    }
                ],
            },
        )

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "演示系统",
                "base_url": "http://demo.local",
                "role": "connected",
            }
        ]
    )
    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "external_system_client", external_client)

    response = client.get("/external-systems/demo_system/submissions")

    assert response.status_code == 200
    assert response.json()["items"][0]["ticket_id"] == "DEMO-0001"


def test_unknown_external_system_returns_404():
    response = client.get("/external-systems/not_exists/submissions")

    assert response.status_code == 404


def test_reads_all_tasks_and_submissions_for_connected_system(monkeypatch):
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/api/tasks":
            status = request.url.params["status"]
            return httpx.Response(
                200,
                json={
                    "system_name": "演示采购系统",
                    "items": [
                        {
                            "task_id": f"TASK-{status}",
                            "title": "采购审核",
                            "status": status,
                            "assignee_id": "u002",
                            "content": {"item_name": "显示器"},
                            "created_at": "2026-07-14T10:00:00",
                        }
                    ],
                },
            )
        assert request.url.path == "/api/submissions"
        return httpx.Response(
            200,
            json={
                "system_name": "演示采购系统",
                "items": [
                    {
                        "id": 1,
                        "ticket_id": "ORDER-001",
                        "operator_id": "u003",
                        "form_values": {"item_name": "打印纸"},
                        "source": "submitted",
                        "endpoint_type": "workflow",
                        "fd_template_id": "purchase_request_001",
                        "created_at": "2026-07-14T11:00:00",
                    }
                ],
            },
        )

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "演示采购系统",
                "base_url": "http://demo.local",
                "role": "connected",
                "form_codes": ["purchase_request"],
            }
        ]
    )
    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "external_system_client", external_client)

    response = client.get("/external-systems/demo_system/data")

    assert response.status_code == 200
    assert requested_urls == [
        "http://demo.local/api/tasks?status=pending",
        "http://demo.local/api/tasks?status=completed",
        "http://demo.local/api/submissions",
    ]
    body = response.json()
    assert body["system"]["system_code"] == "demo_system"
    assert [item["status"] for item in body["tasks"]] == ["pending", "completed"]
    assert body["tasks"][0]["source_system_name"] == "演示采购系统"
    assert body["submissions"][0]["ticket_id"] == "ORDER-001"


def test_rejects_all_data_read_for_onboarding_system(monkeypatch):
    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "待接入系统",
                "base_url": "http://demo.local",
                "role": "onboarding",
                "form_codes": [],
            }
        ]
    )
    monkeypatch.setattr(
        main_module,
        "external_system_client",
        ExternalSystemClient(registry=registry),
    )

    response = client.get("/external-systems/demo_system/data")

    assert response.status_code == 404


def test_aggregates_pending_tasks_from_connected_systems(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://demo.local/api/tasks?operator_id=u001"
        return httpx.Response(
            200,
            json={
                "system_name": "演示采购系统",
                "items": [
                    {
                        "task_id": "TASK-001",
                        "title": "核对采购数量",
                        "task_type": "purchase_review",
                        "form_code": "purchase_task_result",
                        "content": {"item_name": "打印纸", "quantity": 10},
                        "status": "pending",
                        "assignee_id": "u001",
                        "created_at": "2026-07-10T09:30:00",
                    }
                ],
            },
        )

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "演示采购系统",
                "base_url": "http://demo.local",
                "role": "connected",
            },
            {
                "system_code": "onboarding_system",
                "system_name": "待接入系统",
                "base_url": "http://onboarding.local",
                "role": "onboarding",
            },
        ]
    )
    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "external_system_client", external_client)

    response = client.get("/tasks", params={"operator_id": "u001"})

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    task = response.json()["items"][0]
    assert task["source_system_code"] == "demo_system"
    assert task["source_system_name"] == "演示采购系统"


def test_aggregates_completed_tasks_with_results(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url != "http://demo.local/api/tasks?operator_id=u001&status=completed":
            return httpx.Response(400, json={"detail": "missing completed status"})
        return httpx.Response(
            200,
            json={
                "system_name": "演示采购系统",
                "items": [
                    {
                        "task_id": "TASK-001",
                        "title": "核对采购数量",
                        "task_type": "purchase_review",
                        "form_code": "purchase_task_result",
                        "content": {"item_name": "打印纸", "quantity": 10},
                        "status": "completed",
                        "assignee_id": "u001",
                        "result_values": {"decision": "通过", "comment": "数量无误"},
                        "created_at": "2026-07-10T09:30:00",
                        "completed_at": "2026-07-13T10:00:00",
                    }
                ],
            },
        )

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "演示采购系统",
                "base_url": "http://demo.local",
                "role": "connected",
                "form_codes": ["after_sales"],
            }
        ]
    )
    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "external_system_client", external_client)

    response = client.get(
        "/tasks",
        params={"operator_id": "u001", "status": "completed"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "completed"
    assert response.json()["items"][0]["result_values"]["decision"] == "通过"


def test_lists_startable_forms_for_connected_system(monkeypatch):
    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "演示采购系统",
                "base_url": "http://demo.local",
                "role": "connected",
                "form_codes": ["after_sales"],
            }
        ]
    )
    monkeypatch.setattr(
        main_module,
        "external_system_client",
        ExternalSystemClient(registry=registry),
    )

    response = client.get("/external-systems/demo_system/forms")

    assert response.status_code == 200
    assert [form["form_code"] for form in response.json()] == ["after_sales"]


def test_completes_task_through_its_configured_form(monkeypatch):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://demo.local/api/tasks?operator_id=u001"
        return httpx.Response(
            200,
            json={
                "system_name": "演示采购系统",
                "items": [
                    {
                        "task_id": "TASK-001",
                        "title": "核对采购数量",
                        "task_type": "purchase_review",
                        "form_code": "purchase_task_result",
                        "content": {"item_name": "打印纸", "quantity": 10},
                        "status": "pending",
                        "assignee_id": "u001",
                        "created_at": "2026-07-10T09:30:00",
                    }
                ],
            },
        )

    class FakeGraph:
        def invoke(self, state):
            captured.update(state)
            return {
                "result": {
                    "ok": True,
                    "task_id": state["context_values"]["task_id"],
                }
            }

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "demo_system",
                "system_name": "演示采购系统",
                "base_url": "http://demo.local",
                "role": "connected",
            }
        ]
    )
    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "external_system_client", external_client)
    monkeypatch.setattr(main_module, "form_execution_graph", FakeGraph())

    response = client.post(
        "/tasks/demo_system/TASK-001/complete",
        json={"operator_id": "u001", "values": {"decision": "approved", "comment": "通过"}},
    )

    assert response.status_code == 200
    assert captured["form_code"] == "purchase_task_result"
    assert captured["operator_id"] == "u001"
    assert captured["values"] == {"decision": "approved", "comment": "通过"}
    assert captured["context_values"] == {"task_id": "TASK-001"}


def test_task_completion_reports_external_submission_failure(monkeypatch):
    class TaskClient:
        def get_task(self, system_code, task_id, operator_id):
            return {"form_code": "purchase_task_result"}

    class FailingGraph:
        def invoke(self, state):
            return {"result": {"ok": False, "error": "外部系统拒绝处理结果"}}

    monkeypatch.setattr(main_module, "external_system_client", TaskClient())
    monkeypatch.setattr(main_module, "form_execution_graph", FailingGraph())

    response = client.post(
        "/tasks/demo_system/TASK-001/complete",
        json={"operator_id": "u001", "values": {"decision": "approved", "comment": "通过"}},
    )

    assert response.status_code == 502
    assert "外部系统拒绝处理结果" in response.json()["detail"]


def test_reset_onboarding_demo_deletes_matching_form_configs_and_resets_external_system(
    tmp_path,
    monkeypatch,
):
    repository = FormTemplateRepository(templates_dir=tmp_path)
    repository.save(
        main_module.FormTemplate.model_validate(
            {
                "form_code": "office_supply_request",
                "form_name": "办公用品申请",
                "endpoint_type": "custom_url",
                "endpoint": {
                    "url": "http://demo.local/api/forms/submit",
                    "submit_mode": "http",
                },
                "fields": [
                    {
                        "label": "申请物品",
                        "key": "itemName",
                        "type": "text",
                        "required": True,
                    }
                ],
            }
        )
    )
    repository.save(
        main_module.FormTemplate.model_validate(
            {
                "form_code": "office_supply_task_result",
                "form_name": "办公用品任务处理",
                "endpoint_type": "custom_url",
                "endpoint": {
                    "url": "http://demo.local/api/tasks/complete",
                    "submit_mode": "http",
                },
                "fields": [
                    {
                        "label": "处理结论",
                        "key": "decision",
                        "type": "text",
                        "required": True,
                    }
                ],
            }
        )
    )

    called = {"reset": False}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://demo.local/api/demo/reset"
        called["reset"] = True
        return httpx.Response(200, json={"deleted_records": 2, "remaining_records": 0})

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "onboarding_system",
                "system_name": "待接入办公用品系统",
                "base_url": "http://demo.local",
                "role": "connected",
                "form_codes": ["office_supply_request"],
            }
        ]
    )
    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "FormTemplateRepository", lambda: repository)
    monkeypatch.setattr(main_module, "external_system_client", external_client)

    response = client.post("/demo/reset-onboarding")

    assert response.status_code == 200
    assert called["reset"] is True
    assert response.json()["deleted_form_codes"] == ["office_supply_request"]
    assert response.json()["external_result"]["deleted_records"] == 2
    assert repository.list_codes() == ["office_supply_task_result"]
    assert registry.get("onboarding_system")["role"] == "onboarding"
    assert registry.get("onboarding_system")["form_codes"] == []


def test_resets_purchase_demo_without_changing_office_system(tmp_path, monkeypatch):
    repository = FormTemplateRepository(templates_dir=tmp_path / "forms")
    for form_code, url in (
        ("purchase_ai_form", "http://purchase.local/api/workflows/start"),
        ("purchase_task_result", "http://purchase.local/api/tasks/complete"),
        ("office_ai_form", "http://office.local/api/forms/submit"),
    ):
        repository.save(
            main_module.FormTemplate.model_validate(
                {
                    "form_code": form_code,
                    "form_name": form_code,
                    "endpoint_type": "custom_url",
                    "endpoint": {"url": url, "submit_mode": "http"},
                    "fields": [{"label": "内容", "key": "value", "type": "text"}],
                }
            )
        )

    registry = ExternalSystemRegistry(
        systems=[
            {
                "system_code": "connected_system",
                "system_name": "采购业务系统",
                "base_url": "http://purchase.local",
                "role": "connected",
                "form_codes": ["purchase_ai_form"],
            },
            {
                "system_code": "onboarding_system",
                "system_name": "办公用品系统",
                "base_url": "http://office.local",
                "role": "connected",
                "form_codes": ["office_ai_form"],
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://purchase.local/api/demo/reset"
        return httpx.Response(200, json={"deleted_records": 1, "remaining_records": 0})

    external_client = ExternalSystemClient(
        registry=registry,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main_module, "FormTemplateRepository", lambda: repository)
    monkeypatch.setattr(main_module, "external_system_client", external_client)

    response = client.post("/demo/reset/connected_system")

    assert response.status_code == 200
    assert response.json()["deleted_form_codes"] == ["purchase_ai_form"]
    assert registry.get("connected_system")["role"] == "onboarding"
    assert registry.get("onboarding_system")["role"] == "connected"
    assert set(repository.list_codes()) == {"purchase_task_result", "office_ai_form"}
