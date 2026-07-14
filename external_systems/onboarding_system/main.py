from pathlib import Path

from external_systems.common import create_external_app


DATABASE_PATH = Path(__file__).parent / "data" / "onboarding.sqlite3"


def seed_records() -> list[dict[str, object]]:
    return []


def seed_tasks() -> list[dict[str, object]]:
    return [
        {
            "task_id": "OFFICE-TASK-0001",
            "title": "确认签字笔领用申请",
            "task_type": "office_supply_review",
            "form_code": "office_supply_task_result",
            "content": {
                "item_name": "签字笔",
                "quantity": 10,
                "usage": "会议使用",
                "applicant": "王五",
            },
            "status": "pending",
            "assignee_id": "u001",
            "created_at": "2026-07-12T09:20:00",
        },
        {
            "task_id": "OFFICE-TASK-0002",
            "title": "核对打印纸库存",
            "task_type": "office_supply_review",
            "form_code": "office_supply_task_result",
            "content": {
                "item_name": "A4 打印纸",
                "quantity": 5,
                "usage": "项目资料打印",
                "applicant": "李明",
            },
            "status": "pending",
            "assignee_id": "u001",
            "created_at": "2026-07-12T15:40:00",
        },
    ]


app = create_external_app(
    system_name="办公用品系统",
    system_code="onboarding_system",
    interface_type="custom_url",
    task_type="office_supply_review",
    task_form_code="office_supply_task_result",
    public_base_url="http://127.0.0.1:8102",
    database_path=DATABASE_PATH,
    seed_records=seed_records(),
    seed_tasks=seed_tasks(),
)
