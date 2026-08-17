from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator


SeedRecord = dict[str, Any]
SeedTask = dict[str, Any]


class CreateTaskRequest(BaseModel):
    title: str
    task_type: str
    form_code: str
    content: dict[str, Any]
    assignee_id: str = "u001"


class PurchaseLinkRequest(BaseModel):
    purchase_request_id: str


class PurchaseRequest(BaseModel):
    item_name: str
    quantity: int
    reason: str


class PurchaseFollowUpItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_code: str = Field(min_length=1, max_length=128)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    suggested_supplier: str = Field(default="", max_length=300)
    required_date: str = Field(default="", max_length=32)
    remark: str = Field(default="", max_length=1_000)


class PurchaseFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    remark: str = Field(default="", max_length=1_000)
    items: list[PurchaseFollowUpItem] = Field(min_length=1, max_length=100)
    source_reference: str | None = Field(default=None, max_length=128)
    record_purpose: Literal["formal", "automated_test"] = "formal"
    verification_run_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_verification_owner_for_test_record(self):
        if self.record_purpose == "automated_test" and not self.verification_run_id:
            raise ValueError("automated test follow-up requires verification_run_id")
        if self.record_purpose == "formal" and self.verification_run_id is not None:
            raise ValueError("formal follow-up must not have verification_run_id")
        return self


class PurchaseFollowUpRecord(BaseModel):
    follow_up_id: str
    title: str
    items: list[PurchaseFollowUpItem]
    source_reference: str | None = None
    remark: str = ""
    record_purpose: Literal["formal", "automated_test"]
    verification_run_id: str | None = None
    created_at: str


def create_external_app(
    *,
    system_name: str,
    system_code: str = "demo_system",
    interface_type: Literal["workflow", "custom_url"] = "custom_url",
    workflow_template_id: str | None = None,
    task_type: str = "general_review",
    task_form_code: str = "task_result",
    public_base_url: str = "http://127.0.0.1",
    database_path: Path,
    seed_records: list[SeedRecord],
    seed_tasks: list[SeedTask] | None = None,
) -> FastAPI:
    app = FastAPI(title=system_name)
    ui_dir = Path(__file__).parent / "ui"
    app.mount("/assets", StaticFiles(directory=ui_dir), name="external-system-assets")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    seed_tasks = seed_tasks or []
    _initialize_database(database_path, seed_records, seed_tasks)

    ticket_prefix = "ONBOARDING" if "待接入" in system_name else "CONNECTED"

    @app.get("/", include_in_schema=False)
    def visual_page() -> FileResponse:
        return FileResponse(ui_dir / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "system": system_name}

    @app.get("/api/system-profile")
    def system_profile() -> dict[str, str | None]:
        return {
            "system_code": system_code,
            "system_name": system_name,
            "interface_type": interface_type,
            "workflow_template_id": workflow_template_id,
            "task_type": task_type,
            "task_form_code": task_form_code,
        }

    @app.get("/api/submissions")
    def list_submissions() -> dict[str, object]:
        with _connect(database_path) as connection:
            rows = connection.execute(
                """
                select id, ticket_id, operator_id, form_values, source,
                       endpoint_type, fd_template_id, created_at
                from submissions
                order by id desc
                """
            ).fetchall()

        return {
            "system_name": system_name,
            "items": [
                {
                    "id": row["id"],
                    "ticket_id": row["ticket_id"],
                    "operator_id": row["operator_id"],
                    "form_values": json.loads(row["form_values"]),
                    "source": row["source"],
                    "endpoint_type": row["endpoint_type"],
                    "fd_template_id": row["fd_template_id"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        }

    @app.get("/api/purchase-follow-ups")
    def list_purchase_follow_ups() -> dict[str, object]:
        with _connect(database_path) as connection:
            rows = connection.execute(
                "select * from purchase_follow_ups order by id desc"
            ).fetchall()
        return {
            "system_name": system_name,
            "items": [_purchase_follow_up_row(row) for row in rows],
        }

    @app.post(
        "/api/purchase-follow-ups",
        status_code=201,
        response_model=PurchaseFollowUpRecord,
        openapi_extra={"x-command-center-idempotency": "header"},
    )
    def create_purchase_follow_up(
        request: PurchaseFollowUpRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, object]:
        with _connect(database_path) as connection:
            existing = _load_idempotent_response(
                connection,
                "create_purchase_follow_up",
                idempotency_key,
            )
            if existing is not None:
                return existing
            created_at = datetime.now().isoformat(timespec="seconds")
            cursor = connection.execute(
                """
                insert into purchase_follow_ups(
                    mes_apply_no, material, quantity, applicant, title, items_json,
                    source_reference, remark, record_purpose, verification_run_id,
                    created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.source_reference or "internal",
                    request.items[0].material_code,
                    request.items[0].quantity,
                    "internal",
                    request.title,
                    json.dumps(
                        [item.model_dump(mode="json") for item in request.items],
                        ensure_ascii=False,
                    ),
                    request.source_reference,
                    request.remark,
                    request.record_purpose,
                    request.verification_run_id,
                    created_at,
                ),
            )
            follow_up_id = f"FOLLOW-UP-{cursor.lastrowid:04d}"
            connection.execute(
                "update purchase_follow_ups set follow_up_id = ? where id = ?",
                (follow_up_id, cursor.lastrowid),
            )
            row = connection.execute(
                "select * from purchase_follow_ups where id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            response = _purchase_follow_up_row(row)
            _store_idempotent_response(
                connection,
                "create_purchase_follow_up",
                idempotency_key,
                response,
            )
            connection.commit()
            return response

    @app.get(
        "/api/purchase-follow-ups/{follow_up_id}",
        response_model=PurchaseFollowUpRecord,
    )
    def get_purchase_follow_up(follow_up_id: str) -> dict[str, object]:
        with _connect(database_path) as connection:
            row = connection.execute(
                "select * from purchase_follow_ups where follow_up_id = ?",
                (follow_up_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="采购跟进任务不存在")
        return _purchase_follow_up_row(row)

    @app.delete("/api/purchase-follow-ups/{follow_up_id}")
    def delete_purchase_follow_up(
        follow_up_id: str,
        verification_run_id: str = Header(alias="X-Verification-Run-Id"),
    ) -> dict[str, object]:
        with _connect(database_path) as connection:
            row = connection.execute(
                "select * from purchase_follow_ups where follow_up_id = ?",
                (follow_up_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="采购跟进任务不存在")
            if (
                row["record_purpose"] != "automated_test"
                or row["verification_run_id"] != verification_run_id
            ):
                raise HTTPException(status_code=409, detail="只允许清理当前验证运行创建的测试任务")
            connection.execute(
                "delete from purchase_follow_ups where follow_up_id = ?",
                (follow_up_id,),
            )
            connection.commit()
        return {"deleted": True, "follow_up_id": follow_up_id}

    @app.post("/api/forms/submit")
    def submit_form(
        docOperator: str = Form(...),
        formValues: str = Form(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        operator = json.loads(docOperator)
        values = json.loads(formValues)
        operator_id = str(operator.get("Id", ""))
        created_at = datetime.now().isoformat(timespec="seconds")

        with _connect(database_path) as connection:
            existing_response = _load_idempotent_response(
                connection,
                "submit_form",
                idempotency_key,
            )
            if existing_response is not None:
                return existing_response
            cursor = connection.execute(
                """
                insert into submissions(
                    operator_id, form_values, source, endpoint_type, fd_template_id, created_at
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    operator_id,
                    json.dumps(values, ensure_ascii=False),
                    "submitted",
                    "custom_url",
                    None,
                    created_at,
                ),
            )
            ticket_id = f"{ticket_prefix}-{cursor.lastrowid:04d}"
            connection.execute(
                "update submissions set ticket_id = ? where id = ?",
                (ticket_id, cursor.lastrowid),
            )
            response = {
                "success": True,
                "message": "提交成功",
                "data": {
                    "id": ticket_id,
                    "operator_id": operator_id,
                    "form_values": values,
                },
            }
            _store_idempotent_response(
                connection,
                "submit_form",
                idempotency_key,
                response,
            )
            connection.commit()
            return response

    if interface_type == "workflow":
        @app.post("/api/purchase-requests")
        def create_purchase_request(
            request: PurchaseRequest,
            idempotency_key: str = Header(alias="Idempotency-Key"),
        ) -> dict[str, object]:
            with _connect(database_path) as connection:
                existing_response = _load_idempotent_response(
                    connection,
                    "create_purchase_request",
                    idempotency_key,
                )
                if existing_response is not None:
                    return existing_response
                created_at = datetime.now().isoformat(timespec="seconds")
                values = {
                    "item_name": request.item_name,
                    "quantity": request.quantity,
                    "reason": request.reason,
                }
                cursor = connection.execute(
                    """
                    insert into submissions(
                        operator_id, form_values, source, endpoint_type,
                        fd_template_id, created_at
                    )
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "u001",
                        json.dumps(values, ensure_ascii=False),
                        "submitted",
                        "workflow",
                        workflow_template_id,
                        created_at,
                    ),
                )
                ticket_id = f"WORKFLOW-{cursor.lastrowid:04d}"
                connection.execute(
                    "update submissions set ticket_id = ? where id = ?",
                    (ticket_id, cursor.lastrowid),
                )
                next_task_id = connection.execute(
                    "select coalesce(max(id), 0) + 1 as next_id from tasks"
                ).fetchone()["next_id"]
                approval_task_id = (
                    f"{system_code.upper()}-TASK-{next_task_id:04d}"
                )
                task_content = {
                    "purchase_request_id": ticket_id,
                    "item_name": request.item_name,
                    "quantity": request.quantity,
                    "reason": request.reason,
                    "applicant_id": "u001",
                }
                connection.execute(
                    """
                    insert into tasks(
                        task_id, title, task_type, form_code, content, status,
                        assignee_id, created_at
                    )
                    values (?, ?, ?, ?, ?, 'pending', 'u002', ?)
                    """,
                    (
                        approval_task_id,
                        f"审批采购申请：{request.item_name}",
                        task_type,
                        task_form_code,
                        json.dumps(task_content, ensure_ascii=False),
                        created_at,
                    ),
                )
                response = {
                    "success": True,
                    "data": {
                        "id": ticket_id,
                        **values,
                        "approval_task_id": approval_task_id,
                    },
                }
                _store_idempotent_response(
                    connection,
                    "create_purchase_request",
                    idempotency_key,
                    response,
                )
                connection.commit()
                return response

        @app.post("/api/workflows/start")
        def start_workflow(
            docSubject: str = Form(...),
            fdTemplateId: str = Form(...),
            formValues: str = Form(...),
            docCreator: str = Form(...),
            docStatus: str = Form("20"),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ) -> dict[str, object]:
            values = json.loads(formValues)
            created_at = datetime.now().isoformat(timespec="seconds")
            with _connect(database_path) as connection:
                existing_response = _load_idempotent_response(
                    connection,
                    "start_workflow",
                    idempotency_key,
                )
                if existing_response is not None:
                    return existing_response
                cursor = connection.execute(
                    """
                    insert into submissions(
                        operator_id, form_values, source, endpoint_type,
                        fd_template_id, created_at
                    )
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        docCreator,
                        json.dumps(values, ensure_ascii=False),
                        "submitted",
                        "workflow",
                        fdTemplateId,
                        created_at,
                    ),
                )
                ticket_id = f"WORKFLOW-{cursor.lastrowid:04d}"
                connection.execute(
                    "update submissions set ticket_id = ? where id = ?",
                    (ticket_id, cursor.lastrowid),
                )
                response = {
                    "success": True,
                    "message": "流程启动成功",
                    "data": {
                        "id": ticket_id,
                        "doc_subject": docSubject,
                        "fd_template_id": fdTemplateId,
                        "doc_status": docStatus,
                        "form_values": values,
                    },
                }
                _store_idempotent_response(
                    connection,
                    "start_workflow",
                    idempotency_key,
                    response,
                )
                connection.commit()
                return response

    @app.post("/api/tasks", status_code=201)
    def create_task(request: CreateTaskRequest) -> dict[str, object]:
        created_at = datetime.now().isoformat(timespec="seconds")
        with _connect(database_path) as connection:
            next_id = connection.execute(
                "select coalesce(max(id), 0) + 1 as next_id from tasks"
            ).fetchone()["next_id"]
            task_id = f"{system_code.upper()}-TASK-{next_id:04d}"
            connection.execute(
                """
                insert into tasks(
                    task_id, title, task_type, form_code, content, status,
                    assignee_id, created_at
                )
                values (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    task_id,
                    request.title,
                    request.task_type,
                    request.form_code,
                    json.dumps(request.content, ensure_ascii=False),
                    request.assignee_id,
                    created_at,
                ),
            )
            connection.commit()
        return {
            "task_id": task_id,
            "title": request.title,
            "status": "pending",
            "assignee_id": request.assignee_id,
            "created_at": created_at,
        }

    @app.get("/api/tasks")
    def list_tasks(
        operator_id: str | None = None,
        status: Literal["pending", "processing", "completed"] = "pending",
    ) -> dict[str, object]:
        where_clause = "status = ?"
        parameters: tuple[str, ...] = (status,)
        if operator_id is not None:
            where_clause = "assignee_id = ? and status = ?"
            parameters = (operator_id, status)

        with _connect(database_path) as connection:
            rows = connection.execute(
                f"""
                select task_id, title, task_type, form_code, content, status,
                       assignee_id, result_values, created_at, completed_at
                from tasks
                where {where_clause}
                order by created_at desc
                """,
                parameters,
            ).fetchall()

        return {
            "system_name": system_name,
            "items": [
                {
                    "task_id": row["task_id"],
                    "title": row["title"],
                    "task_type": row["task_type"],
                    "form_code": row["form_code"],
                    "content": json.loads(row["content"]),
                    "status": row["status"],
                    "assignee_id": row["assignee_id"],
                    "result_values": (
                        json.loads(row["result_values"])
                        if row["result_values"]
                        else None
                    ),
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                }
                for row in rows
            ],
        }

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, object]:
        with _connect(database_path) as connection:
            row = connection.execute(
                """
                select task_id, title, task_type, form_code, content, status,
                       assignee_id, result_values, created_at, completed_at
                from tasks
                where task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _task_row_to_dict(row)

    @app.post("/api/tasks/{task_id}/purchase-link")
    def link_purchase_request(
        task_id: str,
        request: PurchaseLinkRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, object]:
        operation = f"link_purchase_request:{task_id}"
        with _connect(database_path) as connection:
            existing_response = _load_idempotent_response(
                connection,
                operation,
                idempotency_key,
            )
            if existing_response is not None:
                return existing_response
            task = connection.execute(
                "select task_id from tasks where task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            result_values = {"purchase_request_id": request.purchase_request_id}
            connection.execute(
                """
                update tasks
                set status = 'processing', result_values = ?, completed_at = null
                where task_id = ?
                """,
                (json.dumps(result_values, ensure_ascii=False), task_id),
            )
            response = {
                "task_id": task_id,
                "status": "processing",
                "result_values": result_values,
            }
            _store_idempotent_response(
                connection,
                operation,
                idempotency_key,
                response,
            )
            connection.commit()
            return response

    @app.post("/api/tasks/complete")
    def complete_task(
        docOperator: str = Form(...),
        formValues: str = Form(...),
    ) -> dict[str, object]:
        operator = json.loads(docOperator)
        values = json.loads(formValues)
        operator_id = str(operator.get("Id", ""))
        task_id = str(values.get("task_id", ""))
        completed_at = datetime.now().isoformat(timespec="seconds")

        with _connect(database_path) as connection:
            task = connection.execute(
                "select status, assignee_id from tasks where task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            if task["assignee_id"] != operator_id:
                raise HTTPException(status_code=403, detail="任务不属于当前操作人")
            if task["status"] != "pending":
                raise HTTPException(status_code=409, detail="任务已经处理")

            result_values = {key: value for key, value in values.items() if key != "task_id"}
            connection.execute(
                """
                update tasks
                set status = 'completed', result_values = ?, completed_at = ?
                where task_id = ?
                """,
                (json.dumps(result_values, ensure_ascii=False), completed_at, task_id),
            )
            connection.commit()

        return {
            "success": True,
            "message": "任务处理完成",
            "data": {
                "task_id": task_id,
                "operator_id": operator_id,
                "result_values": result_values,
                "status": "completed",
            },
        }

    @app.get("/api/interface-spec")
    def interface_spec() -> dict[str, str]:
        return {
            "system_name": system_name,
            "description": _build_interface_description(
                interface_type,
                public_base_url,
                workflow_template_id,
            ),
        }

    @app.post("/api/demo/reset")
    def reset_demo() -> dict[str, int]:
        with _connect(database_path) as connection:
            deleted_records = connection.execute(
                "select count(*) as count from submissions"
            ).fetchone()["count"]
            connection.execute("delete from submissions")
            connection.execute(
                "delete from sqlite_sequence where name = 'submissions'"
            )
            for record in seed_records:
                connection.execute(
                    """
                    insert into submissions(ticket_id, operator_id, form_values, source, created_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        record["ticket_id"],
                        record["operator_id"],
                        json.dumps(record["form_values"], ensure_ascii=False),
                        "seed",
                        record["created_at"],
                    ),
                )
            connection.execute("delete from tasks")
            connection.execute("delete from purchase_follow_ups")
            connection.execute("delete from idempotency_records")
            for task in seed_tasks:
                _insert_seed_task(connection, task)
            connection.commit()
            remaining_records = connection.execute(
                "select count(*) as count from submissions"
            ).fetchone()["count"]

        return {
            "deleted_records": deleted_records,
            "remaining_records": remaining_records,
        }

    return app


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_database(
    database_path: Path,
    seed_records: list[SeedRecord],
    seed_tasks: list[SeedTask],
) -> None:
    with _connect(database_path) as connection:
        connection.execute(
            """
            create table if not exists submissions (
                id integer primary key autoincrement,
                ticket_id text,
                operator_id text not null,
                form_values text not null,
                source text not null,
                endpoint_type text not null default 'custom_url',
                fd_template_id text,
                created_at text not null
            )
            """
        )
        connection.execute(
            """
            create table if not exists purchase_follow_ups (
                id integer primary key autoincrement,
                follow_up_id text unique,
                mes_apply_no text not null,
                material text not null,
                quantity real not null,
                applicant text not null,
                remark text not null,
                record_purpose text not null,
                verification_run_id text,
                title text,
                items_json text,
                source_reference text,
                created_at text not null
            )
            """
        )
        connection.execute(
            """
            create table if not exists idempotency_records (
                operation text not null,
                idempotency_key text not null,
                response_json text not null,
                primary key(operation, idempotency_key)
            )
            """
        )
        _ensure_column(
            connection,
            "submissions",
            "endpoint_type",
            "text not null default 'custom_url'",
        )
        _ensure_column(connection, "submissions", "fd_template_id", "text")
        _ensure_column(connection, "purchase_follow_ups", "title", "text")
        _ensure_column(connection, "purchase_follow_ups", "items_json", "text")
        _ensure_column(connection, "purchase_follow_ups", "source_reference", "text")
        connection.execute(
            """
            create table if not exists tasks (
                id integer primary key autoincrement,
                task_id text not null unique,
                title text not null,
                task_type text not null,
                form_code text not null,
                content text not null,
                status text not null,
                assignee_id text not null,
                result_values text,
                created_at text not null,
                completed_at text
            )
            """
        )
        existing = connection.execute(
            "select count(*) as count from submissions where source = 'seed'"
        ).fetchone()["count"]
        if existing == 0:
            for record in seed_records:
                connection.execute(
                    """
                    insert into submissions(ticket_id, operator_id, form_values, source, created_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        record["ticket_id"],
                        record["operator_id"],
                        json.dumps(record["form_values"], ensure_ascii=False),
                        "seed",
                        record["created_at"],
                    ),
                )
        existing_tasks = connection.execute(
            "select count(*) as count from tasks"
        ).fetchone()["count"]
        if existing_tasks == 0:
            for task in seed_tasks:
                _insert_seed_task(connection, task)
        connection.commit()


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"] for row in connection.execute(f"pragma table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"alter table {table} add column {column} {definition}")


def _insert_seed_task(connection: sqlite3.Connection, task: SeedTask) -> None:
    connection.execute(
        """
        insert into tasks(
            task_id, title, task_type, form_code, content, status,
            assignee_id, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task["task_id"],
            task["title"],
            task["task_type"],
            task["form_code"],
            json.dumps(task["content"], ensure_ascii=False),
            task["status"],
            task["assignee_id"],
            task["created_at"],
        ),
    )


def _task_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return {
        "task_id": row["task_id"],
        "title": row["title"],
        "task_type": row["task_type"],
        "form_code": row["form_code"],
        "content": json.loads(row["content"]),
        "status": row["status"],
        "assignee_id": row["assignee_id"],
        "result_values": json.loads(row["result_values"]) if row["result_values"] else None,
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


def _purchase_follow_up_row(row: sqlite3.Row) -> dict[str, object]:
    items = json.loads(row["items_json"]) if row["items_json"] else [
        {
            "material_code": row["material"],
            "quantity": row["quantity"],
            "unit": "",
            "suggested_supplier": "",
            "required_date": "",
            "remark": "",
        }
    ]
    return {
        "follow_up_id": row["follow_up_id"],
        "title": row["title"] or "采购申请跟进",
        "items": items,
        "source_reference": row["source_reference"],
        "remark": row["remark"],
        "record_purpose": row["record_purpose"],
        "verification_run_id": row["verification_run_id"],
        "created_at": row["created_at"],
    }


def _load_idempotent_response(
    connection: sqlite3.Connection,
    operation: str,
    idempotency_key: str | None,
) -> dict[str, object] | None:
    if not idempotency_key:
        return None
    row = connection.execute(
        """
        select response_json
        from idempotency_records
        where operation = ? and idempotency_key = ?
        """,
        (operation, idempotency_key),
    ).fetchone()
    return json.loads(row["response_json"]) if row else None


def _store_idempotent_response(
    connection: sqlite3.Connection,
    operation: str,
    idempotency_key: str | None,
    response: dict[str, object],
) -> None:
    if not idempotency_key:
        return
    connection.execute(
        """
        insert into idempotency_records(operation, idempotency_key, response_json)
        values (?, ?, ?)
        """,
        (operation, idempotency_key, json.dumps(response, ensure_ascii=False)),
    )


def _build_interface_description(
    interface_type: Literal["workflow", "custom_url"],
    public_base_url: str,
    workflow_template_id: str | None,
) -> str:
    if interface_type == "workflow":
        return (
            f"POST {public_base_url}/api/workflows/start。流程类接口，Body 使用 form-data。"
            f"fdTemplateId 固定为 {workflow_template_id or 'purchase_request_001'}。"
            "参数包含 docSubject、fdTemplateId、formValues、docCreator、docStatus。"
            'formValues 示例 {"fd_item_name":"包装箱","fd_quantity":20,"fd_reason":"仓库库存不足"}。'
            "字段说明：fd_item_name 为采购物品，fd_quantity 为数量，fd_reason 为采购原因，均为必填。"
        )
    return (
        f"POST {public_base_url}/api/forms/submit。独立 URL 类接口，Body 使用 form-data。"
        '入参只有 docOperator 和 formValues。docOperator 示例 {"Id":"u001"}。'
        'formValues 示例 {"itemName":"签字笔","quantity":10,"usage":"会议使用","applicant":"王五"}。'
        "字段说明：itemName 为申请物品，quantity 为数量，usage 为用途，applicant 为申请人，均为必填。"
    )
