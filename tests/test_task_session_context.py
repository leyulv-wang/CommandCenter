from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.command_center.direct_tool_runner import DirectToolRunner
from app.command_center.redaction import TraceRedactor
from app.command_center.schemas import DirectToolPlan, StepResult
from app.command_center.task_session_context import (
    ReadOnlyTaskContextResolver,
)
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition


def _tool(side_effect="read"):
    return ToolDefinition(
        tool_id=f"hr:{side_effect}",
        system_code="hr",
        operation_id=side_effect,
        method="GET",
        base_url="http://hr",
        path_template=f"/{side_effect}",
        content_type=None,
        side_effect=side_effect,
    )


class PlanningAgents:
    def __init__(self, tool_id):
        self.tool_id = tool_id

    def plan_tool_request(self, **_):
        return DirectToolPlan.model_validate(
            {
                "status": "matched",
                "steps": [
                    {
                        "step_id": "employee",
                        "tool_id": self.tool_id,
                        "arguments": {},
                        "reason": "读取员工资料",
                    }
                ],
                "summary": "读取资料",
            }
        )


class SuccessfulExecutor:
    def execute(self, command):
        now = datetime.now(UTC)
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status="succeeded",
            started_at=now,
            ended_at=now,
            normalized_output={
                "id": "E-9",
                "department": "研发",
                "authorization": "secret",
            },
        )


def test_context_resolver_rejects_agent_write_plan():
    read_tool, write_tool = _tool("read"), _tool("write")
    catalog = ToolCatalog([read_tool, write_tool])
    resolver = ReadOnlyTaskContextResolver(
        agents=PlanningAgents(write_tool.tool_id),
        tools=lambda: [read_tool, write_tool],
        runner=DirectToolRunner(catalog, SuccessfulExecutor()),
        redactor=TraceRedactor(fingerprint_key=b"test"),
    )

    with pytest.raises(ValueError, match="read-only"):
        resolver.resolve(goal="读取员工资料", selected_object={"id": "E-9"})


def test_context_resolver_returns_redacted_normalized_evidence():
    read_tool = _tool("read")
    catalog = ToolCatalog([read_tool])
    resolver = ReadOnlyTaskContextResolver(
        agents=PlanningAgents(read_tool.tool_id),
        tools=lambda: [read_tool],
        runner=DirectToolRunner(catalog, SuccessfulExecutor()),
        redactor=TraceRedactor(fingerprint_key=b"test"),
    )

    evidence = resolver.resolve(
        goal="读取员工资料", selected_object={"id": "E-9"}
    )

    assert evidence[0].tool_id == read_tool.tool_id
    assert evidence[0].object_id == "E-9"
    assert evidence[0].output["department"] == "研发"
    assert evidence[0].output["authorization"] == "[REDACTED]"
