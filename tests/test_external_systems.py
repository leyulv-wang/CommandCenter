from pathlib import Path

from fastapi.testclient import TestClient

from external_systems.common import create_external_app
from external_systems.connected_system.main import seed_records as connected_seed_records
from external_systems.onboarding_system import main as onboarding_main
from external_systems.onboarding_system.main import seed_records as onboarding_seed_records


def connected_seed_tasks() -> list[dict[str, object]]:
    return [
        {
            "task_id": "PURCHASE-TASK-0001",
            "title": "核对打印纸采购数量",
            "task_type": "purchase_review",
            "form_code": "purchase_task_result",
            "content": {"item_name": "打印纸", "quantity": 10},
            "status": "pending",
            "assignee_id": "u001",
            "created_at": "2026-07-10T09:30:00",
        },
        {
            "task_id": "PURCHASE-TASK-0002",
            "title": "确认包装箱采购用途",
            "task_type": "purchase_review",
            "form_code": "purchase_task_result",
            "content": {"item_name": "包装箱", "quantity": 30},
            "status": "pending",
            "assignee_id": "u001",
            "created_at": "2026-07-11T14:15:00",
        },
    ]


def test_connected_system_lists_seed_records_and_accepts_new_submission(tmp_path: Path):
    app = create_external_app(
        system_name="已接入采购系统",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=connected_seed_records(),
    )
    client = TestClient(app)

    before = client.get("/api/submissions")

    assert before.status_code == 200
    assert len(before.json()["items"]) >= 2
    assert before.json()["items"][0]["source"] == "seed"

    response = client.post(
        "/api/forms/submit",
        data={
            "docOperator": '{"Id":"u001"}',
            "formValues": '{"fd_item_name":"测试纸箱","fd_quantity":3,"fd_reason":"演示提交"}',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"].startswith("CONNECTED-")

    after = client.get("/api/submissions")

    assert after.status_code == 200
    assert len(after.json()["items"]) == len(before.json()["items"]) + 1
    assert after.json()["items"][0]["source"] == "submitted"


def test_connected_system_accepts_workflow_submission_and_stores_template_id(tmp_path: Path):
    app = create_external_app(
        system_name="采购业务系统",
        system_code="connected_system",
        interface_type="workflow",
        workflow_template_id="purchase_request_001",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=[],
        seed_tasks=[],
    )
    client = TestClient(app)

    response = client.post(
        "/api/workflows/start",
        data={
            "docSubject": "采购申请：打印纸",
            "fdTemplateId": "purchase_request_001",
            "formValues": '{"fd_item_name":"打印纸","fd_quantity":5,"fd_reason":"项目使用"}',
            "docCreator": "u001",
            "docStatus": "20",
        },
    )

    assert response.status_code == 200
    record = client.get("/api/submissions").json()["items"][0]
    assert record["endpoint_type"] == "workflow"
    assert record["fd_template_id"] == "purchase_request_001"
    assert record["form_values"]["fd_item_name"] == "打印纸"


def test_business_system_can_create_and_assign_task(tmp_path: Path):
    app = create_external_app(
        system_name="采购业务系统",
        system_code="connected_system",
        interface_type="workflow",
        workflow_template_id="purchase_request_001",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=[],
        seed_tasks=[],
    )
    client = TestClient(app)

    response = client.post(
        "/api/tasks",
        json={
            "title": "审核显示器采购",
            "task_type": "purchase_review",
            "form_code": "purchase_task_result",
            "content": {"item_name": "显示器", "quantity": 2, "reason": "研发使用"},
            "assignee_id": "u001",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    pending = client.get("/api/tasks", params={"operator_id": "u001"}).json()["items"]
    assert pending[0]["title"] == "审核显示器采购"


def test_external_system_serves_visual_page_and_profile(tmp_path: Path):
    app = create_external_app(
        system_name="采购业务系统",
        system_code="connected_system",
        interface_type="workflow",
        workflow_template_id="purchase_request_001",
        task_type="purchase_review",
        task_form_code="purchase_task_result",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=[],
        seed_tasks=[],
    )
    client = TestClient(app)

    page = client.get("/")
    profile = client.get("/api/system-profile")

    assert page.status_code == 200
    assert "business-system-app" in page.text
    assert profile.status_code == 200
    assert profile.json() == {
        "system_code": "connected_system",
        "system_name": "采购业务系统",
        "interface_type": "workflow",
        "workflow_template_id": "purchase_request_001",
        "task_type": "purchase_review",
        "task_form_code": "purchase_task_result",
    }


def test_connected_system_lists_pending_tasks_for_operator(tmp_path: Path):
    app = create_external_app(
        system_name="已接入采购系统",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=connected_seed_records(),
        seed_tasks=connected_seed_tasks(),
    )
    client = TestClient(app)

    response = client.get("/api/tasks", params={"operator_id": "u001"})

    assert response.status_code == 200
    body = response.json()
    assert body["system_name"] == "已接入采购系统"
    assert len(body["items"]) == 2
    assert all(item["assignee_id"] == "u001" for item in body["items"])
    assert all(item["status"] == "pending" for item in body["items"])
    assert body["items"][0]["form_code"] == "purchase_task_result"


def test_connected_system_lists_all_pending_tasks_without_operator_filter(tmp_path: Path):
    tasks = connected_seed_tasks()
    tasks[1] = {**tasks[1], "assignee_id": "u002"}
    app = create_external_app(
        system_name="已接入采购系统",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=[],
        seed_tasks=tasks,
    )
    client = TestClient(app)

    response = client.get("/api/tasks")

    assert response.status_code == 200
    assert {item["assignee_id"] for item in response.json()["items"]} == {"u001", "u002"}


def test_connected_system_completes_task_and_removes_it_from_pending(tmp_path: Path):
    app = create_external_app(
        system_name="已接入采购系统",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=connected_seed_records(),
        seed_tasks=connected_seed_tasks(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/tasks/complete",
        data={
            "docOperator": '{"Id":"u001"}',
            "formValues": (
                '{"task_id":"PURCHASE-TASK-0001","decision":"approved",'
                '"comment":"数量核对无误"}'
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["task_id"] == "PURCHASE-TASK-0001"
    pending = client.get("/api/tasks", params={"operator_id": "u001"}).json()["items"]
    assert all(item["task_id"] != "PURCHASE-TASK-0001" for item in pending)

    completed = client.get(
        "/api/tasks",
        params={"operator_id": "u001", "status": "completed"},
    ).json()["items"]
    completed_task = next(
        item for item in completed if item["task_id"] == "PURCHASE-TASK-0001"
    )
    assert completed_task["result_values"] == {
        "decision": "approved",
        "comment": "数量核对无误",
    }
    assert completed_task["completed_at"]


def test_onboarding_system_starts_without_seed_records_and_exposes_interface_spec(
    tmp_path: Path,
):
    app = create_external_app(
        system_name="待接入办公用品系统",
        database_path=tmp_path / "onboarding.sqlite3",
        seed_records=onboarding_seed_records(),
    )
    client = TestClient(app)

    records = client.get("/api/submissions")
    interface_spec = client.get("/api/interface-spec")

    assert records.status_code == 200
    assert records.json()["items"] == []
    assert interface_spec.status_code == 200
    assert "formValues" in interface_spec.json()["description"]

    response = client.post(
        "/api/forms/submit",
        data={
            "docOperator": '{"Id":"u002"}',
            "formValues": '{"itemName":"签字笔","quantity":10,"usage":"会议使用","applicant":"王五"}',
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"].startswith("ONBOARDING-")
    assert client.get("/api/submissions").json()["items"][0]["source"] == "submitted"


def test_onboarding_system_demo_reset_clears_submitted_records(tmp_path: Path):
    app = create_external_app(
        system_name="待接入办公用品系统",
        database_path=tmp_path / "onboarding.sqlite3",
        seed_records=onboarding_seed_records(),
    )
    client = TestClient(app)
    client.post(
        "/api/forms/submit",
        data={
            "docOperator": '{"Id":"u002"}',
            "formValues": '{"itemName":"签字笔","quantity":10}',
        },
    )

    response = client.post("/api/demo/reset")

    assert response.status_code == 200
    assert response.json()["deleted_records"] == 1
    assert client.get("/api/submissions").json()["items"] == []


def test_onboarding_system_exposes_and_completes_office_supply_tasks(tmp_path: Path):
    tasks = getattr(onboarding_main, "seed_tasks", lambda: [])()
    app = create_external_app(
        system_name="待接入办公用品系统",
        database_path=tmp_path / "onboarding.sqlite3",
        seed_records=onboarding_seed_records(),
        seed_tasks=tasks,
    )
    client = TestClient(app)

    pending = client.get("/api/tasks", params={"operator_id": "u001"})

    assert pending.status_code == 200
    assert len(pending.json()["items"]) == 2
    task = pending.json()["items"][0]
    assert task["form_code"] == "office_supply_task_result"

    completed = client.post(
        "/api/tasks/complete",
        data={
            "docOperator": '{"Id":"u001"}',
            "formValues": (
                f'{{"task_id":"{task["task_id"]}","decision":"通过",'
                '"comment":"库存核对完成"}'
            ),
        },
    )

    assert completed.status_code == 200
    completed_items = client.get(
        "/api/tasks",
        params={"operator_id": "u001", "status": "completed"},
    ).json()["items"]
    assert any(item["task_id"] == task["task_id"] for item in completed_items)
