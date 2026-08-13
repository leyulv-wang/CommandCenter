from types import SimpleNamespace
from uuid import UUID, uuid4

from app.command_center.cross_system_testing import CrossSystemSkillTestService
from app.command_center.schemas import SkillDefinition
from app.command_center.testing import SkillRunResult
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition
from tests.test_command_center_schemas import valid_skill_payload


def cross_system_skill() -> SkillDefinition:
    payload = valid_skill_payload()
    payload["steps"] = [
        {
            "step_id": "read_mes",
            "name": "读取 MES 采购申请",
            "tool_id": "yifeng_mes:getPurchaseApply",
            "input_bindings": {"query.id": "task.content.record_id"},
            "output_bindings": {},
            "side_effect": "read",
        },
        {
            "step_id": "create_follow_up",
            "name": "创建采购跟进任务",
            "tool_id": "connected_system:createPurchaseFollowUp",
            "input_bindings": {
                "body.title": "task.content.title",
                "body.items": "steps.read_mes.output.items",
                "body.remark": "task.content.remark",
                "body.record_purpose": "task.content.record_purpose",
                "body.verification_run_id": "task.content.verification_run_id",
            },
            "output_bindings": {},
            "side_effect": "write",
            "idempotency_key_template": "{skill_id}:{source_object_id}:{step_id}",
        },
    ]
    return SkillDefinition.model_validate(payload)


def catalog(mes_side_effect="read") -> ToolCatalog:
    return ToolCatalog(
        [
            ToolDefinition(
                tool_id="yifeng_mes:getPurchaseApply", system_code="yifeng_mes",
                operation_id="getPurchaseApply", method="GET", base_url="https://mes.test",
                path_template="/purchase/apply", content_type=None, side_effect=mes_side_effect,
            ),
            ToolDefinition(
                tool_id="connected_system:createPurchaseFollowUp",
                system_code="connected_system", operation_id="createPurchaseFollowUp",
                method="POST", base_url="http://local.test",
                path_template="/api/purchase-follow-ups", content_type="application/json",
                side_effect="write",
            ),
        ]
    )


class Runner:
    def __init__(self):
        self.task = None

    def run(self, skill, task, *, run_id, literals=None):
        self.task = task
        return SkillRunResult(
            "succeeded",
            [],
            {"create_follow_up": {"follow_up_id": "FOLLOW-UP-0001"}},
        )


class Client:
    def __init__(self):
        self.deleted = []

    def get(self, url):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"follow_up_id": "FOLLOW-UP-0001", "record_purpose": "automated_test"},
        )

    def delete(self, url, headers):
        self.deleted.append((url, headers))
        return SimpleNamespace(raise_for_status=lambda: None)


class Verifier:
    def verify_result(self, skill, step_results, observed_state):
        return SimpleNamespace(status="passed", model_dump=lambda mode: {"status": "passed"})


def test_cross_system_test_marks_reads_verifies_and_cleans_local_record():
    runner = Runner()
    client = Client()
    service = CrossSystemSkillTestService(
        catalog=catalog(), runner=runner, verifier=Verifier(), client=client,
        local_base_url="http://local.test",
    )

    result = service.run(
        cross_system_skill(),
        {"category": "normal", "fixture": {"source_task": {"content": {"record_id": "MES-1", "title": "采购申请跟进", "remark": "验证"}}}},
    )

    assert result["status"] == "passed"
    assert result["cleanup_status"] == "succeeded"
    assert runner.task["content"]["record_purpose"] == "automated_test"
    verification_run_id = runner.task["content"]["verification_run_id"]
    assert UUID(verification_run_id)
    assert client.deleted[0][1]["X-Verification-Run-Id"] == verification_run_id


def test_cross_system_test_rejects_write_tool_outside_local_test_system():
    skill = cross_system_skill()
    service = CrossSystemSkillTestService(
        catalog=catalog(mes_side_effect="write"), runner=Runner(), verifier=Verifier(),
        client=Client(), local_base_url="http://local.test",
    )

    result = service.run(skill, {"category": "normal"})

    assert result["status"] == "failed"
    assert result["cleanup_status"] == "not_required"
