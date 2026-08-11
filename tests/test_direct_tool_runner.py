from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.command_center.direct_tool_runner import DirectToolRunner
from app.command_center.schemas import DirectToolPlan, ExecutionCommand, StepResult
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition, ToolParameter


def tool(*, tool_id="yifeng_mes:list", side_effect="read"):
    return ToolDefinition(
        tool_id=tool_id,
        system_code="yifeng_mes",
        operation_id=tool_id.partition(":")[2],
        method="GET",
        base_url="https://mes.test",
        path_template="/jeecg-boot/purchase/apply/list",
        content_type=None,
        side_effect=side_effect,
        credential_header="X-Access-Token",
        parameters=(
            ToolParameter("applyBy", "query", "string", False, "请购人"),
        ),
    )


def plan(*steps):
    return DirectToolPlan(
        status="matched",
        steps=list(steps),
        summary="query purchase applications",
    )


def step(tool_id="yifeng_mes:list", step_id="query"):
    return {
        "step_id": step_id,
        "tool_id": tool_id,
        "arguments": {"query": {"applyBy": "孟明佳"}},
        "reason": "按请购人查询",
    }


class RecordingExecutor:
    def __init__(self, statuses=("succeeded",)):
        self.statuses = iter(statuses)
        self.commands: list[ExecutionCommand] = []

    def execute(self, command):
        self.commands.append(command)
        status = next(self.statuses)
        now = datetime.now(UTC)
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status=status,
            started_at=now,
            ended_at=now,
            request_summary={
                "method": "GET",
                "path": "/jeecg-boot/purchase/apply/list",
                "headers": {"X-Access-Token": "private-secret"},
            },
            response_summary={
                "status_code": 200,
                "body": {"private": "raw-response"},
            },
            normalized_output={"success": True, "result": {"records": []}},
            error={} if status == "succeeded" else {"code": "ExternalFailure"},
        )


def test_direct_runner_executes_read_plan_and_retains_safe_evidence():
    catalog = ToolCatalog([tool()])
    executor = RecordingExecutor()
    run_id = uuid4()

    result = DirectToolRunner(catalog, executor).run(
        plan(step()),
        run_id=run_id,
    )

    assert result.status == "succeeded"
    assert result.outputs == {
        "query": {"success": True, "result": {"records": []}}
    }
    assert result.evidence == [
        {
            "step_id": "query",
            "tool_id": "yifeng_mes:list",
            "arguments": {"query": {"applyBy": "孟明佳"}},
            "status": "succeeded",
            "request_summary": {
                "method": "GET",
                "path": "/jeecg-boot/purchase/apply/list",
            },
            "response_summary": {"status_code": 200},
        }
    ]
    assert executor.commands[0].skill_id is None
    assert executor.commands[0].skill_version is None
    assert "private-secret" not in str(result.evidence)
    assert "raw-response" not in str(result.evidence)


def test_direct_runner_rejects_write_tool_before_executor_call():
    executor = RecordingExecutor()

    with pytest.raises(ValueError, match="read-only"):
        DirectToolRunner(ToolCatalog([tool(side_effect="write")]), executor).run(
            plan(step()),
            run_id=uuid4(),
        )

    assert executor.commands == []


def test_direct_runner_stops_after_failed_step():
    first = tool(tool_id="yifeng_mes:first")
    second = tool(tool_id="yifeng_mes:second")
    executor = RecordingExecutor(statuses=("failed", "succeeded"))

    result = DirectToolRunner(ToolCatalog([first, second]), executor).run(
        plan(step(first.tool_id, "first"), step(second.tool_id, "second")),
        run_id=uuid4(),
    )

    assert result.status == "failed"
    assert [command.step_id for command in executor.commands] == ["first"]
    assert result.outputs == {}
    assert result.evidence[0]["status"] == "failed"
