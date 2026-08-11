from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.command_center.schemas import (
    DirectToolPlan,
    ExecutionCommand,
    StepResult,
)
from app.command_center.tool_catalog import ToolDefinition


class ToolResolver(Protocol):
    def get(self, tool_id: str) -> ToolDefinition: ...


class Executor(Protocol):
    def execute(self, command: ExecutionCommand) -> StepResult: ...


@dataclass
class DirectToolRunResult:
    status: str
    step_results: list[StepResult]
    outputs: dict[str, Any]
    evidence: list[dict[str, Any]]


class DirectToolRunner:
    def __init__(self, catalog: ToolResolver, executor: Executor):
        self.catalog = catalog
        self.executor = executor

    def run(self, plan: DirectToolPlan, *, run_id: UUID) -> DirectToolRunResult:
        if plan.status != "matched":
            raise ValueError("only matched direct Tool plans can execute")

        results: list[StepResult] = []
        outputs: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        for step in plan.steps[:3]:
            tool = self.catalog.get(step.tool_id)
            if tool.side_effect != "read":
                raise ValueError("direct Tool execution is read-only")
            command = ExecutionCommand(
                run_id=run_id,
                step_id=step.step_id,
                tool_id=step.tool_id,
                arguments=deepcopy(step.arguments),
                reason=step.reason,
            )
            result = self.executor.execute(command)
            results.append(result)
            evidence.append(_safe_evidence(command, result))
            if result.status != "succeeded":
                return DirectToolRunResult(
                    status="failed",
                    step_results=results,
                    outputs=outputs,
                    evidence=evidence,
                )
            outputs[step.step_id] = result.normalized_output

        return DirectToolRunResult(
            status="succeeded",
            step_results=results,
            outputs=outputs,
            evidence=evidence,
        )


def _safe_evidence(
    command: ExecutionCommand,
    result: StepResult,
) -> dict[str, Any]:
    request_summary = {
        key: result.request_summary[key]
        for key in ("method", "path")
        if key in result.request_summary
    }
    response_summary = {
        key: result.response_summary[key]
        for key in ("status_code",)
        if key in result.response_summary
    }
    return {
        "step_id": command.step_id,
        "tool_id": command.tool_id,
        "arguments": deepcopy(command.arguments),
        "status": result.status,
        "request_summary": request_summary,
        "response_summary": response_summary,
    }
