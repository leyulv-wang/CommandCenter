from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx

from app.command_center.schemas import (
    ExecutionCommand,
    SkillDefinition,
    StepResult,
)
from app.command_center.tool_executor import BindingResolver


class Executor(Protocol):
    def execute(self, command: ExecutionCommand) -> StepResult: ...


@dataclass
class SkillRunResult:
    status: str
    step_results: list[StepResult]
    outputs: dict[str, Any]


class SkillRunner:
    def __init__(self, executor: Executor):
        self.executor = executor

    def run(
        self,
        skill: SkillDefinition,
        task: dict[str, Any],
        *,
        run_id: UUID,
        literals: dict[str, Any] | None = None,
    ) -> SkillRunResult:
        context: dict[str, Any] = {
            "task": task,
            "steps": {},
            "literal": literals or {},
        }
        optional_bindings = {
            expression
            for item in skill.inputs
            if not item.required
            for expression in (
                f"literal.{item.name}",
                f"task.content.{item.name}",
            )
        }
        results: list[StepResult] = []
        for step in skill.steps:
            arguments: dict[str, Any] = {}
            for target, expression in step.input_bindings.items():
                try:
                    value = BindingResolver.resolve(expression, context)
                except KeyError:
                    if expression in optional_bindings:
                        continue
                    raise
                if value is None and expression in optional_bindings:
                    continue
                _set_nested(
                    arguments,
                    _binding_target_parts(target),
                    value,
                )
            idempotency_key = None
            if step.side_effect == "write":
                source_identity = _task_source_identity(task)
                idempotency_key = ":".join(
                    (
                        str(skill.skill_id),
                        str(skill.version),
                        str(task.get("system_code", "unknown")),
                        source_identity,
                        step.step_id,
                    )
                )
            command = ExecutionCommand(
                run_id=run_id,
                skill_id=skill.skill_id,
                skill_version=skill.version,
                step_id=step.step_id,
                tool_id=step.tool_id,
                arguments=arguments,
                idempotency_key=idempotency_key,
                reason=step.name,
            )
            result = self.executor.execute(command)
            results.append(result)
            context["steps"][step.step_id] = {"output": result.normalized_output}
            if result.status == "failed":
                return SkillRunResult("failed", results, {})
        return SkillRunResult(
            "succeeded",
            results,
            {
                step_id: value["output"]
                for step_id, value in context["steps"].items()
            },
        )


def _task_source_identity(task: dict[str, Any]) -> str:
    """Return the stable source object protected by write idempotency.

    CommandCenter executes user actions through a neutral ``user-request`` task.
    That task id identifies the interaction channel, not the selected business
    object. When a trusted selected record is present, its id is therefore the
    stable idempotency boundary. This keeps retries for one object safe without
    collapsing writes for different objects into the same response.
    """

    content = task.get("content")
    if isinstance(content, dict):
        selected_record = content.get("selected_record")
        if isinstance(selected_record, dict):
            selected_id = selected_record.get("id")
            if selected_id not in (None, ""):
                return str(selected_id)
        source_reference = content.get("source_reference")
        if source_reference not in (None, ""):
            return str(source_reference)
    object_id = task.get("object_id")
    if object_id not in (None, ""):
        return str(object_id)
    return str(task.get("task_id", "unknown"))


class FixtureService(Protocol):
    def prepare(self, fixture: dict[str, Any]) -> dict[str, Any]: ...
    def observe(self, task: dict[str, Any]) -> dict[str, Any]: ...


class ResultVerifier(Protocol):
    def verify_result(
        self,
        skill: SkillDefinition,
        step_results: list[StepResult],
        observed_state: dict[str, Any],
    ) -> Any: ...


class HarmlessTestService:
    def __init__(
        self,
        *,
        fixture_service: FixtureService,
        runner: Any,
        verifier: ResultVerifier,
    ):
        self.fixture_service = fixture_service
        self.runner = runner
        self.verifier = verifier

    def run(
        self,
        skill: SkillDefinition,
        case: dict[str, Any],
    ) -> dict[str, Any]:
        task = self.fixture_service.prepare(case.get("fixture", {}))
        before_state = self.fixture_service.observe(task)
        literals = case.get("invocation", {})
        runs = [
            self.runner.run(skill, task, run_id=uuid4(), literals=literals),
        ]
        if case["category"] == "idempotency":
            runs.append(
                self.runner.run(
                    skill,
                    task,
                    run_id=uuid4(),
                    literals=literals,
                )
            )
        step_results = [
            step
            for run in runs
            for step in run.step_results
        ]
        observed_state = self.fixture_service.observe(task)
        verification_state = {
            **observed_state,
            "_execution_evidence": {
                "before_state": before_state,
                "after_state": observed_state,
            },
        }
        verification = self.verifier.verify_result(
            skill,
            step_results,
            verification_state,
        )
        run_failed = any(run.status == "failed" for run in runs)
        status = "failed" if run_failed else verification.status
        return {
            "category": case["category"],
            "status": status,
            "verification": verification.model_dump(mode="json"),
            "unknown_side_effect": verification.status == "inconclusive",
            "observed_state": observed_state,
        }


class LocalFixtureService:
    def __init__(
        self,
        *,
        client: httpx.Client,
        base_urls: dict[str, str],
    ):
        self.client = client
        self.base_urls = {
            code: url.rstrip("/")
            for code, url in base_urls.items()
        }

    def prepare(self, fixture: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            f"{self.base_urls['connected_system']}/api/demo/reset"
        )
        response.raise_for_status()
        source = fixture.get("source_task", {})
        return {
            "task_id": source.get("task_id", f"purchase-test-{uuid4()}"),
            "system_code": "connected_system",
            "content": source.get(
                "content",
                {
                    "applicant": "测试员工",
                    "item_name": "自动测试物品",
                    "quantity": 1,
                    "usage": "CommandCenter 无害测试",
                },
            ),
        }

    def observe(self, task: dict[str, Any]) -> dict[str, Any]:
        submissions_response = self.client.get(
            f"{self.base_urls['connected_system']}/api/submissions"
        )
        submissions_response.raise_for_status()
        submissions = submissions_response.json().get("items", [])
        return {
            "purchase_requests": submissions,
            "purchase_count": len(submissions),
        }


def _binding_target_parts(target: str) -> list[str]:
    return [
        part
        for part in re.sub(r"\[(\d+)\]", r".\1", target).split(".")
        if part
    ]


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    current: dict[str, Any] | list[Any] = target
    for index, part in enumerate(path):
        last = index == len(path) - 1
        numeric = part.isdigit()
        if isinstance(current, list):
            if not numeric:
                raise ValueError(f"List binding segment must be numeric: {part}")
            position = int(part)
            while len(current) <= position:
                current.append(None)
            if last:
                current[position] = value
                return
            want_list = path[index + 1].isdigit()
            child = current[position]
            if child is None:
                child = [] if want_list else {}
                current[position] = child
            if not isinstance(child, (dict, list)):
                raise ValueError(f"Binding path conflicts at segment: {part}")
            current = child
            continue
        if numeric:
            raise ValueError(f"Numeric binding segment requires a list: {part}")
        if last:
            current[part] = value
            return
        want_list = path[index + 1].isdigit()
        child = current.get(part)
        if child is None:
            child = [] if want_list else {}
            current[part] = child
        if not isinstance(child, (dict, list)):
            raise ValueError(f"Binding path conflicts at segment: {part}")
        current = child
