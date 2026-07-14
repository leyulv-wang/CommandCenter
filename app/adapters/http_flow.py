from typing import Any, Literal

import httpx

from app.forms.schemas import ContentType, EndpointType


class HttpExternalSubmitter:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client()

    def submit(
        self,
        endpoint_type: EndpointType,
        method: str,
        url: str,
        payload: dict[str, Any],
        content_type: ContentType,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        try:
            response = self._request(method, url, payload, content_type, timeout_seconds)
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "ticket_id": "",
                "endpoint_type": endpoint_type,
                "submit_mode": "http",
                "payload": payload,
                "error": str(exc),
                "external_response": None,
            }

        external_response = _parse_response(response)
        ok = 200 <= response.status_code < 300
        return {
            "ok": ok,
            "ticket_id": _extract_ticket_id(external_response),
            "endpoint_type": endpoint_type,
            "submit_mode": "http",
            "payload": payload,
            "error": "" if ok else str(external_response),
            "external_response": external_response,
            "status_code": response.status_code,
        }

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        content_type: ContentType,
        timeout_seconds: int,
    ) -> httpx.Response:
        if content_type == "json":
            return self.client.request(
                method=method,
                url=url,
                json=payload,
                timeout=timeout_seconds,
            )
        return self.client.request(
            method=method,
            url=url,
            data=payload,
            timeout=timeout_seconds,
        )


def _parse_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _extract_ticket_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("ticket_id", "ticketId", "id", "fd_id"):
            if key in value and value[key] is not None:
                return str(value[key])
        data = value.get("data")
        if isinstance(data, dict):
            for key in ("ticket_id", "ticketId", "id", "fd_id"):
                if key in data and data[key] is not None:
                    return str(data[key])
    return ""
