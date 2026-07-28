import httpx

from app.command_center.schemas import VerificationResult
from app.command_center.testing import (
    HarmlessTestService,
    LocalFixtureService,
    SkillRunResult,
)
from tests.test_skill_runner import two_step_skill


class IsolatedFixture:
    def __init__(self):
        self.task = {
            "system_code": "onboarding_system",
            "task_id": "TEST-TASK-1",
            "content": {"item_name": "测试签字笔", "quantity": 7},
        }

    def prepare(self, fixture):
        return self.task

    def observe(self, task):
        return {"task": {**task, "status": "processing"}, "purchase_count": 1}


class CountingRunner:
    def __init__(self):
        self.calls = 0

    def run(self, skill, task, *, run_id, literals=None):
        self.calls += 1
        return SkillRunResult("succeeded", [], {"purchase_id": "WORKFLOW-1"})


class PassingVerifier:
    def verify_result(self, skill, step_results, observed_state):
        return VerificationResult(
            status="passed",
            side_effects={"purchase_count": observed_state["purchase_count"]},
            duplicate_detected=False,
            summary="业务状态正确",
        )


def test_idempotency_case_runs_same_skill_twice_and_passes_one_side_effect():
    runner = CountingRunner()
    service = HarmlessTestService(
        fixture_service=IsolatedFixture(),
        runner=runner,
        verifier=PassingVerifier(),
    )

    result = service.run(
        two_step_skill(),
        {
            "category": "idempotency",
            "fixture": {"source_task": {"content": {"quantity": 7}}},
        },
    )

    assert runner.calls == 2
    assert result["status"] == "passed"
    assert result["unknown_side_effect"] is False


class InconclusiveVerifier(PassingVerifier):
    def verify_result(self, skill, step_results, observed_state):
        return VerificationResult(
            status="inconclusive",
            side_effects={},
            duplicate_detected=False,
            summary="出现未知副作用",
        )


def test_inconclusive_verification_blocks_publication_result():
    result = HarmlessTestService(
        fixture_service=IsolatedFixture(),
        runner=CountingRunner(),
        verifier=InconclusiveVerifier(),
    ).run(two_step_skill(), {"category": "normal", "fixture": {}})

    assert result["status"] == "inconclusive"
    assert result["unknown_side_effect"] is True


def test_local_fixture_resets_both_systems_and_observes_business_state():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/tasks" and request.method == "POST":
            return httpx.Response(201, json={"task_id": "TEST-TASK-1"})
        if request.url.path == "/api/tasks/TEST-TASK-1":
            return httpx.Response(
                200,
                json={
                    "task_id": "TEST-TASK-1",
                    "status": "processing",
                    "content": {"item_name": "测试签字笔", "quantity": 7},
                    "result_values": {"purchase_request_id": "WORKFLOW-1"},
                },
            )
        if request.url.path == "/api/submissions":
            return httpx.Response(200, json={"items": [{"ticket_id": "WORKFLOW-1"}]})
        return httpx.Response(200, json={"ok": True})

    fixture = LocalFixtureService(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_urls={
            "connected_system": "http://connected",
            "onboarding_system": "http://onboarding",
        },
    )

    task = fixture.prepare(
        {
            "source_task": {
                "title": "测试库存不足",
                "content": {"item_name": "测试签字笔", "quantity": 7},
            }
        }
    )
    observed = fixture.observe(task)

    assert calls[:2] == [
        ("POST", "/api/demo/reset"),
        ("POST", "/api/demo/reset"),
    ]
    assert task["content"]["quantity"] == 7
    assert observed["purchase_count"] == 1
