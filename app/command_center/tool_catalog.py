from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.command_center.system_profiles import SystemProfile


ParameterLocation = Literal["query", "path", "body", "header", "formData", "cookie"]


@dataclass(frozen=True)
class ToolParameter:
    name: str
    location: ParameterLocation
    type: str | None
    required: bool
    description: str | None


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    system_code: str
    operation_id: str
    method: str
    base_url: str
    path_template: str
    content_type: str | None
    path_parameters: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    side_effect: Literal["read", "write"] = "write"
    query_parameters: dict[str, ToolParameter] = field(default_factory=dict)
    body_schema: dict[str, Any] = field(default_factory=dict)
    credential_header: str | None = None
    parameters: tuple[ToolParameter, ...] = ()

    def with_path_parameters(self, values: dict[str, str]) -> ToolDefinition:
        return ToolDefinition(
            tool_id=self.tool_id,
            system_code=self.system_code,
            operation_id=self.operation_id,
            method=self.method,
            base_url=self.base_url,
            path_template=self.path_template,
            content_type=self.content_type,
            path_parameters=values,
            description=self.description,
            side_effect=self.side_effect,
            query_parameters=self.query_parameters,
            body_schema=self.body_schema,
            credential_header=self.credential_header,
            parameters=self.parameters,
        )


class ToolCatalog:
    def __init__(self, tools: list[ToolDefinition]):
        self._tools = {tool.tool_id: tool for tool in tools}
        canonical = json.dumps(
            [asdict(tool) for tool in tools],
            ensure_ascii=False,
            sort_keys=True,
        )
        self.version = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_openapi_documents(
        cls,
        documents: dict[str, dict[str, Any]],
        base_urls: dict[str, str],
        allowlist: set[tuple[str, str]],
    ) -> ToolCatalog:
        tools: list[ToolDefinition] = []
        for system_code, document in documents.items():
            for path, path_item in document.get("paths", {}).items():
                for method, operation in path_item.items():
                    if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                        continue
                    operation_id = operation.get("operationId")
                    if not operation_id or (system_code, operation_id) not in allowlist:
                        continue
                    tools.append(
                        _tool_from_operation(
                            document=document,
                            path=path,
                            path_item=path_item,
                            method=method,
                            operation=operation,
                            system_code=system_code,
                            base_url=base_urls[system_code],
                            side_effect="write",
                            credential_header=None,
                        )
                    )
        return cls(tools)

    @classmethod
    def from_system_profile(
        cls,
        document: dict[str, Any],
        profile: SystemProfile,
    ) -> ToolCatalog:
        tools: list[ToolDefinition] = []
        for path, path_item in document.get("paths", {}).items():
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                permission = profile.permission_for(method, path)
                operation_id = operation.get("operationId")
                if permission is None or not operation_id:
                    continue
                tools.append(
                    _tool_from_operation(
                        document=document,
                        path=path,
                        path_item=path_item,
                        method=method,
                        operation=operation,
                        system_code=profile.system_code,
                        base_url=str(profile.base_url),
                        side_effect=permission.side_effect,
                        credential_header=profile.credential_header,
                    )
                )
        return cls(tools)

    def get(self, tool_id: str) -> ToolDefinition:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"Tool is not allowlisted: {tool_id}") from exc

    def to_agent_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tools": [
                {
                    "tool_id": tool.tool_id,
                    "system_code": tool.system_code,
                    "operation_id": tool.operation_id,
                    "method": tool.method,
                    "path_template": tool.path_template,
                    "content_type": tool.content_type,
                    "description": tool.description,
                    "side_effect": tool.side_effect,
                    "query_parameters": {
                        name: asdict(parameter)
                        for name, parameter in tool.query_parameters.items()
                    },
                    "body_schema": tool.body_schema,
                    "credential_header": tool.credential_header,
                    "parameters": [asdict(parameter) for parameter in tool.parameters],
                }
                for tool in self._tools.values()
            ],
        }

    def match_exchange(
        self,
        system_code: str,
        method: str,
        path: str,
    ) -> ToolDefinition | None:
        for tool in self._tools.values():
            if tool.system_code != system_code or tool.method != method.upper():
                continue
            pattern, parameter_names = _path_pattern(tool.path_template)
            match = pattern.fullmatch(path)
            if match:
                return tool.with_path_parameters(
                    dict(zip(parameter_names, match.groups(), strict=True))
                )
        return None


def _tool_from_operation(
    *,
    document: dict[str, Any],
    path: str,
    path_item: dict[str, Any],
    method: str,
    operation: dict[str, Any],
    system_code: str,
    base_url: str,
    side_effect: Literal["read", "write"],
    credential_header: str | None,
) -> ToolDefinition:
    parameter_items = _merged_parameter_items(path_item, operation)
    parameters = _tool_parameters(parameter_items)
    content_type, body_schema = _request_body(document, operation, parameter_items)
    return ToolDefinition(
        tool_id=f"{system_code}:{operation['operationId']}",
        system_code=system_code,
        operation_id=operation["operationId"],
        method=method.upper(),
        base_url=base_url.rstrip("/"),
        path_template=path,
        content_type=content_type,
        description=operation.get("description") or operation.get("summary"),
        side_effect=side_effect,
        query_parameters={
            parameter.name: parameter
            for parameter in parameters
            if parameter.location == "query"
        },
        body_schema=body_schema,
        credential_header=credential_header,
        parameters=parameters,
    )


def _merged_parameter_items(
    path_item: dict[str, Any], operation: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
        if "$ref" in item:
            continue
        name = item.get("name")
        location = item.get("in")
        if not name or location not in {
            "query",
            "path",
            "body",
            "header",
            "formData",
            "cookie",
        }:
            continue
        merged[(name, location)] = item

    return tuple(merged.values())


def _tool_parameters(
    parameter_items: tuple[dict[str, Any], ...],
) -> tuple[ToolParameter, ...]:
    return tuple(
        ToolParameter(
            name=item["name"],
            location=item["in"],
            type=item.get("type") or item.get("schema", {}).get("type"),
            required=bool(item.get("required", False)),
            description=item.get("description"),
        )
        for item in parameter_items
    )


def _request_body(
    document: dict[str, Any],
    operation: dict[str, Any],
    parameter_items: tuple[dict[str, Any], ...],
) -> tuple[str | None, dict[str, Any]]:
    content = operation.get("requestBody", {}).get("content", {})
    if content:
        content_type = next(iter(content))
        schema = content[content_type].get("schema", {})
        return content_type, schema

    body_parameter = next(
        (item for item in parameter_items if item.get("in") == "body"),
        None,
    )
    has_form_data = any(item.get("in") == "formData" for item in parameter_items)
    consumes = operation.get("consumes") or document.get("consumes") or []
    content_type = (
        next(iter(consumes), None) if body_parameter is not None or has_form_data else None
    )
    return content_type, body_parameter.get("schema", {}) if body_parameter else {}


def _path_pattern(path_template: str) -> tuple[re.Pattern[str], list[str]]:
    names: list[str] = []
    cursor = 0
    parts: list[str] = []
    for match in re.finditer(r"\{([^}]+)\}", path_template):
        parts.append(re.escape(path_template[cursor : match.start()]))
        parts.append(r"([^/]+)")
        names.append(match.group(1))
        cursor = match.end()
    parts.append(re.escape(path_template[cursor:]))
    return re.compile("".join(parts)), names
