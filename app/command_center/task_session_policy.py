from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict

from app.command_center.schemas import SkillDefinition, StepResult
from app.command_center.task_session_schemas import (
    ExecutionPlan,
    PlannedStep,
    PrincipalContext,
)
from app.command_center.tool_catalog import validate_tool_arguments


class PlanValidationError(ValueError):
    pass


class ConfirmationError(ValueError):
    pass


class ValidatedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: ExecutionPlan
    plan_hash: str


def canonical_plan_hash(plan: ExecutionPlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def issue_confirmation_token() -> str:
    return secrets.token_urlsafe(32)


def confirmation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_confirmation(
    *,
    supplied_token: str,
    stored_token_hash: str | None,
    supplied_revision: int,
    stored_revision: int,
    supplied_plan_hash: str,
    stored_plan_hash: str | None,
    consumed: bool,
) -> None:
    supplied_digest = confirmation_token_hash(supplied_token)
    valid = (
        not consumed
        and stored_token_hash is not None
        and stored_plan_hash is not None
        and supplied_revision == stored_revision
        and hmac.compare_digest(supplied_plan_hash, stored_plan_hash)
        and hmac.compare_digest(supplied_digest, stored_token_hash)
    )
    if not valid:
        raise ConfirmationError("confirmation is no longer valid")


def default_tool_permission_checker(
    principal: PrincipalContext, tool: Any
) -> bool:
    scopes = principal.permissions
    return bool(
        {
            "command-center:*",
            f"tool:{tool.tool_id}",
            f"system:{tool.system_code}:{tool.side_effect}",
        }
        & scopes
    )


def _materialized_argument_targets(arguments: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    for location, values in arguments.items():
        if isinstance(values, dict):
            targets.update(f"{location}.{name}" for name in values)
    return targets


def _is_sensitive_reference(reference: str) -> bool:
    lowered = reference.casefold()
    return any(
        part in lowered
        for part in ("authorization", "cookie", "password", "api_key", "token", "secret")
    )


class PlanValidator:
    def __init__(
        self,
        catalog: Any,
        permission_checker: Callable[[PrincipalContext, Any], bool],
    ) -> None:
        self.catalog = catalog
        self.permission_checker = permission_checker

    def validate(
        self,
        plan: ExecutionPlan,
        skill: SkillDefinition,
        *,
        principal: PrincipalContext,
    ) -> ValidatedPlan:
        if skill.status != "published":
            raise PlanValidationError("generic sessions require a published Skill")
        if (plan.skill_id, plan.skill_version) != (skill.skill_id, skill.version):
            raise PlanValidationError("plan does not pin the selected Skill version")
        if [step.step_id for step in plan.steps] != [step.step_id for step in skill.steps]:
            raise PlanValidationError("Skill step order does not match plan")

        validated_steps: list[PlannedStep] = []
        for planned, declared in zip(plan.steps, skill.steps, strict=True):
            if (planned.tool_id, planned.side_effect) != (
                declared.tool_id,
                declared.side_effect,
            ):
                raise PlanValidationError("Skill step does not match plan step")
            try:
                tool = self.catalog.get(planned.tool_id)
            except KeyError as exc:
                raise PlanValidationError("Skill step Tool is not allowlisted") from exc
            if not self.permission_checker(principal, tool):
                raise PermissionError("Tool permission denied")
            try:
                validate_tool_arguments(tool, planned.arguments, require_read=False)
            except ValueError as exc:
                raise PlanValidationError(str(exc)) from exc
            binding_targets = set(declared.input_bindings)
            if binding_targets != set(planned.argument_sources):
                raise PlanValidationError("every Skill binding requires one source")
            if binding_targets != _materialized_argument_targets(planned.arguments):
                raise PlanValidationError("materialized arguments do not match Skill bindings")
            if any(
                _is_sensitive_reference(source.reference)
                for source in planned.argument_sources.values()
            ):
                raise PlanValidationError("sensitive values cannot be plan parameters")
            if planned.side_effect == "write" and (
                not plan.target_objects or not planned.idempotency_key
            ):
                raise PlanValidationError("write steps require target and stable key")
            validated_steps.append(
                planned.model_copy(
                    update={
                        "idempotency_guarantee": tool.idempotency_guarantee
                    }
                )
            )

        declared_compensations = {
            item.step.step_id for item in skill.compensations
        }
        if set(plan.compensation_step_ids) - declared_compensations:
            raise PlanValidationError("plan references undeclared compensation")
        validated = plan.model_copy(update={"steps": validated_steps})
        return ValidatedPlan(
            plan=validated, plan_hash=canonical_plan_hash(validated)
        )


MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    terminal_status: Literal["failed", "unknown"] = "failed"


def classify_retry(
    step: PlannedStep, result: StepResult, attempt: int
) -> RetryDecision:
    if result.status != "failed" or attempt >= MAX_ATTEMPTS:
        return RetryDecision(False)
    transient = result.error.get("category") == "transient"
    if step.side_effect == "read":
        return RetryDecision(transient)
    protected = step.idempotency_guarantee in {"header", "intrinsic"}
    if transient and protected:
        return RetryDecision(True)
    if transient:
        return RetryDecision(False, "unknown")
    return RetryDecision(False)
