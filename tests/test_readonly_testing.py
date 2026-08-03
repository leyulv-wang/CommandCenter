from uuid import uuid4

import httpx

from app.command_center.readonly_testing import ReadOnlySkillTestService
from app.command_center.schemas import SkillDefinition
from app.command_center.testing import SkillRunner
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition
from app.command_center.tool_executor import ToolExecutor
from tests.test_command_center_schemas import valid_skill_payload


def query_catalog(*, side_effect="read", credential=True):
    return ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:listPurchaseApply",
                system_code="mes",
                operation_id="listPurchaseApply",
                method="GET",
                base_url="https://mes.test",
                path_template="/api/apply/list",
                content_type=None,
                side_effect=side_effect,
                credential_header="X-Access-Token" if credential else None,
            )
        ]
    )


def query_skill(*, step_side_effect="read") -> SkillDefinition:
    payload = valid_skill_payload()
    payload["skill_id"] = str(uuid4())
    payload["name"] = "查询采购申请"
    payload["steps"] = [
        {
            "step_id": "query",
            "name": "查询采购申请",
            "tool_id": "mes:listPurchaseApply",
            "input_bindings": {"query.applyNo": "literal.apply_no"},
            "side_effect": step_side_effect,
            **(
                {"idempotency_key_template": "fixed"}
                if step_side_effect == "write"
                else {}
            ),
        }
    ]
    return SkillDefinition.model_validate(payload)


def service(catalog, handler, *, credentials=None, cleanup=lambda: None):
    executor = ToolExecutor(
        catalog,
        httpx.Client(transport=httpx.MockTransport(handler)),
        credential_provider=lambda _: credentials or {},
    )
    return ReadOnlySkillTestService(
        catalog=catalog,
        runner=SkillRunner(executor),
        credential_cleanup=cleanup,
    )


def test_readonly_service_runs_query_variation_and_response_contract():
    observed = []

    def handler(request):
        observed.append(dict(request.url.params))
        return httpx.Response(200, json={"result": {"records": [], "total": 0}})

    result = service(
        query_catalog(), handler, credentials={"X-Access-Token": "private"}
    ).run(
        query_skill(),
        {
            "category": "parameter_variation",
            "invocation": {"apply_no": "CGSQ002"},
            "expected": {"required_paths": ["result.records", "result.total"]},
        },
    )

    assert result["status"] == "passed"
    assert observed == [{"applyNo": "CGSQ002"}]


def test_readonly_service_repeats_identical_query_without_side_effect():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"result": {"records": []}})

    result = service(
        query_catalog(), handler, credentials={"X-Access-Token": "private"}
    ).run(
        query_skill(),
        {"category": "idempotency", "invocation": {"apply_no": "CGSQ001"}},
    )

    assert result["status"] == "passed"
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert all(not item["side_effect"]["occurred"] for item in result["step_results"])


def test_readonly_service_rejects_write_tool_before_request():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = service(query_catalog(side_effect="write", credential=False), handler).run(
        query_skill(), {"category": "normal", "invocation": {"apply_no": "x"}}
    )

    assert result["status"] == "failed"
    assert calls == 0


def test_readonly_service_reports_missing_credential_and_always_cleans_up():
    cleaned = []
    result = service(
        query_catalog(),
        lambda request: httpx.Response(200, json={}),
        cleanup=lambda: cleaned.append(True),
    ).run(
        query_skill(), {"category": "normal", "invocation": {"apply_no": "x"}}
    )

    assert result["status"] == "failed"
    assert result["step_results"][0]["error"]["code"] == "MissingCredential"
    assert cleaned == [True]


def test_readonly_service_rejects_missing_response_contract():
    result = service(
        query_catalog(),
        lambda request: httpx.Response(200, json={"result": {}}),
        credentials={"X-Access-Token": "private"},
    ).run(
        query_skill(),
        {
            "category": "normal",
            "invocation": {"apply_no": "x"},
            "expected": {"required_paths": ["result.records"]},
        },
    )

    assert result["status"] == "failed"
    assert result["verification"]["summary"] == "response contract is incomplete"
