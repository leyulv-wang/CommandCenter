from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.command_center.redaction import TraceRedactor
from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import SkillDefinition, StepResult, VerificationResult
from app.command_center.task_session_executor import ResumableTaskExecutor
from app.command_center.task_session_policy import (
    ConfirmationError,
    PlanValidator,
    default_tool_permission_checker,
)
from app.command_center.task_session_schemas import (
    CreateTaskSessionRequest,
    ExecutionPlan,
    ParameterSource,
    PlannedStep,
    PrincipalContext,
    TaskContextInterpretation,
    TaskIntentResolution,
    TaskPlanProposal,
    TaskSessionConfirmationRequest,
    TaskSessionInputRequest,
)
from app.command_center.task_session_service import TaskSessionService
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition, ToolParameter


HR_SKILL_ID = UUID("77777777-7777-4777-8777-777777777777")
FINANCE_SKILL_ID = UUID("88888888-8888-4888-8888-888888888888")


def _skill(payload: dict) -> SkillDefinition:
    return SkillDefinition.model_validate(
        {
            "description": "跨领域契约能力",
            "status": "published",
            "trigger_examples": ["执行"],
            "source_recording_id": str(uuid4()),
            "outputs": [],
            "success_conditions": [],
            **payload,
        }
    )


def _hr_skill() -> SkillDefinition:
    return _skill(
        {
            "skill_id": str(HR_SKILL_ID),
            "version": 1,
            "name": "查询员工年假余额",
            "inputs": [
                {
                    "name": "employee_id",
                    "type": "string",
                    "description": "员工编号",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "step_id": "leave_balance",
                    "name": "查询年假余额",
                    "tool_id": "hr_system:get_leave_balance",
                    "input_bindings": {"query.employee_id": "literal.employee_id"},
                    "side_effect": "read",
                }
            ],
        }
    )


def _finance_skill(*, two_steps: bool = False) -> SkillDefinition:
    steps = [
        {
            "step_id": "create_expense",
            "name": "创建报销单",
            "tool_id": "finance_system:create_expense",
            "input_bindings": {"body.items": "literal.items"},
            "side_effect": "write",
            "idempotency_key_template": "{skill_id}:{step_id}:{target}",
        }
    ]
    if two_steps:
        steps.append(
            {
                "step_id": "create_ledger_entry",
                "name": "创建台账记录",
                "tool_id": "finance_system:create_ledger_entry",
                "input_bindings": {
                    "body.expense_id": "steps.create_expense.output.id"
                },
                "side_effect": "write",
                "idempotency_key_template": "{skill_id}:{step_id}:{target}",
            }
        )
    return _skill(
        {
            "skill_id": str(FINANCE_SKILL_ID),
            "version": 1,
            "name": "提交费用报销",
            "inputs": [
                {
                    "name": "items",
                    "type": "array",
                    "description": "费用明细",
                    "json_schema": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "amount": {"type": "number"},
                            },
                            "required": ["category", "amount"],
                        },
                    },
                }
            ],
            "steps": steps,
        }
    )


class ContractAgents:
    def resolve_task_intent(self, *, goal, skills, object_candidates):
        selected = next(
            item for item in skills if ("年假" in goal) == (item.skill_id == HR_SKILL_ID)
        )
        extracted = {"employee_id": "E-9"} if selected.skill_id == HR_SKILL_ID else {}
        return TaskIntentResolution(
            status="matched",
            skill_id=selected.skill_id,
            skill_version=selected.version,
            extracted_inputs=extracted,
            summary="已选择跨领域能力",
        )

    def interpret_task_context(self, **_):
        return TaskContextInterpretation(summary="无需补充业务上下文")

    def propose_task_plan(self, *, skill, input_sources, **_):
        return TaskPlanProposal(
            summary=skill.name,
            target_object_ids=["employee:E-9"] if skill.skill_id == HR_SKILL_ID else ["expense:new"],
            argument_sources={
                f"{step.step_id}.{target}": (
                    input_sources[expression.removeprefix("literal.")]
                    if expression.startswith("literal.")
                    else ParameterSource(kind="step_output", reference=expression)
                )
                for step in skill.steps
                for target, expression in step.input_bindings.items()
            },
        )

    def verify_result(self, skill, step_results, observed_state):
        if skill.skill_id == HR_SKILL_ID:
            balance = step_results[-1].normalized_output["remaining_days"]
            return VerificationResult(
                status="passed", summary=f"员工 E-9 剩余年假 {balance} 天"
            )
        return VerificationResult(status="passed", summary="费用报销已成功提交")


class EmptyContextResolver:
    def resolve(self, **_):
        return []


class StatefulContractExecutor:
    def __init__(self, scripted: list[str] | None = None):
        self.scripted = list(scripted or [])
        self.calls = []
        self.records: dict[str, str] = {}

    def execute(self, command):
        self.calls.append(command)
        behavior = self.scripted.pop(0) if self.scripted else "succeeded"
        now = datetime.now(UTC)
        is_write = command.tool_id.startswith("finance_system:create")
        key = command.idempotency_key or f"unprotected:{len(self.calls)}"
        if is_write and behavior in {"succeeded", "timeout_after_write"}:
            self.records.setdefault(key, f"record-{len(self.records) + 1}")
        if behavior in {"timeout", "timeout_after_write"}:
            return StepResult(
                run_id=command.run_id,
                step_id=command.step_id,
                tool_id=command.tool_id,
                status="failed",
                started_at=now,
                ended_at=now,
                error={"category": "transient", "code": "ReadTimeout"},
                side_effect={"occurred": behavior == "timeout_after_write"},
            )
        if behavior == "business_failure":
            return StepResult(
                run_id=command.run_id,
                step_id=command.step_id,
                tool_id=command.tool_id,
                status="failed",
                started_at=now,
                ended_at=now,
                error={"category": "business", "code": "policy_rejected"},
            )
        output = (
            {"remaining_days": 5}
            if command.tool_id == "hr_system:get_leave_balance"
            else {"id": self.records[key]}
        )
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status="succeeded",
            started_at=now,
            ended_at=now,
            normalized_output=output,
            side_effect={"occurred": is_write},
        )


def _tools(*, protected: bool = True) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            tool_id="hr_system:get_leave_balance",
            system_code="hr_system",
            operation_id="get_leave_balance",
            method="GET",
            base_url="http://hr.invalid",
            path_template="/leave-balance",
            content_type=None,
            side_effect="read",
            parameters=(
                ToolParameter(
                    name="employee_id",
                    location="query",
                    type="string",
                    required=True,
                    description="员工编号",
                ),
            ),
        ),
        ToolDefinition(
            tool_id="finance_system:create_expense",
            system_code="finance_system",
            operation_id="create_expense",
            method="POST",
            base_url="http://finance.invalid",
            path_template="/expenses",
            content_type="application/json",
            side_effect="write",
            body_schema={"type": "object", "properties": {"items": {"type": "array"}}},
            idempotency_guarantee="header" if protected else "none",
        ),
        ToolDefinition(
            tool_id="finance_system:create_ledger_entry",
            system_code="finance_system",
            operation_id="create_ledger_entry",
            method="POST",
            base_url="http://finance.invalid",
            path_template="/ledger",
            content_type="application/json",
            side_effect="write",
            body_schema={"type": "object", "properties": {"expense_id": {"type": "string"}}},
            idempotency_guarantee="header",
        ),
    ]


def _service(tmp_path: Path, *, executor=None, skills=None, protected=True):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / f'{uuid4()}.sqlite3'}")
    catalog = ToolCatalog(_tools(protected=protected))
    raw_executor = executor or StatefulContractExecutor()
    agents = ContractAgents()
    service = TaskSessionService(
        repository=repository,
        principal_provider=lambda: PrincipalContext(
            subject_id="contract-user",
            tenant_id="contract-tenant",
            permissions=frozenset({"command-center:*"}),
        ),
        agents=agents,
        skills=lambda: skills or [_hr_skill(), _finance_skill()],
        catalog=catalog,
        context_resolver=EmptyContextResolver(),
        validator=PlanValidator(catalog, default_tool_permission_checker),
        executor=ResumableTaskExecutor(
            raw_executor,
            redactor=TraceRedactor(fingerprint_key=b"contract"),
            backoff=lambda _: None,
        ),
        verifier=agents,
    )
    service.raw_executor = raw_executor
    return service


def _approve(pending, service):
    interaction = pending.next_interaction
    return service.confirm(
        pending.session_id,
        TaskSessionConfirmationRequest(
            version=pending.version,
            plan_revision=pending.plan_revision,
            plan_hash=pending.plan_hash,
            confirmation_token=interaction.confirmation_token,
            approved=True,
        ),
    )


def _finance_pending(service):
    collecting = service.create(
        CreateTaskSessionRequest(
            goal="提交一张包含两条费用的报销单",
            hint={"skill_id": str(FINANCE_SKILL_ID), "skill_version": 1},
        )
    )
    assert collecting.next_interaction.type == "form"
    return service.submit_inputs(
        collecting.session_id,
        TaskSessionInputRequest(
            version=collecting.version,
            values={
                "items": [
                    {"category": "差旅", "amount": 88},
                    {"category": "餐费", "amount": 32},
                ]
            },
        ),
    )


def test_hr_leave_balance_is_read_only_and_needs_no_confirmation(tmp_path):
    service = _service(tmp_path)
    result = service.create(
        CreateTaskSessionRequest(
            goal="查看员工 E-9 的剩余年假",
            hint={"skill_id": str(HR_SKILL_ID), "skill_version": 1},
        )
    )

    assert result.state == "succeeded"
    assert result.next_interaction.type == "result"
    assert result.next_interaction.summary == "员工 E-9 剩余年假 5 天"
    assert len(service.raw_executor.calls) == 1


def test_finance_expense_uses_form_confirmation_and_idempotent_write(tmp_path):
    service = _service(tmp_path)
    pending = _finance_pending(service)

    assert pending.next_interaction.type == "confirmation"
    completed = _approve(pending, service)

    assert completed.state == "succeeded"
    assert len(service.raw_executor.records) == 1
    assert service.raw_executor.calls[0].idempotency_key


@dataclass(frozen=True)
class ContractOutcome:
    status: str
    tool_calls: int
    target_records: int


class ContractHarness:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def run(self, scenario: str) -> ContractOutcome:
        if scenario == "changed_target":
            service = _service(self.tmp_path)
            pending = _finance_pending(service)
            old = pending.next_interaction
            changed = service.submit_inputs(
                pending.session_id,
                TaskSessionInputRequest(
                    version=pending.version,
                    values={"items": [{"category": "住宿", "amount": 99}]},
                ),
            )
            try:
                service.confirm(
                    changed.session_id,
                    TaskSessionConfirmationRequest(
                        version=changed.version,
                        plan_revision=pending.plan_revision,
                        plan_hash=pending.plan_hash,
                        confirmation_token=old.confirmation_token,
                        approved=True,
                    ),
                )
            except ConfirmationError:
                return ContractOutcome("confirmation_rejected", 0, 0)
            raise AssertionError("changed plan accepted an obsolete confirmation")

        if scenario == "duplicate_confirmation":
            service = _service(self.tmp_path)
            pending = _finance_pending(service)
            completed = _approve(pending, service)
            repeated = _approve(pending, service)
            assert repeated == completed
            return ContractOutcome(
                repeated.state,
                len(service.raw_executor.calls),
                len(service.raw_executor.records),
            )

        scripted = {
            "idempotent_timeout": ["timeout_after_write", "succeeded"],
            "business_failure": ["business_failure"],
            "partial_failure": ["succeeded", "business_failure"],
            "unprotected_timeout": ["timeout_after_write"],
        }
        if scenario in scripted:
            executor = StatefulContractExecutor(scripted[scenario])
            two_steps = scenario == "partial_failure"
            service = _service(
                self.tmp_path,
                executor=executor,
                skills=[_finance_skill(two_steps=two_steps)],
                protected=scenario != "unprotected_timeout",
            )
            completed = _approve(_finance_pending(service), service)
            return ContractOutcome(
                completed.next_interaction.status,
                len(executor.calls),
                len(executor.records),
            )

        if scenario == "restart_after_success":
            executor = StatefulContractExecutor()
            service = _service(self.tmp_path, executor=executor)
            completed = _approve(_finance_pending(service), service)
            assert completed.state == "succeeded"
            service.resume_pending()
            return ContractOutcome("succeeded", len(executor.calls), len(executor.records))

        raise AssertionError(f"unknown scenario: {scenario}")


@pytest.fixture
def contract_harness(tmp_path):
    return ContractHarness(tmp_path)


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_calls", "expected_records"),
    [
        ("changed_target", "confirmation_rejected", 0, 0),
        ("duplicate_confirmation", "succeeded", 1, 1),
        ("idempotent_timeout", "succeeded", 2, 1),
        ("business_failure", "failed", 1, 0),
        ("partial_failure", "partial_failure", 2, 1),
        ("restart_after_success", "succeeded", 1, 1),
        ("unprotected_timeout", "unknown", 1, 1),
    ],
)
def test_failure_and_recovery_contracts(
    contract_harness,
    scenario,
    expected_status,
    expected_calls,
    expected_records,
):
    outcome = contract_harness.run(scenario)
    assert outcome.status == expected_status
    assert outcome.tool_calls == expected_calls
    assert outcome.target_records == expected_records


def test_generic_task_session_modules_do_not_contain_domain_sample_fields():
    root = Path(__file__).parents[1] / "app" / "command_center"
    generic_modules = [
        root / "task_session_service.py",
        root / "task_session_executor.py",
        root / "task_session_policy.py",
        root / "task_session_inputs.py",
        root / "task_session_context.py",
    ]
    forbidden = ("purchase_follow_up", "applyNo", "CGSQ")
    for path in generic_modules:
        source = path.read_text(encoding="utf-8")
        assert not any(term in source for term in forbidden), path.name
