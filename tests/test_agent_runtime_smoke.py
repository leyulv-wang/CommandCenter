import json
import sys
from uuid import UUID

from app.command_center.agent_runtime import (
    RuntimeCapabilities,
    RuntimeLimits,
    RuntimeResult,
    RuntimeTelemetry,
    RuntimeUsage,
)
from app.command_center.schemas import TaskMatchDecision
from scripts.agent_runtime_smoke import render_trace, run_smoke


EXPECTED_SKILL_ID = UUID("00000000-0000-0000-0000-000000000051")


class FakeRuntime:
    capabilities = RuntimeCapabilities(tool_loop=True)
    default_limits = RuntimeLimits()

    def __init__(self, selected_skill_id=EXPECTED_SKILL_ID, error=None):
        self.selected_skill_id = selected_skill_id
        self.error = error
        self.requests = []

    def run_structured(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return RuntimeResult(
            output=TaskMatchDecision(
                candidate_task_ids=["TASK-SMOKE-1"],
                selected_skill_id=self.selected_skill_id,
                literals={},
                summary="synthetic match",
            ),
            telemetry=RuntimeTelemetry(
                trace_id="trace-smoke",
                session_id=request.session_id,
                runtime="fake_runtime",
                provider="fake_provider",
                model="fake_model",
                role=request.role,
                model_calls=1,
                tool_events=(),
                usage=RuntimeUsage(),
                duration_ms=1.0,
            ),
        )


def test_smoke_success_returns_only_harness_trace_fields(monkeypatch):
    monkeypatch.delitem(sys.modules, "app.command_center.execution_graph", raising=False)
    monkeypatch.delitem(sys.modules, "app.command_center.tool_executor", raising=False)

    exit_code, trace = run_smoke(FakeRuntime())

    assert exit_code == 0
    assert trace == {
        "status": "succeeded",
        "runtime": "fake_runtime",
        "trace_id": "trace-smoke",
        "session_id": trace["session_id"],
        "advertised_tools": ["list_available_skills", "get_available_skill"],
        "tool_events": [],
        "expected_skill_id": str(EXPECTED_SKILL_ID),
        "returned_skill_id": str(EXPECTED_SKILL_ID),
        "failure_classification": None,
        "execution_graph_imported": False,
        "tool_executor_imported": False,
    }
    assert json.loads(render_trace(trace)) == trace


def test_smoke_rejects_unknown_skill_as_failed_closed(monkeypatch):
    monkeypatch.delitem(sys.modules, "app.command_center.execution_graph", raising=False)
    monkeypatch.delitem(sys.modules, "app.command_center.tool_executor", raising=False)

    exit_code, trace = run_smoke(
        FakeRuntime(UUID("00000000-0000-0000-0000-000000000099"))
    )

    assert exit_code == 1
    assert trace["status"] == "failed_closed"
    assert trace["failure_classification"] == "candidate_boundary_rejected"
    assert trace["expected_skill_id"] == str(EXPECTED_SKILL_ID)
    assert trace["returned_skill_id"] == "00000000-0000-0000-0000-000000000099"
    assert trace["advertised_tools"] == [
        "list_available_skills",
        "get_available_skill",
    ]
    assert trace["execution_graph_imported"] is False
    assert trace["tool_executor_imported"] is False


def test_smoke_sanitizes_unexpected_runtime_errors(monkeypatch):
    monkeypatch.delitem(sys.modules, "app.command_center.execution_graph", raising=False)
    monkeypatch.delitem(sys.modules, "app.command_center.tool_executor", raising=False)

    exit_code, trace = run_smoke(FakeRuntime(error=RuntimeError("provider-secret")))

    rendered = render_trace(trace)
    assert exit_code == 1
    assert trace["status"] == "failed_closed"
    assert trace["failure_classification"] == "unexpected_runtime_error"
    assert "provider-secret" not in rendered
    assert "message" not in trace
