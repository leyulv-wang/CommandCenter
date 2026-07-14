import httpx

from app.adapters.http_flow import HttpExternalSubmitter


def test_http_submitter_posts_form_payload_and_returns_external_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["content_type"] = request.headers["content-type"]
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"success": True, "data": {"id": "REAL-001"}})

    submitter = HttpExternalSubmitter(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = submitter.submit(
        endpoint_type="custom_url",
        method="POST",
        url="http://example.test/addorder",
        payload={"docOperator": '{"Id":"u1"}', "formValues": '{"orderNo":"001"}'},
        content_type="form",
        timeout_seconds=5,
    )

    assert result["ok"] is True
    assert result["ticket_id"] == "REAL-001"
    assert result["submit_mode"] == "http"
    assert result["external_response"] == {"success": True, "data": {"id": "REAL-001"}}
    assert captured["method"] == "POST"
    assert "application/x-www-form-urlencoded" in captured["content_type"]
    assert "docOperator=" in captured["body"]
