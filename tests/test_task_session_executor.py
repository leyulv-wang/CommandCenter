from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.command_center.redaction import TraceRedactor
from app.command_center.schemas import SkillDefinition, StepResult
from app.command_center.task_session_executor import ResumableTaskExecutor
from app.command_center.task_session_schemas import ExecutionPlan, PlannedStep


SKILL_ID = UUID("44444444-4444-4444-8444-444444444444")


def _skill(step_specs, compensations=None):
    steps = []
    for step_id, side_effect in step_specs:
        steps.append(
            {
                "step_id": step_id,
                "name": step_id,
                "tool_id": f"system:{step_id}",
                "input_bindings": {},
                "side_effect": side_effect,
                **(
                    {"idempotency_key_template": f"key:{step_id}"}
                    if side_effect == "write"
                    else {}
                ),
            }
        )
    return SkillDefinition.model_validate(
        {
            "skill_id": str(SKILL_ID),
            "version": 1,
            "name": "通用执行",
            "description": "通用执行测试",
            "status": "published",
            "trigger_examples": ["执行"],
            "source_recording_id": str(uuid4()),
            "inputs": [],
            "outputs": [],
            "steps": steps,
            "success_conditions": [],
            "compensations": compensations or [],
        }
    )


def _plan(step_specs, *, compensation_step_ids=None, protected=True):
    return ExecutionPlan(
        skill_id=SKILL_ID,
        skill_version=1,
        summary="执行",
        target_objects=["object-1"],
        steps=[
            PlannedStep(
                step_id=step_id,
                name=step_id,
                tool_id=f"system:{step_id}",
                side_effect=side_effect,
                arguments={},
                argument_sources={},
                idempotency_key=(f"stable:{step_id}" if side_effect == "write" else None),
                idempotency_guarantee=(
                    "header" if side_effect == "write" and protected else "none"
                ),
            )
            for step_id, side_effect in step_specs
        ],
        compensation_step_ids=compensation_step_ids or [],
    )


def _result(status, *, step_id="placeholder", error=None, occurred=False, output=None):
    now = datetime.now(UTC)
    return StepResult(
        run_id=uuid4(),
        step_id=step_id,
        tool_id=f"system:{step_id}",
        status=status,
        started_at=now,
        ended_at=now,
        normalized_output=output or {},
        side_effect={"occurred": occurred},
        error=error or {},
    )


class SequenceExecutor:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, command):
        self.calls.append(command)
        template = self.results.pop(0)
        return template.model_copy(
            update={
                "run_id": command.run_id,
                "step_id": command.step_id,
                "tool_id": command.tool_id,
            }
        )


def test_executor_skips_checkpointed_success_after_restart():
    prior = _result("succeeded", step_id="read", output={"id": "42"})
    executor = SequenceExecutor(_result("succeeded", occurred=True))

    outcome = ResumableTaskExecutor(
        executor, redactor=TraceRedactor(fingerprint_key=b"test")
    ).execute(
        plan=_plan([("read", "read"), ("create", "write")]),
        skill=_skill([("read", "read"), ("create", "write")]),
        prior_results=[prior],
        checkpoint=lambda _: None,
    )

    assert [call.step_id for call in executor.calls] == ["create"]
    assert outcome.status == "succeeded"


def test_executor_retries_transient_idempotent_write_with_same_key():
    executor = SequenceExecutor(
        _result("failed", error={"category": "transient", "code": "ReadTimeout"}),
        _result("succeeded", occurred=True, output={"id": "created-1"}),
    )

    outcome = ResumableTaskExecutor(
        executor,
        redactor=TraceRedactor(fingerprint_key=b"test"),
        backoff=lambda _: None,
    ).execute(
        plan=_plan([("create", "write")]),
        skill=_skill([("create", "write")]),
        prior_results=[],
        checkpoint=lambda _: None,
    )

    assert outcome.status == "succeeded"
    assert len(executor.calls) == 2
    assert executor.calls[0].idempotency_key == executor.calls[1].idempotency_key


def test_executor_resolves_prior_step_output_bindings_at_runtime():
    skill = _skill([("lookup", "read"), ("create", "write")])
    skill.steps[1].input_bindings = {
        "body.employee_id": "steps.lookup.output.employee.id"
    }
    plan = _plan([("lookup", "read"), ("create", "write")])
    plan.steps[1].arguments = {
        "body": {
            "employee_id": {
                "$step_output": "steps.lookup.output.employee.id"
            }
        }
    }
    plan.steps[1].argument_sources = {}
    executor = SequenceExecutor(
        _result("succeeded", output={"employee": {"id": "E-9"}}),
        _result("succeeded", occurred=True, output={"id": "expense-1"}),
    )

    outcome = ResumableTaskExecutor(
        executor,
        redactor=TraceRedactor(fingerprint_key=b"test"),
        backoff=lambda _: None,
    ).execute(
        plan=plan,
        skill=skill,
        prior_results=[],
        checkpoint=lambda _: None,
    )

    assert outcome.status == "succeeded"
    assert executor.calls[1].arguments["body"]["employee_id"] == "E-9"


def test_executor_stops_after_business_failure_without_future_writes():
    executor = SequenceExecutor(
        _result("succeeded", occurred=True),
        _result("failed", error={"category": "business"}),
    )

    outcome = ResumableTaskExecutor(
        executor, redactor=TraceRedactor(fingerprint_key=b"test")
    ).execute(
        plan=_plan([("create-a", "write"), ("create-b", "write"), ("create-c", "write")]),
        skill=_skill([("create-a", "write"), ("create-b", "write"), ("create-c", "write")]),
        prior_results=[],
        checkpoint=lambda _: None,
    )

    assert len(executor.calls) == 2
    assert outcome.status == "partial_failure"


def test_executor_reports_unknown_for_unprotected_write_timeout():
    outcome = ResumableTaskExecutor(
        SequenceExecutor(
            _result("failed", error={"category": "transient", "code": "ReadTimeout"})
        ),
        redactor=TraceRedactor(fingerprint_key=b"test"),
    ).execute(
        plan=_plan([("create", "write")], protected=False),
        skill=_skill([("create", "write")]),
        prior_results=[],
        checkpoint=lambda _: None,
    )

    assert outcome.status == "unknown"


def test_checkpoint_receives_redacted_result():
    checkpoints = []
    executor = SequenceExecutor(
        _result(
            "succeeded",
            output={
                "authorization": "secret",
                "cookie": "secret",
                "password": "secret",
                "api_key": "secret",
            },
        )
    )

    ResumableTaskExecutor(
        executor, redactor=TraceRedactor(fingerprint_key=b"test")
    ).execute(
        plan=_plan([("read", "read")]),
        skill=_skill([("read", "read")]),
        prior_results=[],
        checkpoint=checkpoints.append,
    )

    assert set(checkpoints[0].normalized_output.values()) == {"[REDACTED]"}


def test_declared_compensation_runs_after_triggering_failure():
    compensation = {
        "trigger_step_id": "create-b",
        "compensates_step_ids": ["create-a"],
        "step": {
            "step_id": "delete-a",
            "name": "delete-a",
            "tool_id": "system:delete-a",
            "input_bindings": {},
            "side_effect": "write",
            "idempotency_key_template": "key:delete-a",
        },
    }
    executor = SequenceExecutor(
        _result("succeeded", occurred=True),
        _result("failed", error={"category": "business"}),
        _result("succeeded", occurred=True),
    )

    outcome = ResumableTaskExecutor(
        executor, redactor=TraceRedactor(fingerprint_key=b"test")
    ).execute(
        plan=_plan(
            [("create-a", "write"), ("create-b", "write")],
            compensation_step_ids=["delete-a"],
        ),
        skill=_skill(
            [("create-a", "write"), ("create-b", "write")],
            compensations=[compensation],
        ),
        prior_results=[],
        checkpoint=lambda _: None,
    )

    assert [call.step_id for call in executor.calls] == ["create-a", "create-b", "delete-a"]
    assert [item.step_id for item in outcome.compensation_results] == ["delete-a"]
