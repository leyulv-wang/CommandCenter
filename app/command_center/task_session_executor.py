from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.command_center.redaction import TraceRedactor
from app.command_center.schemas import ExecutionCommand, SkillDefinition, StepResult
from app.command_center.task_session_policy import classify_retry
from app.command_center.task_session_schemas import ExecutionPlan, PlannedStep


class TaskExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed", "partial_failure", "unknown"]
    step_results: list[StepResult]
    compensation_results: list[StepResult] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)


def default_backoff(attempt: int) -> None:
    time.sleep(min(2 ** (attempt - 1), 4))


class ResumableTaskExecutor:
    def __init__(
        self,
        executor: Any,
        *,
        redactor: TraceRedactor,
        backoff: Callable[[int], None] = default_backoff,
    ) -> None:
        self.executor = executor
        self.redactor = redactor
        self.backoff = backoff

    def execute(
        self,
        *,
        plan: ExecutionPlan,
        skill: SkillDefinition,
        prior_results: list[StepResult],
        checkpoint: Callable[[StepResult], None],
    ) -> TaskExecutionOutcome:
        if [item.step_id for item in plan.steps] != [item.step_id for item in skill.steps]:
            raise ValueError("execution plan does not match immutable Skill steps")
        results = [deepcopy(item) for item in prior_results]
        successful = {
            item.step_id: item
            for item in prior_results
            if item.status == "succeeded"
        }
        outputs = {
            step_id: deepcopy(item.normalized_output)
            for step_id, item in successful.items()
        }
        writes_succeeded = any(
            item.status == "succeeded" and item.side_effect.get("occurred")
            for item in prior_results
        )

        for declared, planned in zip(skill.steps, plan.steps, strict=True):
            if planned.step_id in successful:
                continue
            command = self._materialize_command(declared, planned, outputs)
            attempt = 1
            while True:
                raw_result = self.executor.execute(command)
                persisted = _redact_step_result(raw_result, self.redactor)
                checkpoint(persisted)
                results.append(persisted)
                if raw_result.status == "succeeded":
                    outputs[planned.step_id] = deepcopy(raw_result.normalized_output)
                    writes_succeeded = writes_succeeded or bool(
                        raw_result.side_effect.get("occurred")
                    )
                    break
                decision = classify_retry(planned, raw_result, attempt)
                if not decision.retry:
                    status: Literal["failed", "partial_failure", "unknown"]
                    if decision.terminal_status == "unknown":
                        status = "unknown"
                    elif writes_succeeded:
                        status = "partial_failure"
                    else:
                        status = "failed"
                    compensations = self._run_compensations(
                        skill=skill,
                        plan=plan,
                        failed_step_id=planned.step_id,
                        checkpoint=checkpoint,
                    )
                    return TaskExecutionOutcome(
                        status=status,
                        step_results=results,
                        compensation_results=compensations,
                        outputs=outputs,
                    )
                self.backoff(attempt)
                attempt += 1

        return TaskExecutionOutcome(
            status="succeeded",
            step_results=results,
            compensation_results=[],
            outputs=outputs,
        )

    @staticmethod
    def _materialize_command(
        declared: Any,
        planned: PlannedStep,
        outputs: dict[str, Any],
    ) -> ExecutionCommand:
        if (declared.tool_id, declared.side_effect) != (
            planned.tool_id,
            planned.side_effect,
        ):
            raise ValueError("planned step differs from immutable Skill step")
        if set(declared.input_bindings) != _argument_targets(planned.arguments):
            raise ValueError("planned arguments differ from immutable Skill bindings")
        return ExecutionCommand(
            run_id=uuid4(),
            skill_id=None,
            skill_version=None,
            step_id=planned.step_id,
            tool_id=planned.tool_id,
            arguments=_resolve_step_outputs(planned.arguments, outputs),
            idempotency_key=planned.idempotency_key,
            reason=planned.name,
        )

    def _run_compensations(
        self,
        *,
        skill: SkillDefinition,
        plan: ExecutionPlan,
        failed_step_id: str,
        checkpoint: Callable[[StepResult], None],
    ) -> list[StepResult]:
        allowed = set(plan.compensation_step_ids)
        selected = [
            item
            for item in skill.compensations
            if item.step.step_id in allowed
            and item.trigger_step_id == failed_step_id
        ]
        results: list[StepResult] = []
        for item in reversed(selected):
            key_payload = (
                f"{plan.skill_id}:{plan.skill_version}:"
                f"{','.join(sorted(plan.target_objects))}:{item.step.step_id}"
            )
            command = ExecutionCommand(
                run_id=uuid4(),
                skill_id=plan.skill_id,
                skill_version=plan.skill_version,
                step_id=item.step.step_id,
                tool_id=item.step.tool_id,
                arguments={},
                idempotency_key=hashlib.sha256(
                    key_payload.encode("utf-8")
                ).hexdigest(),
                reason=item.step.name,
            )
            persisted = _redact_step_result(
                self.executor.execute(command), self.redactor
            )
            checkpoint(persisted)
            results.append(persisted)
        return results


def _argument_targets(arguments: dict[str, Any]) -> set[str]:
    return {
        f"{location}.{name}"
        for location, values in arguments.items()
        if isinstance(values, dict)
        for name in values
    }


def _resolve_step_outputs(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, dict) and set(value) == {"$step_output"}:
        expression = value["$step_output"]
        if not isinstance(expression, str):
            raise ValueError("step output binding must be a string")
        parts = expression.split(".")
        if len(parts) < 4 or parts[0] != "steps" or parts[2] != "output":
            raise ValueError("invalid step output binding")
        resolved: Any = outputs.get(parts[1])
        if resolved is None:
            raise ValueError("referenced step output is unavailable")
        for part in parts[3:]:
            if isinstance(resolved, dict) and part in resolved:
                resolved = resolved[part]
            elif isinstance(resolved, list) and part.isdigit() and int(part) < len(resolved):
                resolved = resolved[int(part)]
            else:
                raise ValueError("referenced step output path is unavailable")
        return deepcopy(resolved)
    if isinstance(value, dict):
        return {key: _resolve_step_outputs(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_step_outputs(item, outputs) for item in value]
    return deepcopy(value)


def _redact_step_result(
    result: StepResult, redactor: TraceRedactor
) -> StepResult:
    return result.model_copy(
        update={
            "request_summary": redactor.redact_payload(result.request_summary),
            "response_summary": redactor.redact_payload(result.response_summary),
            "normalized_output": redactor.redact_payload(result.normalized_output),
            "side_effect": redactor.redact_payload(result.side_effect),
            "error": redactor.redact_payload(result.error),
        }
    )
