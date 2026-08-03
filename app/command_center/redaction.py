from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from typing import Any


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_MARKERS = frozenset(
    {
        "accesstoken",
        "apikey",
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


def _is_sensitive_path(path: tuple[str, ...]) -> bool:
    normalized_path = "".join(path)
    return any(marker in normalized_path for marker in _SENSITIVE_KEY_MARKERS)


class TraceRedactor:
    """Apply deterministic safety limits before data enters a trace or prompt."""

    def __init__(
        self,
        *,
        fingerprint_key: bytes,
        max_depth: int = 8,
        max_array_items: int = 100,
        max_mapping_items: int = 100,
        max_sensitive_paths: int = 100,
        max_string_length: int = 4_096,
    ) -> None:
        if not isinstance(fingerprint_key, bytes) or not fingerprint_key:
            raise ValueError("fingerprint_key must be non-empty bytes")
        limits = (
            max_depth,
            max_array_items,
            max_mapping_items,
            max_sensitive_paths,
            max_string_length,
        )
        if any(type(limit) is not int or limit <= 0 for limit in limits):
            raise ValueError("redaction limits must be positive integers")
        self._fingerprint_key = fingerprint_key
        self._max_depth = max_depth
        self._max_array_items = max_array_items
        self._max_mapping_items = max_mapping_items
        self._max_sensitive_paths = max_sensitive_paths
        self._max_string_length = max_string_length

    def fingerprint(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("fingerprint value must be a string")
        bounded_value = value[: self._max_string_length]
        return hmac.new(
            self._fingerprint_key,
            bounded_value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def redact_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        self._validate_mapping_size(headers)
        sanitized: dict[str, str] = {}
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise TypeError("header names and values must be strings")
            self._validate_mapping_key(name)
            normalized_name = _normalized_key(name)
            if _is_sensitive_path((normalized_name,)):
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
            self._validate_mapping_size(value)
            result: dict[Any, Any] = {}
            for key, child in value.items():
                child_depth = depth + 1
                if child_depth > self._max_depth:
                    raise ValueError("payload exceeds configured maximum depth")
                if not isinstance(key, str):
                    raise TypeError("mapping keys must be strings")
                self._validate_mapping_key(key)
                normalized = _normalized_key(key)
                child_path = (*path, normalized)
                if _is_sensitive_path(child_path):
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

    def _normalize_sensitive_paths(
        self,
        paths: set[str] | frozenset[str],
    ) -> frozenset[tuple[str, ...]]:
        if len(paths) > self._max_sensitive_paths:
            raise ValueError("sensitive paths exceed configured maximum items")
        normalized: set[tuple[str, ...]] = set()
        for path in paths:
            if not isinstance(path, str):
                raise TypeError("sensitive paths must be strings")
            self._validate_sensitive_path(path)
            parts = tuple(
                normalized_part
                for part in path.split(".")
                if (normalized_part := _normalized_key(part))
            )
            if parts:
                normalized.add(parts)
        return frozenset(normalized)

    def _validate_mapping_key(self, key: str) -> None:
        if len(key) > self._max_string_length:
            raise ValueError("mapping key exceeds configured maximum length")

    def _validate_mapping_size(self, value: Mapping[Any, Any]) -> None:
        if len(value) > self._max_mapping_items:
            raise ValueError("mapping exceeds configured maximum items")

    def _validate_sensitive_path(self, path: str) -> None:
        if not path:
            return
        segment_length = 0
        segment_count = 1
        if segment_count > self._max_depth:
            raise ValueError("sensitive path exceeds configured maximum depth")
        for character in path:
            if character == ".":
                segment_count += 1
                segment_length = 0
                if segment_count > self._max_depth:
                    raise ValueError("sensitive path exceeds configured maximum depth")
            else:
                segment_length += 1
                if segment_length > self._max_string_length:
                    raise ValueError(
                        "sensitive path segment exceeds configured maximum length"
                    )

    @staticmethod
    def _path_is_sensitive(
        path: tuple[str, ...],
        sensitive_paths: frozenset[tuple[str, ...]],
    ) -> bool:
        return path in sensitive_paths or (path and (path[-1],) in sensitive_paths)
