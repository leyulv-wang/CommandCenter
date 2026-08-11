from pathlib import Path
from datetime import UTC, datetime
import json

import pytest

from app.command_center.langchain_purchase_agents import (
    LangChainPurchaseAgents,
    PurchaseTrackingLimitError,
)
from app.command_center.model import build_chat_model_from_environment
from app.command_center.schemas import PurchaseTrackingScope, StepResult
from app.command_center.tool_catalog import ToolDefinition, ToolParameter


def test_chat_model_factory_reuses_existing_ai_environment(tmp_path: Path):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=https://model.test/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=secret\n"
        "AI_CONFIG_TIMEOUT_SECONDS=12\n",
        encoding="utf-8",
    )

    model = build_chat_model_from_environment(env_file)

    assert model.model_name == "test-model"
    assert model.openai_api_base == "https://model.test/v1"
    assert model.request_timeout == 12.0


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "infinity", "invalid"])
def test_chat_model_factory_rejects_invalid_timeout(tmp_path: Path, timeout: str):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=https://model.test/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=secret\n"
        f"AI_CONFIG_TIMEOUT_SECONDS={timeout}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timeout"):
        build_chat_model_from_environment(env_file)


def purchase_tool(
    tool_id: str,
    parameter_name: str,
    *,
    side_effect: str = "read",
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        system_code="yifeng_mes",
        operation_id=tool_id.rsplit(":", 1)[-1],
        method="GET",
        base_url="https://mes.test",
        path_template=f"/{tool_id.rsplit(':', 1)[-1]}",
        content_type=None,
        description=f"查询 {parameter_name}",
        side_effect=side_effect,
        parameters=(
            ToolParameter(
                name=parameter_name,
                location="query",
                type="string",
                required=True,
                description=parameter_name,
            ),
        ),
    )


def tracking_scope() -> PurchaseTrackingScope:
    application = {
        "id": "application-1",
        "applyNo": "CGSQ01",
        "applyBy": "孟明佳",
    }
    return PurchaseTrackingScope(
        goal="追踪所选采购申请",
        application=application,
        application_id="application-1",
        application_number="CGSQ01",
    )


class PurchaseExecutor:
    def __init__(self):
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        now = datetime.now(UTC)
        if command.tool_id.endswith("purchase_orders"):
            output = {
                "result": {
                    "records": [
                        {"id": "order-1", "orderNumber": "CGDD01"}
                    ]
                }
            }
        else:
            output = {
                "result": {
                    "records": [
                        {"id": "receipt-1", "orderNumber": "CGDD01"}
                    ]
                }
            }
        return StepResult(
            run_id=command.run_id,
            step_id=command.step_id,
            tool_id=command.tool_id,
            status="succeeded",
            started_at=now,
            ended_at=now,
            normalized_output=output,
            side_effect={"occurred": False},
        )


class ScriptedAgent:
    def __init__(self, name, tools, calls, *, repeat_first_tool=False):
        self.name = name
        self.tools = list(tools)
        self.calls = calls
        self.repeat_first_tool = repeat_first_tool

    def invoke(self, payload, config=None):
        self.calls.append(self.name)
        if self.name == "purchase_scope":
            return {"structured_response": tracking_scope()}
        if self.name == "purchase_trace":
            by_id = {
                tool.metadata["tool_id"]: tool
                for tool in self.tools
            }
            order_text = by_id["yifeng_mes:purchase_orders"].invoke(
                {"query": {"sourceCode": "CGSQ01"}}
            )
            if self.repeat_first_tool:
                by_id["yifeng_mes:purchase_orders"].invoke(
                    {"query": {"sourceCode": "CGSQ01"}}
                )
            order_number = json.loads(order_text)["output"]["result"]["records"][0][
                "orderNumber"
            ]
            by_id["yifeng_mes:receiving_records"].invoke(
                {"query": {"orderNumber": order_number}}
            )
            return {
                "structured_response": {
                    "status": "complete",
                    "summary": "已找到订单和收货记录",
                    "evidence_step_ids": ["tool_01", "tool_02"],
                }
            }
        return {
            "structured_response": {
                "status": "complete",
                "summary": "采购链路完整",
                "stages": [
                    {
                        "stage": "application",
                        "status": "completed",
                        "summary": "采购申请已找到",
                        "record_count": 1,
                        "records": [tracking_scope().application],
                        "evidence_step_ids": [],
                    }
                ],
            }
        }


def scripted_factory(calls, *, repeat_first_tool=False):
    def factory(*, model, tools, system_prompt, response_format, name):
        return ScriptedAgent(
            name,
            tools,
            calls,
            repeat_first_tool=repeat_first_tool,
        )

    return factory


def test_trace_agent_uses_previous_tool_output_for_next_call():
    calls = []
    executor = PurchaseExecutor()
    agents = LangChainPurchaseAgents(
        model=object(),
        tools=[
            purchase_tool("yifeng_mes:purchase_orders", "sourceCode"),
            purchase_tool("yifeng_mes:receiving_records", "orderNumber"),
        ],
        executor=executor,
        agent_factory=scripted_factory(calls),
    )

    run = agents.trace(tracking_scope())

    assert calls == ["purchase_trace"]
    assert [result.tool_id for result in run.step_results] == [
        "yifeng_mes:purchase_orders",
        "yifeng_mes:receiving_records",
    ]
    assert executor.commands[1].arguments["query"]["orderNumber"] == "CGDD01"
    assert run.output.status == "complete"


def test_purchase_agents_use_separate_langchain_roles():
    calls = []
    executor = PurchaseExecutor()
    agents = LangChainPurchaseAgents(
        model=object(),
        tools=[
            purchase_tool("yifeng_mes:purchase_orders", "sourceCode"),
            purchase_tool("yifeng_mes:receiving_records", "orderNumber"),
        ],
        executor=executor,
        agent_factory=scripted_factory(calls),
    )

    scope_run = agents.scope(tracking_scope().application)
    trace_run = agents.trace(scope_run.output)
    agents.verify(scope_run.output, trace_run.output, trace_run.step_results)

    assert calls == ["purchase_scope", "purchase_trace", "purchase_verify"]


def test_agent_adapter_rejects_write_tool_before_model_invocation():
    with pytest.raises(ValueError, match="read-only"):
        LangChainPurchaseAgents(
            model=object(),
            tools=[
                purchase_tool(
                    "yifeng_mes:purchase_orders",
                    "sourceCode",
                    side_effect="write",
                )
            ],
            executor=PurchaseExecutor(),
            agent_factory=scripted_factory([]),
        )


def test_agent_adapter_stops_after_tool_limit():
    agents = LangChainPurchaseAgents(
        model=object(),
        tools=[
            purchase_tool("yifeng_mes:purchase_orders", "sourceCode"),
            purchase_tool("yifeng_mes:receiving_records", "orderNumber"),
        ],
        executor=PurchaseExecutor(),
        agent_factory=scripted_factory([], repeat_first_tool=True),
        max_tool_calls=1,
    )

    with pytest.raises(PurchaseTrackingLimitError, match="Tool call limit"):
        agents.trace(tracking_scope())
