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


def test_skill_runner_scopes_idempotency_to_selected_business_record():
    executor = RecordingExecutor()
    runner = SkillRunner(executor)
    skill = two_step_skill()

    for selected_id in ("MES-APPLICATION-1", "MES-APPLICATION-2"):
        runner.run(
            skill,
            {
                "system_code": "command_center",
                "task_id": "user-request",
                "content": {
                    "item_name": "material",
                    "quantity": 10,
                    "selected_record": {"id": selected_id},
                },
            },
            run_id=uuid4(),
        )

    first_create = executor.commands[0]
    second_create = executor.commands[2]
    assert first_create.idempotency_key != second_create.idempotency_key
    assert "MES-APPLICATION-1" in first_create.idempotency_key
    assert "MES-APPLICATION-2" in second_create.idempotency_key


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


def test_skill_runner_omits_unprovided_optional_inputs_from_tool_arguments():
    skill = SkillDefinition.model_validate(
        {
            "skill_id": str(uuid4()),
            "version": 1,
            "name": "查询采购申请列表",
            "description": "按可选条件分页查询",
            "status": "verified_candidate",
            "trigger_examples": ["查询采购申请"],
            "source_recording_id": str(uuid4()),
            "inputs": [
                {
                    "name": "applyNo",
                    "type": "string",
                    "description": "申请单号",
                    "required": False,
                },
                {
                    "name": "pageNo",
                    "type": "integer",
                    "description": "页码",
                    "required": True,
                },
                {
                    "name": "pageSize",
                    "type": "integer",
                    "description": "每页条数",
                    "required": True,
                },
            ],
            "outputs": [],
            "steps": [
                {
                    "step_id": "query",
                    "name": "查询",
                    "tool_id": "mes:list",
                    "input_bindings": {
                        "query.applyNo": "task.content.applyNo",
                        "query.pageNo": "task.content.pageNo",
                        "query.pageSize": "task.content.pageSize",
                    },
                    "side_effect": "read",
                }
            ],
            "success_conditions": [],
        }
    )
    executor = RecordingExecutor()

    result = SkillRunner(executor).run(
        skill,
        {
            "system_code": "command_center",
            "task_id": "user-request",
            "content": {"pageNo": 1, "pageSize": 10},
        },
        run_id=uuid4(),
    )

    assert result.status == "succeeded"
    assert executor.commands[0].arguments == {
        "query": {"pageNo": 1, "pageSize": 10}
    }


def test_skill_runner_builds_lists_from_numeric_binding_segments():
    skill = two_step_skill()
    skill.steps = [skill.steps[0]]
    skill.steps[0].input_bindings = {
        "body.items.0.material_code": "task.content.first_code",
        "body.items.0.quantity": "task.content.first_quantity",
        "body.items.1.material_code": "task.content.second_code",
        "body.items.1.quantity": "task.content.second_quantity",
    }
    executor = RecordingExecutor()

    SkillRunner(executor).run(
        skill,
        {
            "system_code": "connected_system",
            "task_id": "array-binding-test",
            "content": {
                "first_code": "M001",
                "first_quantity": 100,
                "second_code": "M002",
                "second_quantity": 50,
            },
        },
        run_id=uuid4(),
    )

    assert executor.commands[0].arguments == {
        "body": {
            "items": [
                {"material_code": "M001", "quantity": 100},
                {"material_code": "M002", "quantity": 50},
            ]
        }
    }


def test_skill_runner_builds_lists_from_bracketed_binding_segments():
    skill = two_step_skill()
    skill.steps = [skill.steps[0]]
    skill.steps[0].input_bindings = {
        "body.items[0].material_code": "task.content.first_code",
        "body.items[0].quantity": "task.content.first_quantity",
        "body.items[1].material_code": "task.content.second_code",
        "body.items[1].quantity": "task.content.second_quantity",
    }
    executor = RecordingExecutor()

    SkillRunner(executor).run(
        skill,
        {
            "system_code": "connected_system",
            "task_id": "bracket-array-binding-test",
            "content": {
                "first_code": "M001",
                "first_quantity": 100,
                "second_code": "M002",
                "second_quantity": 50,
            },
        },
        run_id=uuid4(),
    )

    assert executor.commands[0].arguments == {
        "body": {
            "items": [
                {"material_code": "M001", "quantity": 100},
                {"material_code": "M002", "quantity": 50},
            ]
        }
    }
