from datetime import UTC, datetime
from uuid import uuid4

from app.command_center.schemas import SkillDefinition, StepResult
from app.command_center.testing import SkillRunner
from tests.test_command_center_schemas import valid_skill_payload


class RecordingExecutor:
    def __init__(self, fail_step=None):
        self.commands = []
        self.fail_step = fail_step

    def execute(self, command):
        self.commands.append(command)
        failed = command.step_id == self.fail_step
        output = (
            {}
            if failed
            else {"data": {"id": "WORKFLOW-0001"}}
            if command.step_id == "create_purchase"
            else {"status": "processing"}
        )
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status="failed" if failed else "succeeded",
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            normalized_output=output,
            error={"message": "failed"} if failed else {},
        )


def two_step_skill() -> SkillDefinition:
    payload = valid_skill_payload()
    payload["steps"] = [
        {
            "step_id": "create_purchase",
            "name": "创建采购",
            "tool_id": "connected_system:start_workflow",
            "input_bindings": {
                "body.item_name": "task.content.item_name",
                "body.quantity": "task.content.quantity",
            },
            "output_bindings": {},
            "side_effect": "write",
            "idempotency_key_template": "fixed",
        },
        {
            "step_id": "link_purchase",
            "name": "回写单号",
            "tool_id": "onboarding_system:link_purchase",
            "input_bindings": {
                "path.task_id": "task.task_id",
                "body.purchase_request_id": "steps.create_purchase.output.data.id",
            },
            "output_bindings": {},
            "side_effect": "write",
            "idempotency_key_template": "fixed",
        },
    ]
    return SkillDefinition.model_validate(payload)


def test_skill_runner_resolves_cross_step_output_and_stable_idempotency():
    executor = RecordingExecutor()
    runner = SkillRunner(executor)
    task = {
        "system_code": "onboarding_system",
        "task_id": "OFFICE-TASK-0001",
        "content": {"item_name": "签字笔", "quantity": 10},
    }
    run_id = uuid4()
    skill = two_step_skill()

    first = runner.run(skill, task, run_id=run_id)
    second = runner.run(skill, task, run_id=uuid4())

    assert first.status == "succeeded"
    assert executor.commands[1].arguments == {
        "path": {"task_id": "OFFICE-TASK-0001"},
        "body": {"purchase_request_id": "WORKFLOW-0001"},
    }
    assert executor.commands[0].idempotency_key == executor.commands[2].idempotency_key
    assert second.status == "succeeded"


def test_skill_runner_stops_after_failed_write():
    executor = RecordingExecutor(fail_step="create_purchase")

    result = SkillRunner(executor).run(
        two_step_skill(),
        {
            "system_code": "onboarding_system",
            "task_id": "OFFICE-TASK-0001",
            "content": {"item_name": "签字笔", "quantity": 10},
        },
        run_id=uuid4(),
    )

    assert result.status == "failed"
    assert len(executor.commands) == 1
