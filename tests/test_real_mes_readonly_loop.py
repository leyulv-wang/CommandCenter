from datetime import UTC, datetime
import json
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from app.command_center.repository import CommandCenterRepository
from app.command_center.langchain_purchase_agents import LangChainPurchaseAgents
from app.command_center.purchase_tracking_graph import (
    PurchaseTrackingDependencies,
    build_purchase_tracking_graph,
)
from app.command_center.readonly_testing import ReadOnlySkillTestService
from app.command_center.router import CreateRecordingRequest
from app.command_center.schemas import (
    APIAttributionAnalysis,
    FieldMappingAnalysis,
    SkillDefinition,
    StepResult,
    TestPlan as SkillTestPlan,
    TraceSegmentation,
)
from app.command_center.system_profiles import ProfileLimits, SystemProfile, ToolPermission
from app.command_center.testing import SkillRunner
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition, ToolParameter
from app.command_center.tool_executor import ToolExecutor
from app.command_center.service import CommandCenterService
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


def test_local_test_system_outage_does_not_block_readonly_observer(tmp_path):
    def unavailable_local_system(_request):
        return httpx.Response(502, json={"detail": "test system unavailable"})

    components = build_command_center_components(
        client=httpx.Client(transport=httpx.MockTransport(unavailable_local_system)),
        profiles={"yifeng_mes": mes_profile()},
        repository=CommandCenterRepository(
            f"sqlite:///{tmp_path / 'degraded-center.sqlite3'}"
        ),
        agents=ReadonlyAgents(),
        local_tester=object(),
        execution_graph=StubGraph(),
    )

    assert components.service.list_skills() == []


def task_bound_readonly_skill() -> SkillDefinition:
    return SkillDefinition.model_validate(
        {
            "skill_id": str(uuid4()),
            "version": 1,
            "name": "查询部门申请",
            "description": "按任务中的部门查询申请",
            "status": "testing",
            "trigger_examples": ["查询采购部申请"],
            "source_recording_id": str(uuid4()),
            "inputs": [
                {
                    "name": "department",
                    "type": "string",
                    "description": "部门",
                    "required": True,
                }
            ],
            "outputs": [],
            "steps": [
                {
                    "step_id": "query",
                    "name": "查询",
                    "tool_id": "mes:list",
                    "input_bindings": {
                        "query.department": "task.content.department"
                    },
                    "side_effect": "read",
                }
            ],
            "success_conditions": [],
        }
    )


def readonly_catalog() -> ToolCatalog:
    return ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:list",
                system_code="mes",
                operation_id="list",
                method="GET",
                base_url="https://mes.test",
                path_template="/list",
                content_type=None,
                side_effect="read",
            )
        ]
    )


class CapturingReadExecutor:
    def __init__(self):
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        now = datetime.now(UTC)
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status="succeeded",
            started_at=now,
            ended_at=now,
            normalized_output={"result": {"records": []}},
            side_effect={"occurred": False},
        )


def test_readonly_test_returns_structured_failure_before_tool_for_missing_task_binding():
    executor = CapturingReadExecutor()
    tester = ReadOnlySkillTestService(
        catalog=readonly_catalog(),
        runner=SkillRunner(executor),
    )

    result = tester.run(
        task_bound_readonly_skill(),
        {
            "category": "normal",
            "fixture": {
                "source_task": {
                    "task_id": "test",
                    "system_code": "mes",
                    "content": {},
                }
            },
            "invocation": {},
        },
    )

    assert result["status"] == "failed"
    assert result["verification"]["summary"] == (
        "test data does not satisfy Skill bindings"
    )
    assert executor.commands == []


def test_readonly_test_executes_when_task_binding_is_present():
    executor = CapturingReadExecutor()
    tester = ReadOnlySkillTestService(
        catalog=readonly_catalog(),
        runner=SkillRunner(executor),
    )

    result = tester.run(
        task_bound_readonly_skill(),
        {
            "category": "normal",
            "fixture": {
                "source_task": {
                    "task_id": "test",
                    "system_code": "mes",
                    "content": {"department": "采购部"},
                }
            },
            "invocation": {},
        },
    )

    assert result["status"] == "passed"
    assert executor.commands[0].arguments == {"query": {"department": "采购部"}}


class PurchaseChainAgent:
    def __init__(self, name, tools):
        self.name = name
        self.tools = {tool.metadata.get("tool_id"): tool for tool in tools}

    def invoke(self, invocation, config=None):
        payload = json.loads(invocation["messages"][0]["content"])
        if self.name == "purchase_scope":
            application = payload["trusted_application"]
            return {
                "structured_response": {
                    "goal": payload["goal"],
                    "application": application,
                    "application_id": application["id"],
                    "application_number": application["applyNo"],
                }
            }
        if self.name == "purchase_trace":
            application_number = payload["scope"]["application_number"]
            order_output = json.loads(
                self.tools["yifeng_mes:purchase_orders"].invoke(
                    {"query": {"sourceCode": application_number}}
                )
            )
            orders = order_output["output"]["result"]["records"]
            if not orders:
                return {
                    "structured_response": {
                        "status": "business_pending",
                        "summary": "采购申请尚未生成采购订单",
                        "evidence_step_ids": [order_output["step_id"]],
                    }
                }
            receipt_output = json.loads(
                self.tools["yifeng_mes:receiving_records"].invoke(
                    {"query": {"orderNumber": orders[0]["orderNumber"]}}
                )
            )
            return {
                "structured_response": {
                    "status": "complete",
                    "summary": "已查询采购订单和收货记录",
                    "evidence_step_ids": [
                        order_output["step_id"],
                        receipt_output["step_id"],
                    ],
                }
            }

        scope = payload["scope"]
        step_results = payload["step_results"]
        orders = step_results[0]["normalized_output"]["result"]["records"]
        receipts = (
            step_results[1]["normalized_output"]["result"]["records"]
            if len(step_results) > 1
            else []
        )
        status = "complete" if orders and receipts else "business_pending"
        return {
            "structured_response": {
                "status": status,
                "summary": (
                    "采购订单已生成并找到收货记录"
                    if status == "complete"
                    else "采购申请尚未生成采购订单"
                ),
                "stages": [
                    {
                        "stage": "application",
                        "status": "completed",
                        "summary": "采购申请已找到",
                        "record_count": 1,
                        "records": [scope["application"]],
                        "evidence_step_ids": [],
                    },
                    {
                        "stage": "order",
                        "status": "completed" if orders else "not_found",
                        "summary": "已找到采购订单" if orders else "尚未生成采购订单",
                        "record_count": len(orders),
                        "records": orders,
                        "evidence_step_ids": ["tool_01"],
                    },
                    {
                        "stage": "receiving",
                        "status": "completed" if receipts else "pending",
                        "summary": "已找到收货记录" if receipts else "尚未收货",
                        "record_count": len(receipts),
                        "records": receipts,
                        "evidence_step_ids": ["tool_02"] if receipts else [],
                    },
                ],
            }
        }


def purchase_chain_agent_factory(*, model, tools, system_prompt, response_format, name):
    return PurchaseChainAgent(name, tools)


def purchase_chain_tool(tool_id, path, parameter):
    return ToolDefinition(
        tool_id=tool_id,
        system_code="yifeng_mes",
        operation_id=tool_id.rsplit(":", 1)[-1],
        method="GET",
        base_url="https://mes.test",
        path_template=path,
        content_type=None,
        description=tool_id,
        side_effect="read",
        credential_header="X-Access-Token",
        parameters=(
            ToolParameter(
                name=parameter,
                location="query",
                type="string",
                required=True,
                description=parameter,
            ),
        ),
    )


def purchase_progress_service(tmp_path, handler):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'progress.sqlite3'}")
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "user_request": "查询孟明佳的采购申请",
            "status": "succeeded",
            "final_response": {
                "outputs": {
                    "query": {
                        "result": {
                            "records": [
                                {
                                    "id": "application-1",
                                    "applyNo": "CGSQ01",
                                    "applyBy": "孟明佳",
                                }
                            ]
                        }
                    }
                }
            },
        },
    )
    catalog = ToolCatalog(
        [
            purchase_chain_tool(
                "yifeng_mes:purchase_orders", "/orders", "sourceCode"
            ),
            purchase_chain_tool(
                "yifeng_mes:receiving_records", "/receiving", "orderNumber"
            ),
        ]
    )
    executor = ToolExecutor(
        catalog,
        httpx.Client(transport=httpx.MockTransport(handler)),
        credential_provider=lambda _: {"X-Access-Token": "readonly-token"},
    )

    def graph_factory():
        return build_purchase_tracking_graph(
            PurchaseTrackingDependencies(
                agents=LangChainPurchaseAgents(
                    model=object(),
                    tools=list(catalog.definitions()),
                    executor=executor,
                    agent_factory=purchase_chain_agent_factory,
                )
            )
        )

    service = CommandCenterService(
        repository=repository,
        recorder=object(),
        learning_graph=StubGraph(),
        execution_graph=StubGraph(),
        purchase_tracking_graph_factory=graph_factory,
    )
    return service, parent_run_id


def test_selected_application_traces_order_and_receiving_without_user_internal_ids(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["X-Access-Token"] == "readonly-token"
        if request.url.path == "/orders":
            assert request.url.params["sourceCode"] == "CGSQ01"
            return httpx.Response(
                200,
                json={
                    "result": {
                        "records": [
                            {"id": "order-1", "orderNumber": "CGDD01"}
                        ]
                    }
                },
            )
        assert request.url.path == "/receiving"
        assert request.url.params["orderNumber"] == "CGDD01"
        return httpx.Response(
            200,
            json={
                "result": {
                    "records": [
                        {"id": "receipt-1", "orderNumber": "CGDD01"},
                        {"id": "receipt-2", "orderNumber": "CGDD01"},
                    ]
                }
            },
        )

    service, parent_run_id = purchase_progress_service(tmp_path, handler)

    progress = service.create_purchase_progress_run(parent_run_id, "application-1")

    assert progress["status"] == "succeeded"
    assert progress["final_response"]["progress"]["status"] == "complete"
    assert progress["final_response"]["progress"]["stages"][2]["record_count"] == 2
    assert [request.url.path for request in requests] == ["/orders", "/receiving"]


def test_purchase_trace_stops_normally_when_order_does_not_exist(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"result": {"records": []}})

    service, parent_run_id = purchase_progress_service(tmp_path, handler)

    progress = service.create_purchase_progress_run(parent_run_id, "application-1")

    assert progress["status"] == "succeeded"
    assert progress["final_response"]["progress"]["status"] == "business_pending"
    assert [request.url.path for request in requests] == ["/orders"]
