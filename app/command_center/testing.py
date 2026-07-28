from __future__ import annotations

from dataclasses import dataclass
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
        results: list[StepResult] = []
        for step in skill.steps:
            arguments: dict[str, Any] = {}
            for target, expression in step.input_bindings.items():
                _set_nested(
                    arguments,
                    target.split("."),
                    BindingResolver.resolve(expression, context),
                )
            idempotency_key = None
            if step.side_effect == "write":
                idempotency_key = ":".join(
                    (
                        str(skill.skill_id),
                        str(skill.version),
                        str(task.get("system_code", "unknown")),
                        str(task.get("task_id", task.get("object_id", "unknown"))),
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
        runs = [
            self.runner.run(skill, task, run_id=uuid4()),
        ]
        if case["category"] == "idempotency":
            runs.append(self.runner.run(skill, task, run_id=uuid4()))
        step_results = [
            step
            for run in runs
            for step in run.step_results
        ]
        observed_state = self.fixture_service.observe(task)
        verification = self.verifier.verify_result(
            skill,
            step_results,
            observed_state,
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
        for system_code in ("connected_system", "onboarding_system"):
            response = self.client.post(
                f"{self.base_urls[system_code]}/api/demo/reset"
            )
            response.raise_for_status()
        source = fixture.get("source_task", {})
        response = self.client.post(
            f"{self.base_urls['onboarding_system']}/api/tasks",
            json={
                "title": source.get("title", "CommandCenter 自动测试任务"),
                "task_type": "office_supply_review",
                "form_code": "office_supply_task_result",
                "content": source.get(
                    "content",
                    {
                        "item_name": "自动测试物品",
                        "quantity": 1,
                        "usage": "CommandCenter 无害测试",
                        "applicant": "测试员工",
                    },
                ),
                "assignee_id": "u001",
            },
        )
        response.raise_for_status()
        task_id = response.json()["task_id"]
        detail = self.client.get(
            f"{self.base_urls['onboarding_system']}/api/tasks/{task_id}"
        )
        detail.raise_for_status()
        return {
            **detail.json(),
            "system_code": "onboarding_system",
        }

    def observe(self, task: dict[str, Any]) -> dict[str, Any]:
        task_response = self.client.get(
            f"{self.base_urls['onboarding_system']}/api/tasks/{task['task_id']}"
        )
        task_response.raise_for_status()
        submissions_response = self.client.get(
            f"{self.base_urls['connected_system']}/api/submissions"
        )
        submissions_response.raise_for_status()
        submissions = submissions_response.json().get("items", [])
        return {
            "task": task_response.json(),
            "purchase_requests": submissions,
            "purchase_count": len(submissions),
        }


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    current = target
    for part in path[:-1]:
        current = current.setdefault(part, {})
    current[path[-1]] = value
