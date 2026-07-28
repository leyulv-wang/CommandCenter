from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.command_center.execution_graph import (
    ExecutionDependencies,
    LocalBusinessReader,
    build_execution_graph,
)
from app.command_center.learning_graph import LearningDependencies, build_learning_graph
from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import (
    DemonstrationAnalysis,
    SkillDefinition,
    TaskMatchDecision,
    TestPlan as SkillTestPlan,
    VerificationResult,
)
from app.command_center.testing import HarmlessTestService, LocalFixtureService, SkillRunner
from app.command_center.tool_catalog import ToolCatalog
from app.command_center.tool_executor import ToolExecutor
from external_systems.common import create_external_app


class FastAPITransport(httpx.BaseTransport):
    def __init__(self, client: TestClient):
        self.client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.client.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.read(),
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            headers=dict(response.headers),
            content=response.content,
            request=request,
        )


class DeterministicAgents:
    def analyze_demonstration(self, trace, catalog):
        return DemonstrationAnalysis(
            summary="创建采购申请",
            business_actions=[],
            compilable=True,
        )

    def compile_skill(self, analysis, trace, catalog):
        return SkillDefinition(
            skill_id=uuid4(),
            version=1,
            name="创建采购申请",
            description="根据员工输入创建一条采购申请",
            status="candidate",
            trigger_examples=["采购10箱打印纸用于会议"],
            source_recording_id=uuid4(),
            inputs=[],
            outputs=[],
            steps=[
                {
                    "step_id": "create_purchase",
                    "name": "创建采购申请",
                    "tool_id": (
                        "connected_system:"
                        "create_purchase_request_api_purchase_requests_post"
                    ),
                    "input_bindings": {
                        "body.item_name": "literal.item_name",
                        "body.quantity": "literal.quantity",
                        "body.reason": "literal.reason",
                    },
                    "side_effect": "write",
                    "idempotency_key_template": "deterministic",
                }
            ],
            success_conditions=[],
        )

    def design_tests(self, skill):
        cases = []
        for index, category in enumerate(
            ("normal", "parameter_variation", "idempotency"),
            start=1,
        ):
            cases.append(
                {
                    "case_id": category,
                    "category": category,
                    "description": category,
                    "fixture": {
                        "source_task": {
                            "task_id": f"purchase-test-{index}",
                            "content": {},
                        }
                    },
                    "invocation": {
                        "item_name": f"测试物品{index}",
                        "quantity": index,
                        "reason": "CommandCenter 无害测试",
                    },
                    "expected": {},
                }
            )
        return SkillTestPlan(
            skill_id=skill.skill_id,
            skill_version=skill.version,
            cases=cases,
        )

    def match_request(self, user_request, tasks, skills):
        return TaskMatchDecision(
            candidate_task_ids=[tasks[0]["task_id"]],
            selected_skill_id=skills[0].skill_id,
            literals={
                "item_name": "打印纸",
                "quantity": 10,
                "reason": "会议使用",
            },
            summary="匹配创建采购申请 Skill",
        )

    def verify_result(self, skill, step_results, observed_state):
        purchase_ids = {
            item["ticket_id"]
            for item in observed_state["purchase_requests"]
        }
        created_ids = {
            result.normalized_output.get("data", {}).get("id")
            for result in step_results
        }
        created_ids.discard(None)
        passed = bool(created_ids) and created_ids.issubset(purchase_ids)
        return VerificationResult(
            status="passed" if passed else "failed",
            side_effects={"purchase_request_ids": sorted(created_ids)},
            duplicate_detected=len(created_ids) != 1,
            summary="采购申请创建完成" if passed else "未找到创建的采购申请",
        )


def build_procurement_system(tmp_path: Path):
    app = create_external_app(
        system_name="采购业务系统",
        system_code="connected_system",
        interface_type="workflow",
        workflow_template_id="purchase_request_001",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=[],
        seed_tasks=[],
    )
    test_client = TestClient(app)
    client = httpx.Client(transport=FastAPITransport(test_client))
    base_urls = {"connected_system": "http://connected"}
    catalog = ToolCatalog.from_openapi_documents(
        {"connected_system": app.openapi()},
        base_urls,
        {
            (
                "connected_system",
                "create_purchase_request_api_purchase_requests_post",
            )
        },
    )
    return test_client, client, base_urls, catalog


def test_one_procurement_demonstration_publishes_and_executes_skill(tmp_path):
    procurement, client, base_urls, catalog = build_procurement_system(tmp_path)
    agents = DeterministicAgents()
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    runner = SkillRunner(ToolExecutor(catalog, client))
    tester = HarmlessTestService(
        fixture_service=LocalFixtureService(client=client, base_urls=base_urls),
        runner=runner,
        verifier=agents,
    )
    learning = build_learning_graph(
        LearningDependencies(repository, agents, tester, catalog)
    )

    learned = learning.invoke(
        {"recording_id": str(uuid4()), "trace": {"api_exchanges": ["captured"]}}
    )

    assert learned["final_status"] == "published"
    published = repository.list_published_skills()
    assert len(published) == 1
    assert [step.tool_id for step in published[0].steps] == [
        "connected_system:create_purchase_request_api_purchase_requests_post"
    ]

    before = procurement.get("/api/submissions").json()["items"]
    execution = build_execution_graph(
        ExecutionDependencies(
            skills=repository.list_published_skills,
            business_reader=LocalBusinessReader(client, base_urls),
            agents=agents,
            runner=runner,
        )
    )

    result = execution.invoke(
        {"user_request": "帮我采购10箱打印纸，用于会议"}
    )

    after = procurement.get("/api/submissions").json()["items"]
    assert result["status"] == "succeeded"
    assert result["final_response"]["summary"] == "采购申请创建完成"
    assert len(after) == len(before) + 1
    created_id = result["final_response"]["outputs"]["create_purchase"]["data"]["id"]
    created = next(item for item in after if item["ticket_id"] == created_id)
    assert created["form_values"] == {
        "item_name": "打印纸",
        "quantity": 10,
        "reason": "会议使用",
    }
