from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


_SEMANTIC_TEXT_LIMIT = 320
_TARGET_FIELDS = (
    "system_code",
    "tab_id",
    "role",
    "accessible_name",
    "label",
    "input_type",
    "element_kind",
)


def project_trace_for_analysis(trace: Any) -> dict[str, Any]:
    """Build a bounded model input while leaving the audit trace untouched."""
    source = _payload(trace)
    return _compact(
        {
            "objective": source.get("objective"),
            "ui_events": [_project_ui_event(item) for item in source.get("ui_events", [])],
            "api_exchanges": [
                _project_api_exchange(item)
                for item in source.get("api_exchanges", [])
            ],
            "page_mutations": [
                _project_page_mutation(item)
                for item in source.get("page_mutations", [])
            ],
        }
    )


def _project_ui_event(item: dict[str, Any]) -> dict[str, Any]:
    target = item.get("target") or {}
    return _compact(
        {
            "event_id": item.get("event_id"),
            "sequence": item.get("sequence"),
            "page_path": _url_path(item.get("page_url")),
            "action_type": item.get("action_type"),
            "target": {
                key: _bounded_text(target.get(key))
                for key in _TARGET_FIELDS
                if target.get(key) is not None
            },
            "value_ref": item.get("value_ref"),
        }
    )


def _project_api_exchange(item: dict[str, Any]) -> dict[str, Any]:
    request = item.get("request_body") or {}
    return _compact(
        {
            "exchange_id": item.get("exchange_id"),
            "sequence": item.get("sequence"),
            "system_code": item.get("system_code"),
            "method": item.get("method"),
            "path": item.get("path"),
            "request_body": {
                "query_parameter_names": request.get("query_parameter_names"),
                "query_parameter_fingerprints": request.get(
                    "query_parameter_fingerprints"
                ),
                "body_field_fingerprints": request.get(
                    "body_field_fingerprints"
                ),
            },
            "response_status": item.get("response_status"),
            "matched_tool_id": item.get("matched_tool_id"),
            "match_status": item.get("match_status"),
        }
    )


def _project_page_mutation(item: dict[str, Any]) -> dict[str, Any]:
    page = item.get("page") or {}
    return _compact(
        {
            "mutation_id": item.get("mutation_id"),
            "client_sequence": item.get("client_sequence"),
            "system_code": item.get("system_code"),
            "tab_id": item.get("tab_id"),
            "page_path": _url_path(page.get("url")),
            "mutation_type": item.get("mutation_type"),
            "changed_control_count": len(
                item.get("changed_control_fingerprints") or []
            ),
            "before_fingerprint": item.get("before_fingerprint"),
            "after_fingerprint": item.get("after_fingerprint"),
        }
    )


def _url_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    parsed = urlsplit(value)
    if parsed.path:
        return parsed.path
    return "/" if parsed.scheme and parsed.netloc else _bounded_text(value)


def _bounded_text(value: Any) -> Any:
    if not isinstance(value, str) or len(value) <= _SEMANTIC_TEXT_LIMIT:
        return value
    return value[:_SEMANTIC_TEXT_LIMIT]


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: compacted
            for key, item in value.items()
            if (compacted := _compact(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [compacted for item in value if (compacted := _compact(item)) is not None]
    return value


def _payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    raise TypeError("analysis trace must be a mapping or Pydantic model")
