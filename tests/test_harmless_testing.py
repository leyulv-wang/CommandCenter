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
        self.literals = []

    def run(self, skill, task, *, run_id, literals=None):
        self.calls += 1
        self.literals.append(literals)
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


def test_harmless_test_passes_generated_invocation_values_to_skill():
    runner = CountingRunner()
    HarmlessTestService(
        fixture_service=IsolatedFixture(),
        runner=runner,
        verifier=PassingVerifier(),
    ).run(
        two_step_skill(),
        {
            "category": "normal",
            "fixture": {},
            "invocation": {"item_name": "打印纸", "quantity": 10},
        },
    )

    assert runner.literals == [{"item_name": "打印纸", "quantity": 10}]


class ChangingFixture(IsolatedFixture):
    def __init__(self):
        super().__init__()
        self.observations = iter(
            [
                {"objects": [], "object_count": 0},
                {"objects": [{"id": "OBJECT-1"}], "object_count": 1},
            ]
        )

    def observe(self, task):
        return next(self.observations)


class EvidenceCapturingVerifier(PassingVerifier):
    def __init__(self):
        self.observed_state = None

    def verify_result(self, skill, step_results, observed_state):
        self.observed_state = observed_state
        return VerificationResult(
            status="passed",
            side_effects={},
            duplicate_detected=False,
            summary="状态变化可解释",
        )


def test_harmless_test_gives_verifier_before_and_after_state_evidence():
    verifier = EvidenceCapturingVerifier()
    service = HarmlessTestService(
        fixture_service=ChangingFixture(),
        runner=CountingRunner(),
        verifier=verifier,
    )

    service.run(two_step_skill(), {"category": "normal", "fixture": {}})

    assert verifier.observed_state["_execution_evidence"] == {
        "before_state": {"objects": [], "object_count": 0},
        "after_state": {
            "objects": [{"id": "OBJECT-1"}],
            "object_count": 1,
        },
    }


def test_local_fixture_resets_only_procurement_and_returns_purchase_inputs():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/submissions":
            return httpx.Response(200, json={"items": []})
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
                "content": {
                    "applicant": "测试员工",
                    "item_name": "打印纸",
                    "quantity": 10,
                    "usage": "行政采购",
                },
            }
        }
    )
    observed = fixture.observe(task)

    assert calls == [
        ("POST", "/api/demo/reset"),
        ("GET", "/api/submissions"),
    ]
    assert task["system_code"] == "connected_system"
    assert task["content"]["item_name"] == "打印纸"
    assert observed["purchase_count"] == 0
