from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx

from app.command_center.schemas import ExecutionCommand, StepResult
from app.command_center.tool_catalog import ToolCatalog


class BindingResolver:
    @staticmethod
    def resolve(expression: str, context: dict[str, Any]) -> Any:
        parts = expression.split(".")
        if not parts or parts[0] not in {"task", "steps", "literal"}:
            raise ValueError(f"Unsupported binding: {expression}")
        value: Any = context
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"Binding not found: {expression}")
            value = value[part]
        return value


class ToolExecutor:
    def __init__(self, catalog: ToolCatalog, client: httpx.Client | None = None):
        self.catalog = catalog
        self.client = client or httpx.Client(timeout=30)

    def execute(self, command: ExecutionCommand) -> StepResult:
        started_at = datetime.now(UTC)
        tool = self.catalog.get(command.tool_id)
        path = tool.path_template
        for name, value in command.arguments.get("path", {}).items():
            path = path.replace(f"{{{name}}}", str(value))
        headers: dict[str, str] = {}
        if command.idempotency_key:
            headers["Idempotency-Key"] = command.idempotency_key
        request_kwargs: dict[str, Any] = {"headers": headers}
        body = command.arguments.get("body", {})
        if tool.content_type == "application/json":
            request_kwargs["json"] = body
        elif body:
            request_kwargs["data"] = body
        try:
            response = self.client.request(
                tool.method,
                f"{tool.base_url}{path}",
                **request_kwargs,
            )
            response.raise_for_status()
            payload = response.json()
            side_effect: dict[str, Any] = {
                "occurred": tool.method != "GET",
            }
            if tool.method != "GET":
                side_effect.update(
                    {
                        "operation": {
                            "tool_id": tool.tool_id,
                            "method": tool.method,
                            "path": path,
                        },
                        "idempotency": {
                            "protected": bool(command.idempotency_key),
                            "key_fingerprint": (
                                hashlib.sha256(
                                    command.idempotency_key.encode("utf-8")
                                ).hexdigest()
                                if command.idempotency_key
                                else None
                            ),
                        },
                    }
                )
            return StepResult(
                run_id=command.run_id,
                step_id=command.step_id,
                tool_id=command.tool_id,
                status="succeeded",
                started_at=started_at,
                ended_at=datetime.now(UTC),
                request_summary={"method": tool.method, "path": path},
                response_summary={"status_code": response.status_code},
                normalized_output=payload,
                side_effect=side_effect,
                retry_safe=bool(command.idempotency_key) or tool.method == "GET",
            )
        except (httpx.HTTPError, ValueError) as exc:
            return StepResult(
                run_id=command.run_id,
                step_id=command.step_id,
                tool_id=command.tool_id,
                status="failed",
                started_at=started_at,
                ended_at=datetime.now(UTC),
                request_summary={"method": tool.method, "path": path},
                error={"code": type(exc).__name__, "message": str(exc)},
                retry_safe=bool(command.idempotency_key) or tool.method == "GET",
            )
