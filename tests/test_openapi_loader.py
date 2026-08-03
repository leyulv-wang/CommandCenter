import httpx
import pytest

from app.command_center.openapi_loader import OpenAPIDocumentLoader
from app.command_center.system_profiles import SystemProfile


def profile_for_url(
    openapi_url: str = "http://mes.example.test/v2/api-docs",
    *,
    max_response_bytes: int = 1_024,
) -> SystemProfile:
    return SystemProfile.model_validate(
        {
            "system_code": "generic_system",
            "display_name": "Generic system",
            "allowed_hosts": ["mes.example.test"],
            "openapi_url": openapi_url,
            "base_url": "http://mes.example.test",
            "api_path_prefix": "/api/",
            "credential_header": "X-Access-Token",
            "limits": {
                "request_timeout_seconds": 7,
                "max_response_bytes": max_response_bytes,
                "max_requests_per_minute": 30,
            },
            "value_capture_policy": "fingerprint_by_default",
            "sensitive_field_patterns": ["token"],
            "tool_permissions": [],
        }
    )


def test_loader_accepts_json_content_type_and_applies_profile_timeout():
    observed_timeout = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_timeout
        observed_timeout = request.extensions["timeout"]
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            json={"swagger": "2.0", "paths": {}},
        )

    loader = OpenAPIDocumentLoader(
        httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert loader.load(profile_for_url()) == {"swagger": "2.0", "paths": {}}
    assert observed_timeout == {
        "connect": 7.0,
        "read": 7.0,
        "write": 7.0,
        "pool": 7.0,
    }


def test_loader_rejects_non_json_content_type():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="not an OpenAPI document",
            )
        )
    )

    with pytest.raises(ValueError, match="Content-Type"):
        OpenAPIDocumentLoader(client).load(profile_for_url())


def test_loader_rejects_unsuccessful_status():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                headers={"Content-Type": "application/json"},
                json={"error": "unavailable"},
            )
        )
    )

    with pytest.raises(httpx.HTTPStatusError):
        OpenAPIDocumentLoader(client).load(profile_for_url())


def test_loader_rejects_document_larger_than_profile_limit():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b'{"swagger":"2.0","paths":{}}',
            )
        )
    )

    with pytest.raises(ValueError, match="maximum document size"):
        OpenAPIDocumentLoader(client).load(profile_for_url(max_response_bytes=8))


def test_loader_caches_by_profile_and_openapi_url():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"swagger": "2.0", "source": str(request.url)},
        )

    loader = OpenAPIDocumentLoader(
        httpx.Client(transport=httpx.MockTransport(handler))
    )
    first_profile = profile_for_url()
    other_profile = profile_for_url("http://mes.example.test/openapi/other.json")

    first = loader.load(first_profile)
    cached = loader.load(first_profile)
    other = loader.load(other_profile)

    assert cached is first
    assert other != first
    assert request_count == 2


def test_loader_context_manager_closes_internally_created_client():
    with OpenAPIDocumentLoader() as loader:
        pass

    with pytest.raises(RuntimeError, match="closed"):
        loader.load(profile_for_url())


def test_loader_close_does_not_close_injected_client():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"still": "open"})
        )
    )
    loader = OpenAPIDocumentLoader(client)

    loader.close()

    assert client.get("http://mes.example.test/health").json() == {"still": "open"}
    client.close()


def test_loader_cache_expires_after_bounded_ttl():
    now = [0.0]
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"swagger": "2.0", "revision": request_count})

    loader = OpenAPIDocumentLoader(
        httpx.Client(transport=httpx.MockTransport(handler)),
        cache_ttl_seconds=5,
        clock=lambda: now[0],
    )
    first = loader.load(profile_for_url())
    now[0] = 4.0
    assert loader.load(profile_for_url()) is first
    now[0] = 5.0

    assert loader.load(profile_for_url())["revision"] == 2
