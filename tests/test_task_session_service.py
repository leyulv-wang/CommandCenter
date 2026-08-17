from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.command_center.repository import CommandCenterRepository, TaskSessionConflictError
from app.command_center.schemas import SkillDefinition, StepResult, VerificationResult
from app.command_center.task_session_executor import ResumableTaskExecutor
from app.command_center.task_session_policy import (
    ConfirmationError,
    PlanValidator,
    default_tool_permission_checker,
)
from app.command_center.task_session_schemas import (
    CreateTaskSessionRequest,
    ParameterSource,
    PrincipalContext,
    TaskContextInterpretation,
    TaskIntentResolution,
    TaskPlanProposal,
    TaskSessionConfirmationRequest,
    TaskSessionInputRequest,
)
from app.command_center.task_session_service import TaskSessionService
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition
from app.command_center.redaction import TraceRedactor


READ_SKILL_ID = UUID("55555555-5555-4555-8555-555555555555")
WRITE_SKILL_ID = UUID("66666666-6666-4666-8666-666666666666")


def _skill(*, write=False, needs_amount=False):
    skill_id = WRITE_SKILL_ID if write else READ_SKILL_ID
    return SkillDefinition.model_validate(
        {
            "skill_id": str(skill_id),
            "version": 1,
            "name": "创建报销" if write else "查询假期",
            "description": "通用测试能力",
            "status": "published",
            "trigger_examples": ["创建" if write else "查询"],
            "source_recording_id": str(uuid4()),
            "inputs": (
                [{"name": "amount", "type": "number", "description": "金额"}]
                if needs_amount
                else []
            ),
            "outputs": [],
            "steps": [
                {
                    "step_id": "execute",
                    "name": "执行",
                    "tool_id": "finance:create" if write else "hr:leave",
                    "input_bindings": (
                        {"body.amount": "literal.amount"}
                        if needs_amount
                        else {}
                    ),
                    "side_effect": "write" if write else "read",
                    **(
                        {"idempotency_key_template": "{skill_id}:{step_id}"}
                        if write
                        else {}
                    ),
                }
            ],
            "success_conditions": [],
        }
    )


class FakeAgents:
    def resolve_task_intent(self, *, goal, skills, object_candidates):
        write = "创建" in goal
        skill = next(item for item in skills if (item.skill_id == WRITE_SKILL_ID) == write)
        return TaskIntentResolution(
            status="matched",
            skill_id=skill.skill_id,
            skill_version=skill.version,
            summary="匹配能力",
        )

    def interpret_task_context(self, **_):
        return TaskContextInterpretation(summary="无需额外上下文")

    def propose_task_plan(self, *, skill, selected_object, input_sources, **_):
        return TaskPlanProposal(
            summary=skill.description,
            target_object_ids=[str(selected_object["id"])] if selected_object else ["user-goal"],
            argument_sources={
                f"{step.step_id}.{target}": input_sources[expression.removeprefix("literal.")]
                for step in skill.steps
                for target, expression in step.input_bindings.items()
            },
        )

    def verify_result(self, skill, step_results, observed_state):
        return VerificationResult(status="passed", summary="业务结果已验证")


class EmptyContextResolver:
    def resolve(self, **_):
        return []


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, command):
        self.calls.append(command)
        now = datetime.now(UTC)
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status="succeeded",
            started_at=now,
            ended_at=now,
            normalized_output={"result": "ok", "external_id": "R-1"},
            side_effect={"occurred": command.tool_id == "finance:create"},
        )


@pytest.fixture
def session_service(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    read_skill = _skill()
    write_skill = _skill(write=True, needs_amount=True)
    read_tool = ToolDefinition(
        tool_id="hr:leave",
        system_code="hr",
        operation_id="leave",
        method="GET",
        base_url="http://hr",
        path_template="/leave",
        content_type=None,
        side_effect="read",
    )
    write_tool = ToolDefinition(
        tool_id="finance:create",
        system_code="finance",
        operation_id="create",
        method="POST",
        base_url="http://finance",
        path_template="/expenses",
        content_type="application/json",
        side_effect="write",
        body_schema={"type": "object", "properties": {"amount": {"type": "number"}}},
        idempotency_guarantee="header",
    )
    catalog = ToolCatalog([read_tool, write_tool])
    raw_executor = RecordingExecutor()
    service = TaskSessionService(
        repository=repository,
        principal_provider=lambda: PrincipalContext(
            subject_id="local-user",
            tenant_id="local",
            permissions=frozenset({"command-center:*"}),
        ),
        agents=FakeAgents(),
        skills=lambda: [read_skill, write_skill],
        catalog=catalog,
        context_resolver=EmptyContextResolver(),
        validator=PlanValidator(catalog, default_tool_permission_checker),
        executor=ResumableTaskExecutor(
            raw_executor, redactor=TraceRedactor(fingerprint_key=b"test"), backoff=lambda _: None
        ),
        verifier=FakeAgents(),
    )
    service.raw_executor = raw_executor
    return service


def test_read_only_session_executes_without_confirmation(session_service):
    created = session_service.create(CreateTaskSessionRequest(goal="查询我的假期余额"))

    assert created.state == "succeeded"
    assert created.next_interaction.type == "result"
    assert session_service.raw_executor.calls[0].tool_id == "hr:leave"


def test_simple_missing_input_pauses_for_question(session_service):
    created = session_service.create(CreateTaskSessionRequest(goal="创建报销记录"))

    assert created.state == "collecting_input"
    assert created.next_interaction.type == "question"

    resumed = session_service.submit_inputs(
        created.session_id,
        TaskSessionInputRequest(version=created.version, values={"amount": 88}),
    )
    assert resumed.state == "awaiting_confirmation"


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


def test_write_session_executes_only_after_bound_confirmation(session_service):
    collecting = session_service.create(CreateTaskSessionRequest(goal="创建报销记录"))
    pending = session_service.submit_inputs(
        collecting.session_id,
        TaskSessionInputRequest(version=collecting.version, values={"amount": 88}),
    )
    assert session_service.raw_executor.calls == []

    completed = _approve(pending, session_service)

    assert completed.state == "succeeded"
    assert len(session_service.raw_executor.calls) == 1


def test_changed_input_invalidates_previous_confirmation(session_service):
    collecting = session_service.create(CreateTaskSessionRequest(goal="创建报销记录"))
    pending = session_service.submit_inputs(
        collecting.session_id,
        TaskSessionInputRequest(version=collecting.version, values={"amount": 88}),
    )
    old_interaction = pending.next_interaction

    changed = session_service.submit_inputs(
        pending.session_id,
        TaskSessionInputRequest(version=pending.version, values={"amount": 99}),
    )

    assert changed.plan_revision == pending.plan_revision + 1
    assert changed.plan_hash != pending.plan_hash
    with pytest.raises(ConfirmationError):
        session_service.confirm(
            changed.session_id,
            TaskSessionConfirmationRequest(
                version=changed.version,
                plan_revision=pending.plan_revision,
                plan_hash=pending.plan_hash,
                confirmation_token=old_interaction.confirmation_token,
                approved=True,
            ),
        )


def test_stale_version_is_rejected(session_service):
    created = session_service.create(CreateTaskSessionRequest(goal="创建报销记录"))

    with pytest.raises(TaskSessionConflictError):
        session_service.submit_inputs(
            created.session_id,
            TaskSessionInputRequest(version=created.version - 1, values={"amount": 88}),
        )


def test_confirmation_token_is_single_use(session_service):
    collecting = session_service.create(CreateTaskSessionRequest(goal="创建报销记录"))
    pending = session_service.submit_inputs(
        collecting.session_id,
        TaskSessionInputRequest(version=collecting.version, values={"amount": 88}),
    )
    _approve(pending, session_service)

    with pytest.raises((ConfirmationError, TaskSessionConflictError)):
        _approve(pending, session_service)


def test_action_hint_uses_record_from_parent_run_not_browser_payload(session_service):
    parent_run_id = uuid4()
    session_service.repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "status": "succeeded",
            "available_actions": [
                {
                    "action_id": "create-expense",
                    "record_id": "record-9",
                    "skill_id": str(WRITE_SKILL_ID),
                    "skill_version": 1,
                    "task_session_eligible": True,
                }
            ],
            "final_response": {
                "outputs": {
                    "query": {
                        "records": [
                            {"id": "record-9", "owner": "trusted server value"}
                        ]
                    }
                }
            },
        },
    )

    created = session_service.create(
        CreateTaskSessionRequest.model_validate(
            {
                "goal": "创建报销记录",
                "hint": {
                    "parent_run_id": str(parent_run_id),
                    "selected_record_id": "record-9",
                    "selected_object": {"id": "record-9", "owner": "tampered"},
                    "skill_id": str(WRITE_SKILL_ID),
                    "skill_version": 1,
                    "action_id": "create-expense",
                },
            }
        )
    )

    stored = session_service.repository.get_task_session(created.session_id)
    assert stored.selected_object["owner"] == "trusted server value"
