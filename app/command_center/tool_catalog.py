from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


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
        )


class ToolCatalog:
    def __init__(self, tools: list[ToolDefinition]):
        self._tools = {tool.tool_id: tool for tool in tools}
        canonical = json.dumps(
            [tool.__dict__ for tool in tools],
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
                    content = operation.get("requestBody", {}).get("content", {})
                    content_type = next(iter(content), None)
                    tools.append(
                        ToolDefinition(
                            tool_id=f"{system_code}:{operation_id}",
                            system_code=system_code,
                            operation_id=operation_id,
                            method=method.upper(),
                            base_url=base_urls[system_code].rstrip("/"),
                            path_template=path,
                            content_type=content_type,
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
