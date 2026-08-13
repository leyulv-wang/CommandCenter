from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from app.command_center.schemas import SkillDefinition
from app.command_center.tool_catalog import ToolCatalog


class CrossSystemSkillTestService:
    """Verify a cross-system Skill while limiting writes to removable local data."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog,
        runner: Any,
        verifier: Any,
        client: httpx.Client,
        local_base_url: str,
    ) -> None:
        self.catalog = catalog
        self.runner = runner
        self.verifier = verifier
        self.client = client
        self.local_base_url = local_base_url.rstrip("/")

    def run(self, skill: SkillDefinition, case: dict[str, Any]) -> dict[str, Any]:
        category = str(case.get("category", "normal"))
        if not self._safe_test_shape(skill):
            return self._failed(category, "candidate contains a non-local write Tool")

        verification_run_id = str(uuid4())
        source_task = dict(case.get("fixture", {}).get("source_task", {}))
        task = {
            **source_task,
            "task_id": source_task.get("task_id", f"cross-system-test-{verification_run_id}"),
            "system_code": "cross_system_verification",
            "content": {
                **source_task.get("content", {}),
                "record_purpose": "automated_test",
                "verification_run_id": verification_run_id,
            },
        }
        created_id: str | None = None
        cleanup_status = "not_required"
        result: dict[str, Any]
        try:
            run = self.runner.run(
                skill,
                task,
                run_id=uuid4(),
                literals=case.get("invocation", {}),
            )
            if run.status != "succeeded":
                result = self._failed(category, "cross-system execution failed")
                return result
            local_write_steps = [
                step
                for step in skill.steps
                if self.catalog.get(step.tool_id).system_code == "connected_system"
                and self.catalog.get(step.tool_id).side_effect == "write"
            ]
            if len(local_write_steps) != 1:
                result = self._failed(
                    category, "verification requires exactly one removable local write"
                )
                return result
            created = run.outputs.get(local_write_steps[0].step_id, {})
            created_id = (
                created.get("follow_up_id") if isinstance(created, dict) else None
            )
            if not created_id:
                result = self._failed(category, "local test record id was not returned")
                return result
            response = self.client.get(
                f"{self.local_base_url}/api/purchase-follow-ups/{created_id}"
            )
            response.raise_for_status()
            observed = response.json()
            verification = self.verifier.verify_result(skill, run.step_results, observed)
            status = "passed" if verification.status == "passed" else "failed"
            result = {
                "category": category,
                "status": status,
                "verification": verification.model_dump(mode="json"),
                "unknown_side_effect": verification.status == "inconclusive",
                "execution_status": "succeeded",
                "cleanup_status": "pending",
                "residual_test_record_id": created_id,
            }
        except (httpx.HTTPError, KeyError, ValueError):
            result = self._failed(
                category,
                "cross-system verification failed",
                residual_test_record_id=created_id,
            )
        finally:
            if created_id:
                try:
                    response = self.client.delete(
                        f"{self.local_base_url}/api/purchase-follow-ups/{created_id}",
                        headers={"X-Verification-Run-Id": verification_run_id},
                    )
                    response.raise_for_status()
                    cleanup_status = "succeeded"
                except httpx.HTTPError:
                    cleanup_status = "failed"
        result["cleanup_status"] = cleanup_status
        if cleanup_status == "succeeded":
            result["residual_test_record_id"] = None
        elif cleanup_status == "failed":
            result["status"] = "failed"
            result["verification"] = {
                "status": "failed",
                "summary": "business verification completed but test cleanup failed",
            }
        return result

    def _safe_test_shape(self, skill: SkillDefinition) -> bool:
        local_writes = 0
        for step in skill.steps:
            tool = self.catalog.get(step.tool_id)
            if tool.side_effect == "write" and tool.system_code != "connected_system":
                return False
            if tool.side_effect == "write":
                local_writes += 1
        return local_writes == 1

    @staticmethod
    def _failed(
        category: str,
        summary: str,
        *,
        residual_test_record_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "category": category,
            "status": "failed",
            "verification": {"status": "failed", "summary": summary},
            "unknown_side_effect": False,
            "execution_status": "failed",
            "cleanup_status": "not_required",
            "residual_test_record_id": residual_test_record_id,
        }
