from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from collections.abc import Callable
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
    def __init__(
        self,
        catalog: ToolCatalog,
        client: httpx.Client | None = None,
        *,
        credential_provider: Callable[[str], dict[str, str]] | None = None,
        credential_invalidator: Callable[[str], None] | None = None,
    ):
        self.catalog = catalog
        self.client = client or httpx.Client(timeout=30)
        self.credential_provider = credential_provider
        self.credential_invalidator = credential_invalidator

    def execute(self, command: ExecutionCommand) -> StepResult:
        started_at = datetime.now(UTC)
        tool = self.catalog.get(command.tool_id)
        path = tool.path_template
        for name, value in command.arguments.get("path", {}).items():
            path = path.replace(f"{{{name}}}", str(value))
        headers: dict[str, str] = {}
        if command.idempotency_key:
            headers["Idempotency-Key"] = command.idempotency_key
        if tool.credential_header:
            try:
                provided = (
                    self.credential_provider(tool.system_code)
                    if self.credential_provider is not None
                    else {}
                )
                if not isinstance(provided, dict):
                    provided = {}
            except Exception:
                provided = {}
            credential = next(
                (
                    value
                    for name, value in provided.items()
                    if name.casefold() == tool.credential_header.casefold()
                ),
                None,
            )
            if not credential:
                return StepResult(
                    run_id=command.run_id,
                    step_id=command.step_id,
                    tool_id=command.tool_id,
                    status="failed",
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    request_summary={"method": tool.method, "path": path},
                    error={
                        "code": "MissingCredential",
                        "message": "required request credential is unavailable",
                    },
                    retry_safe=tool.side_effect == "read",
                )
            headers[tool.credential_header] = credential
        request_kwargs: dict[str, Any] = {"headers": headers}
        query = command.arguments.get("query", {})
        if query:
            request_kwargs["params"] = query
        body = command.arguments.get("body", {})
        if isinstance(body, dict) and tool.body_schema:
            body = _omit_optional_nulls(body, tool.body_schema)
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
            if len(response.content) > tool.max_response_bytes:
                raise ResponseTooLargeError
            payload = response.json()
            is_write = tool.side_effect == "write"
            side_effect: dict[str, Any] = {"occurred": is_write}
            if is_write:
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
                retry_safe=bool(command.idempotency_key) or not is_write,
            )
        except (httpx.HTTPError, ValueError) as exc:
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in {401, 403}
                and self.credential_invalidator is not None
            ):
                try:
                    self.credential_invalidator(tool.system_code)
                except Exception:
                    pass
            return StepResult(
                run_id=command.run_id,
                step_id=command.step_id,
                tool_id=command.tool_id,
                status="failed",
                started_at=started_at,
                ended_at=datetime.now(UTC),
                request_summary={"method": tool.method, "path": path},
                error={
                    "code": (
                        "ResponseTooLarge"
                        if isinstance(exc, ResponseTooLargeError)
                        else type(exc).__name__
                    ),
                    "message": str(exc) or "response exceeded the configured limit",
                },
                retry_safe=(
                    bool(command.idempotency_key) or tool.side_effect == "read"
                ),
            )


class ResponseTooLargeError(ValueError):
    pass


def _omit_optional_nulls(value: Any, schema: dict[str, Any]) -> Any:
    """Remove only optional nulls according to the declared OpenAPI schema."""

    schema_type = schema.get("type")
    if schema_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        required_names = set(required) if isinstance(required, list) else set()
        normalized: dict[str, Any] = {}
        for name, item in value.items():
            if item is None and name not in required_names:
                continue
            item_schema = properties.get(name, {}) if isinstance(properties, dict) else {}
            normalized[name] = (
                _omit_optional_nulls(item, item_schema)
                if isinstance(item_schema, dict)
                else item
            )
        return normalized
    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items", {})
        return [
            _omit_optional_nulls(item, item_schema)
            if isinstance(item_schema, dict)
            else item
            for item in value
        ]
    return value
