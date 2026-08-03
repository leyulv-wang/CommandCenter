from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.command_center.system_profiles import SystemProfile


class OpenAPIDocumentLoader:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        cache_ttl_seconds: int = 300,
        max_cache_entries: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(cache_ttl_seconds) is not int or cache_ttl_seconds <= 0:
            raise ValueError("cache TTL must be a positive integer")
        if type(max_cache_entries) is not int or max_cache_entries <= 0:
            raise ValueError("cache size must be a positive integer")
        self._owns_client = client is None
        self._client = client or httpx.Client()
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_cache_entries = max_cache_entries
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def __enter__(self) -> OpenAPIDocumentLoader:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def load(self, profile: SystemProfile) -> dict[str, Any]:
        profile_key = json.dumps(profile.model_dump(mode="json"), sort_keys=True)
        cache_key = (profile_key, str(profile.openapi_url))
        now = self._clock()
        cached = self._cache.get(cache_key)
        if cached is not None and now - cached[0] < self._cache_ttl_seconds:
            return cached[1]
        if cached is not None:
            self._cache.pop(cache_key, None)

        maximum_bytes = profile.limits.max_response_bytes
        with self._client.stream(
            "GET",
            str(profile.openapi_url),
            timeout=profile.limits.request_timeout_seconds,
        ) as response:
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";", 1)[0]
            if not _is_json_media_type(media_type.strip().lower()):
                raise ValueError("OpenAPI response Content-Type must be JSON")

            declared_length = response.headers.get("content-length")
            if declared_length is not None and int(declared_length) > maximum_bytes:
                raise ValueError("OpenAPI response exceeds maximum document size")

            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > maximum_bytes:
                    raise ValueError("OpenAPI response exceeds maximum document size")
                chunks.append(chunk)

        document = json.loads(b"".join(chunks))
        if not isinstance(document, dict):
            raise ValueError("OpenAPI document must be a JSON object")
        if len(self._cache) >= self._max_cache_entries:
            oldest_key = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest_key, None)
        self._cache[cache_key] = (now, document)
        return document


def _is_json_media_type(media_type: str) -> bool:
    return media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )
