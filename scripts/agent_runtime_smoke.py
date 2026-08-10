"""Run one match-only Microsoft Agent Runtime smoke check without side effects."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from app.command_center.agent_runtime import AgentRuntime, RuntimeResult
from app.command_center.agent_runtime_factory import build_agent_runtime
from app.command_center.agents import AgentSuite
from app.command_center.schemas import SkillDefinition, TaskMatchDecision


EXPECTED_SKILL_ID = "00000000-0000-0000-0000-000000000051"
_EXPECTED_TOOLS = ["list_available_skills", "get_available_skill"]
_EXECUTION_GRAPH_MODULE = "app.command_center.execution_graph"
_TOOL_EXECUTOR_MODULE = "app.command_center.tool_executor"


class CapturingRuntime:
    """Delegate to a runtime while preserving match-only request evidence."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime
        self.capabilities = runtime.capabilities
        self.default_limits = runtime.default_limits
        self.request: Any | None = None
        self.result: RuntimeResult[TaskMatchDecision] | None = None

    def run_structured(self, request: Any) -> RuntimeResult[TaskMatchDecision]:
        self.request = request
        self.result = self._runtime.run_structured(request)
        return self.result


def run_smoke(runtime: AgentRuntime) -> tuple[int, dict[str, Any]]:
    """Run the synthetic request and return an exit code plus safe harness trace."""
    capturing_runtime = CapturingRuntime(runtime)
    skill = _synthetic_skill()
    try:
        decision = AgentSuite(model=object(), match_runtime=capturing_runtime).match_request(
            "Look up the status of the synthetic task.",
            [{"task_id": "TASK-SMOKE-1", "content": {"kind": "synthetic"}}],
            [skill],
        )
    except Exception as exc:
        trace = _trace(capturing_runtime, skill_id=EXPECTED_SKILL_ID)
        trace["status"] = "failed_closed"
        trace["failure_classification"] = _failure_classification(exc)
        return 1, trace

    trace = _trace(capturing_runtime, skill_id=EXPECTED_SKILL_ID)
    if trace["advertised_tools"] != _EXPECTED_TOOLS:
        trace["status"] = "failed_closed"
        trace["failure_classification"] = "tool_scope_violation"
        return 1, trace
    if trace["execution_graph_imported"] or trace["tool_executor_imported"]:
        trace["status"] = "failed_closed"
        trace["failure_classification"] = "execution_scope_violation"
        return 1, trace
    if str(decision.selected_skill_id) != EXPECTED_SKILL_ID:
        trace["status"] = "failed_closed"
        trace["failure_classification"] = "candidate_boundary_rejected"
        return 1, trace

    trace["status"] = "succeeded"
    return 0, trace


def render_trace(trace: dict[str, Any]) -> str:
    """Serialize the intentionally small harness trace without provider payloads."""
    return json.dumps(trace, ensure_ascii=False, sort_keys=True)


def main() -> int:
    os.environ["COMMAND_CENTER_AGENT_RUNTIME"] = "microsoft"
    try:
        runtime = build_agent_runtime(model=object())
        exit_code, trace = run_smoke(runtime)
    except Exception as exc:
        exit_code = 1
        trace = _initialization_failure_trace(exc)
    finally:
        os.environ["COMMAND_CENTER_AGENT_RUNTIME"] = "legacy"
    print(render_trace(trace))
    return exit_code


def _synthetic_skill() -> SkillDefinition:
    return SkillDefinition.model_validate(
        {
            "skill_id": EXPECTED_SKILL_ID,
            "version": 1,
            "name": "Synthetic task status lookup",
            "description": "Read-only matching Skill for the supplied synthetic task.",
            "status": "published",
            "trigger_examples": ["look up the synthetic task status"],
            "source_recording_id": "00000000-0000-0000-0000-000000000052",
            "inputs": [],
            "outputs": [],
            "steps": [],
            "success_conditions": [],
        }
    )


def _trace(capturing_runtime: CapturingRuntime, *, skill_id: str) -> dict[str, Any]:
    request = capturing_runtime.request
    result = capturing_runtime.result
    telemetry = result.telemetry if result is not None else None
    output = result.output if result is not None else None
    return {
        "status": "failed_closed",
        "runtime": telemetry.runtime if telemetry is not None else None,
        "trace_id": telemetry.trace_id if telemetry is not None else None,
        "session_id": telemetry.session_id if telemetry is not None else None,
        "advertised_tools": (
            [tool.__name__ for tool in request.tools] if request is not None else []
        ),
        "tool_events": (
            [
                {"name": event.name, "status": event.status}
                for event in telemetry.tool_events
            ]
            if telemetry is not None
            else []
        ),
        "expected_skill_id": skill_id,
        "returned_skill_id": str(output.selected_skill_id) if output is not None else None,
        "failure_classification": None,
        "execution_graph_imported": _EXECUTION_GRAPH_MODULE in sys.modules,
        "tool_executor_imported": _TOOL_EXECUTOR_MODULE in sys.modules,
    }


def _failure_classification(error: Exception) -> str:
    if isinstance(error, ValueError) and str(error) == "agent match references unknown Skill":
        return "candidate_boundary_rejected"
    return "unexpected_runtime_error"


def _initialization_failure_trace(error: Exception) -> dict[str, Any]:
    trace = _trace_without_runtime()
    trace["failure_classification"] = "runtime_initialization_error"
    trace["error_type"] = type(error).__name__
    return trace


def _trace_without_runtime() -> dict[str, Any]:
    return {
        "status": "failed_closed",
        "runtime": None,
        "trace_id": None,
        "session_id": None,
        "advertised_tools": [],
        "tool_events": [],
        "expected_skill_id": EXPECTED_SKILL_ID,
        "returned_skill_id": None,
        "failure_classification": None,
        "execution_graph_imported": _EXECUTION_GRAPH_MODULE in sys.modules,
        "tool_executor_imported": _TOOL_EXECUTOR_MODULE in sys.modules,
    }


if __name__ == "__main__":
    raise SystemExit(main())
