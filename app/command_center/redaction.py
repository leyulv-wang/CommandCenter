from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from typing import Any


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_MARKERS = frozenset(
    {
        "authorization",
        "captcha",
        "cookie",
        "filecontent",
        "localstorage",
        "password",
        "xaccesstoken",
    }
)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


class TraceRedactor:
    """Apply deterministic safety limits before data enters a trace or prompt."""

    def __init__(
        self,
        *,
        fingerprint_key: bytes,
        max_depth: int = 8,
        max_array_items: int = 100,
        max_string_length: int = 4_096,
    ) -> None:
        if not isinstance(fingerprint_key, bytes) or not fingerprint_key:
            raise ValueError("fingerprint_key must be non-empty bytes")
        if max_depth < 0 or max_array_items < 0 or max_string_length < 0:
            raise ValueError("redaction limits must be non-negative")
        self._fingerprint_key = fingerprint_key
        self._max_depth = max_depth
        self._max_array_items = max_array_items
        self._max_string_length = max_string_length

    def fingerprint(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("fingerprint value must be a string")
        return hmac.new(
            self._fingerprint_key,
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def redact_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        sanitized: dict[str, str] = {}
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise TypeError("header names and values must be strings")
            if _is_sensitive_key(name):
                continue
            sanitized[name] = value[: self._max_string_length]
        return sanitized

    def redact_payload(
        self,
        payload: Any,
        *,
        sensitive_paths: set[str] | frozenset[str] | None = None,
    ) -> Any:
        paths = self._normalize_sensitive_paths(sensitive_paths or set())
        return self._sanitize(payload, depth=0, path=(), sensitive_paths=paths)

    def _sanitize(
        self,
        value: Any,
        *,
        depth: int,
        path: tuple[str, ...],
        sensitive_paths: frozenset[tuple[str, ...]],
    ) -> Any:
        if depth > self._max_depth:
            raise ValueError("payload exceeds configured maximum depth")

        if isinstance(value, Mapping):
            result: dict[Any, Any] = {}
            for key, child in value.items():
                normalized = _normalized_key(key) if isinstance(key, str) else ""
                child_path = (*path, normalized)
                if isinstance(key, str) and _is_sensitive_key(key):
                    result[key] = _REDACTED
                elif self._path_is_sensitive(child_path, sensitive_paths):
                    result[key] = {"fingerprint": self._fingerprint_value(child)}
                else:
                    result[key] = self._sanitize(
                        child,
                        depth=depth + 1,
                        path=child_path,
                        sensitive_paths=sensitive_paths,
                    )
            return result

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [
                self._sanitize(
                    item,
                    depth=depth + 1,
                    path=path,
                    sensitive_paths=sensitive_paths,
                )
                for item in value[: self._max_array_items]
            ]

        if isinstance(value, str):
            return value[: self._max_string_length]
        if isinstance(value, (bytes, bytearray, memoryview)):
            return _REDACTED
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[UNSUPPORTED]"

    def _fingerprint_value(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("fingerprinted payload values must be strings")
        return self.fingerprint(value)

    @staticmethod
    def _normalize_sensitive_paths(
        paths: set[str] | frozenset[str],
    ) -> frozenset[tuple[str, ...]]:
        normalized: set[tuple[str, ...]] = set()
        for path in paths:
            if not isinstance(path, str):
                raise TypeError("sensitive paths must be strings")
            parts = tuple(
                normalized_part
                for part in path.split(".")
                if (normalized_part := _normalized_key(part))
            )
            if parts:
                normalized.add(parts)
        return frozenset(normalized)

    @staticmethod
    def _path_is_sensitive(
        path: tuple[str, ...],
        sensitive_paths: frozenset[tuple[str, ...]],
    ) -> bool:
        return path in sensitive_paths or (path and (path[-1],) in sensitive_paths)
