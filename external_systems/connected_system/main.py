from pathlib import Path

from external_systems.common import create_external_app


DATABASE_PATH = Path(__file__).parent / "data" / "connected.sqlite3"


def seed_records() -> list[dict[str, object]]:
    return [
        {
            "ticket_id": "CONNECTED-SEED-0001",
            "operator_id": "u001",
            "form_values": {
                "fd_item_name": "打印纸",
                "fd_quantity": 10,
                "fd_reason": "行政库存补充",
            },
            "created_at": "2026-07-01T09:30:00",
        },
        {
            "ticket_id": "CONNECTED-SEED-0002",
            "operator_id": "u003",
            "form_values": {
                "fd_item_name": "包装箱",
                "fd_quantity": 30,
                "fd_reason": "仓库发货备用",
            },
            "created_at": "2026-07-02T14:15:00",
        },
    ]


def seed_tasks() -> list[dict[str, object]]:
    return [
        {
            "task_id": "PURCHASE-TASK-0001",
            "title": "核对打印纸采购数量",
            "task_type": "purchase_review",
            "form_code": "purchase_task_result",
            "content": {
                "item_name": "打印纸",
                "quantity": 10,
                "reason": "行政库存补充",
            },
            "status": "pending",
            "assignee_id": "u001",
            "created_at": "2026-07-10T09:30:00",
        },
        {
            "task_id": "PURCHASE-TASK-0002",
            "title": "确认包装箱采购用途",
            "task_type": "purchase_review",
            "form_code": "purchase_task_result",
            "content": {
                "item_name": "包装箱",
                "quantity": 30,
                "reason": "仓库发货备用",
            },
            "status": "pending",
            "assignee_id": "u001",
            "created_at": "2026-07-11T14:15:00",
        },
    ]


app = create_external_app(
    system_name="采购业务系统",
    system_code="connected_system",
    interface_type="workflow",
    workflow_template_id="purchase_request_001",
    task_type="purchase_review",
    task_form_code="purchase_task_result",
    public_base_url="http://127.0.0.1:8101",
    database_path=DATABASE_PATH,
    seed_records=seed_records(),
    seed_tasks=seed_tasks(),
)
