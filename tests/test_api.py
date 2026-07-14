from fastapi.testclient import TestClient

import app.main as main_module
from app.external_systems import ExternalSystemClient, ExternalSystemRegistry
from app.forms.repository import FormTemplateRepository
from app.main import app


client = TestClient(app)


def test_lists_form_templates():
    response = client.get("/forms")

    assert response.status_code == 200
    codes = [item["form_code"] for item in response.json()]
    assert "purchase_task_result" in codes
    assert "office_supply_task_result" in codes
    assert "after_sales" in codes
    assert "hr_request" in codes


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_submits_after_sales_to_mock_api():
    response = client.post(
        "/forms/after_sales/submit",
        json={
            "operator_id": "demo-user-001",
            "values": {
                "customer_name": "测试客户",
                "issue_description": "设备需要售后处理",
                "priority": "普通",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["endpoint_type"] == "workflow"
    assert body["submit_mode"] == "mock"
    assert body["ticket_id"].startswith("MOCK-")


def test_saves_ai_draft_as_form_config(tmp_path, monkeypatch):
    repository = FormTemplateRepository(templates_dir=tmp_path)
    monkeypatch.setattr(main_module, "FormTemplateRepository", lambda: repository)

    response = client.post(
        "/forms",
        json={
            "form_code": "office_supply_request",
            "form_name": "办公用品申请",
            "endpoint_type": "custom_url",
            "endpoint": {
                "url": "http://mock.local/office-supply",
                "submit_mode": "mock",
            },
            "fields": [
                {
                    "label": "申请物品",
                    "key": "itemName",
                    "type": "text",
                    "required": True,
                }
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["form_code"] == "office_supply_request"
    assert repository.get("office_supply_request").form_name == "办公用品申请"


def test_saving_ai_form_automatically_connects_matching_system(tmp_path, monkeypatch):
    repository = FormTemplateRepository(templates_dir=tmp_path / "forms")
    registry = ExternalSystemRegistry(state_path=tmp_path / "external_systems.json")
    monkeypatch.setattr(main_module, "FormTemplateRepository", lambda: repository)
    monkeypatch.setattr(
        main_module,
        "external_system_client",
        ExternalSystemClient(registry=registry),
    )

    response = client.post(
        "/forms",
        json={
            "form_code": "office_supply_request",
            "form_name": "办公用品申请",
            "endpoint_type": "custom_url",
            "endpoint": {
                "url": "http://127.0.0.1:8102/api/forms/submit",
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
        },
    )

    assert response.status_code == 201
    system = registry.get("onboarding_system")
    assert system["role"] == "connected"
    assert system["form_codes"] == ["office_supply_request"]


def test_rejects_duplicate_form_code(tmp_path, monkeypatch):
    repository = FormTemplateRepository(templates_dir=tmp_path)
    monkeypatch.setattr(main_module, "FormTemplateRepository", lambda: repository)
    payload = {
        "form_code": "office_supply_request",
        "form_name": "办公用品申请",
        "endpoint_type": "custom_url",
        "endpoint": {
            "url": "http://mock.local/office-supply",
            "submit_mode": "mock",
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

    first = client.post("/forms", json=payload)
    second = client.post("/forms", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_generates_ai_form_config_draft_without_saving(monkeypatch):
    def fake_generate_form_config(request):
        return {
            "draft_config": {
                "form_code": "tower_order_draft",
                "form_name": request.form_name,
                "endpoint_type": "custom_url",
                "endpoint": {
                    "url": "https://oa.example.com/api/orders",
                },
                "fields": [
                    {
                        "label": "订单号",
                        "key": "orderNo",
                        "type": "text",
                        "required": True,
                        "item_fields": [],
                    }
                ],
            },
            "warnings": ["字段必填规则由 AI 推断，需人工确认"],
        }

    monkeypatch.setattr(main_module, "generate_form_config", fake_generate_form_config)

    response = client.post(
        "/ai/form-config/generate",
        json={
            "form_name": "铁塔订单新增",
            "description": "POST https://oa.example.com/api/orders",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["draft_config"]["form_code"] == "tower_order_draft"
    assert body["draft_config"]["endpoint_type"] == "custom_url"
    assert body["warnings"] == ["字段必填规则由 AI 推断，需人工确认"]

    forms_response = client.get("/forms")
    form_codes = [item["form_code"] for item in forms_response.json()]
    assert "tower_order_draft" not in form_codes


def test_ai_form_config_returns_readable_error_when_model_fails(monkeypatch):
    def fake_generate_form_config(_request):
        raise RuntimeError("模型服务调用失败：Arrearage")

    monkeypatch.setattr(main_module, "generate_form_config", fake_generate_form_config)

    response = client.post(
        "/ai/form-config/generate",
        json={
            "form_name": "铁塔订单新增",
            "description": "POST https://oa.example.com/api/orders",
        },
    )

    assert response.status_code == 502
    assert "模型服务调用失败" in response.json()["detail"]
