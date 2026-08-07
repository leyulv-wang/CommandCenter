from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.command_center.schemas import SkillDefinition
from app.command_center.testing import SkillRunner
from app.command_center.tool_catalog import ToolCatalog
from app.command_center.tool_executor import BindingResolver


class ReadOnlySkillTestService:
    """Execute candidate query Skills without granting any write Tool."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog,
        runner: SkillRunner,
        credential_cleanup: Callable[[], None] | None = None,
    ) -> None:
        self.catalog = catalog
        self.runner = runner
        self.credential_cleanup = credential_cleanup or (lambda: None)

    def run(self, skill: SkillDefinition, case: dict[str, Any]) -> dict[str, Any]:
        category = str(case.get("category", "normal"))
        try:
            for step in skill.steps:
                tool = self.catalog.get(step.tool_id)
                if step.side_effect != "read" or tool.side_effect != "read":
                    return self._failed(category, "candidate contains a write Tool")

            fixture = case.get("fixture", {})
            task = fixture.get(
                "source_task",
                {"task_id": "readonly-test", "system_code": "readonly", "content": {}},
            )
            literals = case.get("invocation", {})
            if not self._external_bindings_resolve(skill, task, literals):
                return self._failed(
                    category, "test data does not satisfy Skill bindings"
                )
            run_count = 2 if category == "idempotency" else 1
            try:
                runs = [
                    self.runner.run(skill, task, run_id=uuid4(), literals=literals)
                    for _ in range(run_count)
                ]
            except KeyError:
                return self._failed(
                    category, "test data does not satisfy Skill bindings"
                )
            step_results = [step for run in runs for step in run.step_results]
            if any(run.status != "succeeded" for run in runs):
                return self._failed(category, "query execution failed", step_results)
            if any(result.side_effect.get("occurred") is not False for result in step_results):
                return self._failed(category, "query reported a side effect", step_results)

            missing = self._missing_required_paths(
                step_results,
                case.get("expected", {}).get("required_paths", []),
            )
            if missing:
                return self._failed(category, "response contract is incomplete", step_results)
            return {
                "category": category,
                "status": "passed",
                "verification": {
                    "status": "passed",
                    "summary": "all Tools were explicitly read and response contracts matched",
                    "repeated_query_count": run_count,
                },
                "unknown_side_effect": False,
                "step_results": [item.model_dump(mode="json") for item in step_results],
            }
        finally:
            self.credential_cleanup()

    @staticmethod
    def _external_bindings_resolve(
        skill: SkillDefinition,
        task: dict[str, Any],
        literals: dict[str, Any],
    ) -> bool:
        context = {"task": task, "literal": literals, "steps": {}}
        try:
            for step in skill.steps:
                for expression in step.input_bindings.values():
                    if expression.startswith(("task.", "literal.")):
                        BindingResolver.resolve(expression, context)
        except (KeyError, ValueError):
            return False
        return True

    @staticmethod
    def _failed(category: str, summary: str, step_results: list[Any] | None = None):
        return {
            "category": category,
            "status": "failed",
            "verification": {"status": "failed", "summary": summary},
            "unknown_side_effect": False,
            "step_results": [
                item.model_dump(mode="json") for item in (step_results or [])
            ],
        }

    @staticmethod
    def _missing_required_paths(step_results: list[Any], paths: list[str]) -> list[str]:
        missing: list[str] = []
        outputs = [result.normalized_output for result in step_results]
        for path in paths:
            parts = path.split(".")
            if not any(ReadOnlySkillTestService._has_path(output, parts) for output in outputs):
                missing.append(path)
        return missing

    @staticmethod
    def _has_path(value: Any, parts: list[str]) -> bool:
        current = value
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return True
