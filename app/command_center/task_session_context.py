from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.command_center.direct_tool_runner import DirectToolRunner
from app.command_center.redaction import TraceRedactor
from app.command_center.task_session_schemas import ContextEvidence


class ContextResolutionError(RuntimeError):
    def __init__(self, step_results: list[Any]):
        super().__init__("read-only context resolution failed")
        self.step_results = step_results


class ReadOnlyTaskContextResolver:
    def __init__(
        self,
        *,
        agents: Any,
        tools: Callable[[], list[Any]],
        runner: DirectToolRunner,
        redactor: TraceRedactor,
    ) -> None:
        self.agents = agents
        self.tools = tools
        self.runner = runner
        self.redactor = redactor

    def resolve(
        self,
        *,
        goal: str,
        selected_object: dict[str, Any] | None,
    ) -> list[ContextEvidence]:
        available = [tool for tool in self.tools() if tool.side_effect == "read"]
        plan = self.agents.plan_tool_request(
            user_request=goal,
            task_context={"selected_object": selected_object},
            tools=available,
        )
        if plan.status != "matched":
            return []
        for step in plan.steps:
            if self.runner.catalog.get(step.tool_id).side_effect != "read":
                raise ValueError("context resolution is read-only")
        run = self.runner.run(plan, run_id=uuid4())
        if run.status != "succeeded":
            raise ContextResolutionError(run.step_results)
        object_id = (
            str(selected_object.get("id"))
            if selected_object and selected_object.get("id") is not None
            else None
        )
        planned = {item.step_id: item for item in plan.steps}
        return [
            ContextEvidence(
                evidence_id=f"context:{result.step_id}",
                tool_id=result.tool_id,
                object_id=object_id,
                arguments=self.redactor.redact_payload(
                    planned[result.step_id].arguments
                ),
                output=self.redactor.redact_payload(result.normalized_output),
                observed_at=result.ended_at,
            )
            for result in run.step_results
        ]
