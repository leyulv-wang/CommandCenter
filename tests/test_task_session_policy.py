from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.command_center.schemas import SkillDefinition, StepResult
from app.command_center.task_session_policy import (
    ConfirmationError,
    PlanValidationError,
    PlanValidator,
    RetryDecision,
    canonical_plan_hash,
    classify_retry,
    confirmation_token_hash,
    default_tool_permission_checker,
    issue_confirmation_token,
    validate_confirmation,
)
from app.command_center.task_session_schemas import (
    ExecutionPlan,
    ParameterSource,
    PlannedStep,
    PrincipalContext,
)
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition
from tests.test_command_center_schemas import valid_skill_payload


def _skill() -> SkillDefinition:
    payload = valid_skill_payload()
    payload["skill_id"] = "11111111-1111-4111-8111-111111111111"
    payload["source_recording_id"] = "22222222-2222-4222-8222-222222222222"
    payload["status"] = "published"
    payload["steps"][0]["tool_id"] = "finance:create-expense"
    payload["steps"][0]["input_bindings"] = {"body.amount": "task.content.amount"}
    return SkillDefinition.model_validate(payload)


def _tool(*, mode="header") -> ToolDefinition:
    return ToolDefinition(
        tool_id="finance:create-expense",
        system_code="finance",
        operation_id="create-expense",
        method="POST",
        base_url="http://finance",
        path_template="/expenses",
        content_type="application/json",
        side_effect="write",
        body_schema={"type": "object", "properties": {"amount": {"type": "number"}}},
        idempotency_guarantee=mode,
    )


def _principal(*permissions: str) -> PrincipalContext:
    return PrincipalContext(
        subject_id="employee-9",
        tenant_id="tenant-a",
        permissions=frozenset(permissions or {"command-center:*"}),
    )


def _plan(*, tool_id="finance:create-expense", source="amount", mode="none"):
    skill = _skill()
    return ExecutionPlan(
        skill_id=skill.skill_id,
        skill_version=skill.version,
        summary="创建报销记录",
        target_objects=["expense-42"],
        inputs={"amount": 88},
        steps=[
            PlannedStep(
                step_id="create_purchase",
                name="创建报销记录",
                tool_id=tool_id,
                side_effect="write",
                arguments={"body": {"amount": 88}},
                argument_sources={
                    "body.amount": ParameterSource(kind="user_input", reference=source)
                },
                idempotency_key="stable-key",
                idempotency_guarantee=mode,
            )
        ],
    )


def _result(*, category="transient", status_code=503) -> StepResult:
    now = datetime.now(UTC)
    return StepResult(
        run_id=uuid4(),
        step_id="create_purchase",
        tool_id="finance:create-expense",
        status="failed",
        started_at=now,
        ended_at=now,
        error={"category": category, "status_code": status_code},
    )


def _validator(mode="header") -> PlanValidator:
    return PlanValidator(
        ToolCatalog([_tool(mode=mode)]), default_tool_permission_checker
    )


def test_plan_validator_rejects_tool_not_pinned_by_skill():
    with pytest.raises(PlanValidationError, match="Skill step"):
        _validator().validate(
            _plan(tool_id="other:delete"), _skill(), principal=_principal()
        )


def test_plan_validator_rejects_untraceable_argument():
    plan = _plan()
    plan.steps[0].argument_sources.pop("body.amount")

    with pytest.raises(PlanValidationError, match="source"):
        _validator().validate(plan, _skill(), principal=_principal())


def test_plan_validator_enforces_tool_permission():
    with pytest.raises(PermissionError, match="Tool permission"):
        _validator().validate(
            _plan(),
            _skill(),
            principal=PrincipalContext(
                subject_id="employee-9",
                tenant_id="tenant-a",
                permissions=frozenset(),
            ),
        )


def test_plan_validator_rejects_sensitive_parameter_sources():
    with pytest.raises(PlanValidationError, match="sensitive"):
        _validator().validate(
            _plan(source="response.authorization"),
            _skill(),
            principal=_principal(),
        )


def test_plan_validator_uses_declared_tool_idempotency_not_plan_claim():
    validated = _validator(mode="none").validate(
        _plan(mode="header"), _skill(), principal=_principal()
    )

    assert validated.plan.steps[0].idempotency_guarantee == "none"


def test_confirmation_is_bound_to_revision_and_hash():
    token = issue_confirmation_token()
    digest = confirmation_token_hash(token)
    plan_hash = canonical_plan_hash(_plan())
    validate_confirmation(
        supplied_token=token,
        stored_token_hash=digest,
        supplied_revision=2,
        stored_revision=2,
        supplied_plan_hash=plan_hash,
        stored_plan_hash=plan_hash,
        consumed=False,
    )

    with pytest.raises(ConfirmationError):
        validate_confirmation(
            supplied_token=token,
            stored_token_hash=digest,
            supplied_revision=1,
            stored_revision=2,
            supplied_plan_hash=plan_hash,
            stored_plan_hash=plan_hash,
            consumed=False,
        )


@pytest.mark.parametrize("status_code", [502, 503, 504])
def test_idempotent_write_retries_only_transient_status(status_code):
    decision = classify_retry(
        _plan(mode="header").steps[0],
        _result(status_code=status_code),
        attempt=1,
    )

    assert decision.retry is True


def test_non_idempotent_write_never_retries_uncertain_response():
    decision = classify_retry(
        _plan(mode="none").steps[0], _result(status_code=None), attempt=1
    )

    assert decision == RetryDecision(retry=False, terminal_status="unknown")
