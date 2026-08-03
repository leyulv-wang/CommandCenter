from __future__ import annotations

import json
from typing import Any

import httpx

from app.command_center.system_profiles import SystemProfile


class OpenAPIDocumentLoader:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def load(self, profile: SystemProfile) -> dict[str, Any]:
        profile_key = json.dumps(profile.model_dump(mode="json"), sort_keys=True)
        cache_key = (profile_key, str(profile.openapi_url))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

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
        self._cache[cache_key] = document
        return document


def _is_json_media_type(media_type: str) -> bool:
    return media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )
