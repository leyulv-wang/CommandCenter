from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from app.command_center.repository import CommandCenterRepository
from app.command_center.router import CreateRecordingRequest
from app.command_center.schemas import (
    APIAttributionAnalysis,
    FieldMappingAnalysis,
    SkillDefinition,
    TestPlan as SkillTestPlan,
    TraceSegmentation,
)
from app.command_center.system_profiles import ProfileLimits, SystemProfile, ToolPermission
from app.command_center.tool_catalog import ToolCatalog
from app.main import build_command_center_components


FP = "hmac-sha256:" + "a" * 64


class StubGraph:
    def invoke(self, state):
        return {"status": "unused"}


class ReadonlyAgents:
    def segment_trace(self, trace):
        return TraceSegmentation.model_validate(
            {
                "summary": "查询采购申请",
                "segments": [
                    {
                        "segment_id": "query_purchase",
                        "sequence": 1,
                        "classification": "business_action",
                        "summary": "查询采购申请列表与详情",
                        "source_ui_event_ids": [trace["ui_events"][0]["event_id"]],
                        "source_exchange_ids": [
                            item["exchange_id"] for item in trace["api_exchanges"]
                        ],
                    }
                ],
                "conclusive": True,
            }
        )

    def attribute_apis(self, segmentation, trace, catalog):
        exchanges = trace["api_exchanges"]
        return APIAttributionAnalysis.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "query_purchase",
                        "primary_tool_ids": [exchanges[0]["matched_tool_id"]],
                        "supporting_tool_ids": [
                            item["matched_tool_id"] for item in exchanges[1:]
                        ],
                        "primary_exchange_ids": [exchanges[0]["exchange_id"]],
                        "supporting_exchange_ids": [
                            item["exchange_id"] for item in exchanges[1:]
                        ],
                        "evidence_summary": "三次只读采购查询紧邻同一页面操作",
                    }
                ],
                "attributable": True,
            }
        )

    def map_fields(self, attribution, trace, catalog):
        return FieldMappingAnalysis.model_validate(
            {
                "mappings": [
                    {
                        "skill_input_name": "page_no",
                        "api_target": "query.pageNo",
                        "source_ui_event_ids": [trace["ui_events"][0]["event_id"]],
                        "source_exchange_ids": [trace["api_exchanges"][0]["exchange_id"]],
                        "transformation": "integer",
                        "evidence_summary": "列表请求使用页码查询参数",
                    }
                ],
                "compilable": True,
            }
        )

    def compile_skill(self, mapping, attribution, trace, catalog):
        return SkillDefinition.model_validate(
            {
                "skill_id": str(uuid4()),
                "version": 1,
                "name": "查询采购申请",
                "description": "按页查询采购申请",
                "status": "candidate",
                "trigger_examples": ["查询采购申请"],
                "source_recording_id": trace["recording_id"],
                "inputs": [
                    {
                        "name": "page_no",
                        "type": "integer",
                        "description": "页码",
                    }
                ],
                "outputs": [],
                "steps": [
                    {
                        "step_id": "list_purchase",
                        "name": "查询采购申请列表",
                        "tool_id": "yifeng_mes:listPurchaseApply",
                        "input_bindings": {"query.pageNo": "literal.page_no"},
                        "side_effect": "read",
                    }
                ],
                "success_conditions": [],
            }
        )

    def design_tests(self, skill):
        return SkillTestPlan.model_validate(
            {
                "skill_id": str(skill.skill_id),
                "skill_version": skill.version,
                "cases": [
                    {
                        "case_id": category,
                        "category": category,
                        "description": category,
                        "fixture": {},
                        "invocation": {"page_no": index},
                        "expected": {"required_paths": ["result.records"]},
                    }
                    for index, category in enumerate(
                        ("normal", "parameter_variation", "idempotency"), start=1
                    )
                ],
            }
        )


def mes_profile() -> SystemProfile:
    paths = [
        "/jeecg-boot/purchase/apply/list",
        "/jeecg-boot/purchase/apply/queryById",
        "/jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId",
    ]
    return SystemProfile(
        system_code="yifeng_mes",
        display_name="MES",
        allowed_hosts={"mes.test"},
        openapi_url="https://mes.test/api-docs",
        base_url="https://mes.test",
        api_path_prefix="/jeecg-boot/",
        credential_header="X-Access-Token",
        limits=ProfileLimits(
            request_timeout_seconds=10,
            max_response_bytes=100_000,
            max_requests_per_minute=30,
        ),
        value_capture_policy="fingerprint_by_default",
        sensitive_field_patterns=["(?i)token"],
        tool_permissions=[
            ToolPermission(method="GET", path=path, side_effect="read")
            for path in paths
        ],
    )


def swagger_document():
    return {
        "swagger": "2.0",
        "paths": {
            "/jeecg-boot/purchase/apply/list": {
                "get": {
                    "operationId": "listPurchaseApply",
                    "parameters": [
                        {"name": "pageNo", "in": "query", "type": "integer"}
                    ],
                }
            },
            "/jeecg-boot/purchase/apply/queryById": {
                "get": {"operationId": "queryPurchaseApplyById"}
            },
            "/jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId": {
                "get": {"operationId": "queryPurchaseApplyDetailByMainId"}
            },
        },
    }


def network_event(sequence, path):
    now = datetime.now(UTC)
    return {
        "exchange_id": str(uuid4()),
        "client_sequence": sequence,
        "started_at": now,
        "completed_at": now,
        "method": "GET",
        "path_template": path,
        "query_parameter_names": ["pageNo"] if path.endswith("/list") else [],
        "response_status": 200,
        "endpoint_fingerprint": FP,
    }


def test_record_query_generate_and_verify_candidate(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api-docs":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json=swagger_document(),
            )
        assert request.headers["X-Access-Token"] == "ephemeral-token"
        return httpx.Response(200, json={"result": {"records": [], "total": 0}})

    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    components = build_command_center_components(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        profiles={"yifeng_mes": mes_profile()},
        repository=repository,
        agents=ReadonlyAgents(),
        local_catalog=ToolCatalog([]),
        local_tester=object(),
        execution_graph=StubGraph(),
    )
    service = components.service
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询采购申请",
            source_system="yifeng_mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    started = service.start_extension_recording(created["recording_id"])
    token = started["recording_token"]
    recording_id = created["recording_id"]
    paths = list(swagger_document()["paths"])
    service.put_extension_credential(
        recording_id,
        "X-Access-Token",
        SecretStr("ephemeral-token"),
        token,
    )
    service.ingest_extension_events(
        recording_id,
        {
            "batch_id": str(uuid4()),
            "recording_id": recording_id,
            "events": [
                {
                    "event_id": str(uuid4()),
                    "client_sequence": 1,
                    "occurred_at": datetime.now(UTC),
                    "event_type": "click",
                    "page": {
                        "origin": "https://mes.test",
                        "path": "/purchase/apply",
                        "fingerprint": FP,
                    },
                },
                *(network_event(index, path) for index, path in enumerate(paths, 2)),
            ],
        },
        token,
    )
    result = service.stop_extension_recording(recording_id, token)

    assert result["status"] == "verified_candidate"
    assert result["learning_result"]["candidate_skill"]["name"] == "查询采购申请"
    assert repository.list_published_skills() == []
    assert len(repository.list_verified_candidates()) == 1
    assert components.credential_vault.headers_for(UUID(str(recording_id))) == {}
    assert sum(request.url.path.endswith("/list") for request in requests) == 4
