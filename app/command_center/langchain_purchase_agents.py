from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Protocol, TypeVar
from uuid import UUID, uuid4

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from app.command_center.schemas import (
    ExecutionCommand,
    PurchaseProgressResult,
    PurchaseTrackingDraft,
    PurchaseTrackingScope,
    StepResult,
)
from app.command_center.tool_catalog import ToolDefinition, validate_tool_arguments


SchemaT = TypeVar("SchemaT", bound=BaseModel)
AgentFactory = Callable[..., Any]

_SCOPE_PROMPT = (
    "你是采购追踪任务理解智能体。只根据系统提供的可信采购申请记录定义追踪目标。"
    "必须逐字保留记录中的 id 和 applyNo，不得编造或替换内部编号。"
)
_TRACE_PROMPT = (
    "你是采购进度追踪执行智能体。使用允许的只读 Tool，从采购申请逐步查询采购订单、"
    "收货和入库证据。每次读取 Tool 返回后再决定下一步。允许不存在订单或收货记录，"
    "这属于业务尚未推进；不得调用写操作，不得编造关联字段或结果。"
)
_VERIFY_PROMPT = (
    "你是采购追踪证据验证与总结智能体。核对采购申请、订单、收货和入库记录的关联，"
    "保留全部相关记录。区分业务尚未推进、证据不完整和技术失败，不得根据 HTTP 成功"
    "状态臆造业务结论。"
)


class PurchaseTrackingLimitError(RuntimeError):
    pass


class PurchaseTrackingProtocolError(RuntimeError):
    pass


class ToolExecutorLike(Protocol):
    def execute(self, command: ExecutionCommand) -> StepResult: ...


class AgentToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: dict[str, Any] = Field(default_factory=dict)
    path: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)


@dataclass
class PurchaseAgentRun(Generic[SchemaT]):
    output: SchemaT
    step_results: list[StepResult] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _ToolRunLedger:
    run_id: UUID
    max_tool_calls: int
    step_results: list[StepResult] = field(default_factory=list)

    def next_step_id(self) -> str:
        if len(self.step_results) >= self.max_tool_calls:
            raise PurchaseTrackingLimitError("Tool call limit exceeded")
        return f"tool_{len(self.step_results) + 1:02d}"


class LangChainPurchaseAgents:
    def __init__(
        self,
        *,
        model: Any,
        tools: list[ToolDefinition],
        executor: ToolExecutorLike,
        agent_factory: AgentFactory = create_agent,
        max_tool_calls: int = 8,
        recursion_limit: int = 20,
    ) -> None:
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        if recursion_limit < 2:
            raise ValueError("recursion_limit must be at least two")
        for tool in tools:
            validate_tool_arguments(tool, {})
        self.model = model
        self.tools = tuple(tools)
        self.executor = executor
        self.agent_factory = agent_factory
        self.max_tool_calls = max_tool_calls
        self.recursion_limit = recursion_limit

    def scope(self, application: dict[str, Any]) -> PurchaseAgentRun[PurchaseTrackingScope]:
        agent = self._create_agent(
            name="purchase_scope",
            tools=[],
            prompt=_SCOPE_PROMPT,
            schema=PurchaseTrackingScope,
        )
        output = self._invoke_structured(
            agent,
            PurchaseTrackingScope,
            {
                "goal": "追踪所选采购申请的采购订单、收货和入库进度",
                "trusted_application": application,
            },
        )
        return PurchaseAgentRun(output=output)

    def trace(
        self,
        scope: PurchaseTrackingScope,
    ) -> PurchaseAgentRun[PurchaseTrackingDraft]:
        ledger = _ToolRunLedger(run_id=uuid4(), max_tool_calls=self.max_tool_calls)
        agent_tools = [self._agent_tool(tool, ledger) for tool in self.tools]
        agent = self._create_agent(
            name="purchase_trace",
            tools=agent_tools,
            prompt=_TRACE_PROMPT,
            schema=PurchaseTrackingDraft,
        )
        output = self._invoke_structured(
            agent,
            PurchaseTrackingDraft,
            {
                "scope": scope.model_dump(mode="json"),
                "available_tools": [_compact_tool(tool) for tool in self.tools],
            },
        )
        return PurchaseAgentRun(
            output=output,
            step_results=list(ledger.step_results),
            events=[_safe_tool_event(result) for result in ledger.step_results],
        )

    def verify(
        self,
        scope: PurchaseTrackingScope,
        draft: PurchaseTrackingDraft,
        step_results: list[StepResult],
    ) -> PurchaseAgentRun[PurchaseProgressResult]:
        agent = self._create_agent(
            name="purchase_verify",
            tools=[],
            prompt=_VERIFY_PROMPT,
            schema=PurchaseProgressResult,
        )
        output = self._invoke_structured(
            agent,
            PurchaseProgressResult,
            {
                "scope": scope.model_dump(mode="json"),
                "draft": draft.model_dump(mode="json"),
                "step_results": [
                    result.model_dump(mode="json") for result in step_results
                ],
            },
        )
        return PurchaseAgentRun(output=output)

    def _create_agent(
        self,
        *,
        name: str,
        tools: list[Any],
        prompt: str,
        schema: type[SchemaT],
    ) -> Any:
        return self.agent_factory(
            model=self.model,
            tools=tools,
            system_prompt=prompt,
            response_format=ToolStrategy(schema),
            name=name,
        )

    def _invoke_structured(
        self,
        agent: Any,
        schema: type[SchemaT],
        payload: dict[str, Any],
    ) -> SchemaT:
        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, default=str),
                    }
                ]
            },
            config={"recursion_limit": self.recursion_limit},
        )
        if not isinstance(result, dict) or "structured_response" not in result:
            raise PurchaseTrackingProtocolError(
                "LangChain agent did not return a structured response"
            )
        return schema.model_validate(result["structured_response"])

    def _agent_tool(
        self,
        tool: ToolDefinition,
        ledger: _ToolRunLedger,
    ) -> StructuredTool:
        def execute(
            query: dict[str, Any] | None = None,
            path: dict[str, Any] | None = None,
            body: dict[str, Any] | None = None,
        ) -> str:
            arguments = {
                "query": query or {},
                "path": path or {},
                "body": body or {},
            }
            validate_tool_arguments(tool, arguments)
            step_id = ledger.next_step_id()
            result = self.executor.execute(
                ExecutionCommand(
                    run_id=ledger.run_id,
                    step_id=step_id,
                    tool_id=tool.tool_id,
                    arguments=arguments,
                    reason="采购追踪智能体选择了已授权的只读 Tool",
                )
            )
            ledger.step_results.append(result)
            return json.dumps(
                {
                    "step_id": step_id,
                    "status": result.status,
                    "output": result.normalized_output,
                    "error": result.error,
                },
                ensure_ascii=False,
                default=str,
            )

        return StructuredTool.from_function(
            func=execute,
            name=_safe_tool_name(tool),
            description=_tool_description(tool),
            args_schema=AgentToolArguments,
            metadata={"tool_id": tool.tool_id},
        )


def _safe_tool_name(tool: ToolDefinition) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", tool.operation_id).strip("_").lower()
    digest = hashlib.sha256(tool.tool_id.encode("utf-8")).hexdigest()[:8]
    return f"mes_{digest}_{slug[:40]}"


def _tool_description(tool: ToolDefinition) -> str:
    parameters = [
        {
            "name": item.name,
            "location": item.location,
            "required": item.required,
            "description": item.description,
        }
        for item in tool.parameters
        if item.location in {"query", "path", "body"}
    ]
    return (
        f"{tool.description or tool.operation_id}. Internal Tool ID: {tool.tool_id}. "
        f"Allowed arguments: {json.dumps(parameters, ensure_ascii=False)}"
    )


def _compact_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "tool_id": tool.tool_id,
        "description": tool.description,
        "parameters": [
            {
                "name": item.name,
                "location": item.location,
                "required": item.required,
                "description": item.description,
            }
            for item in tool.parameters
            if item.location in {"query", "path", "body"}
        ],
    }


def _safe_tool_event(result: StepResult) -> dict[str, Any]:
    return {
        "step_id": result.step_id,
        "tool_id": result.tool_id,
        "status": result.status,
        "request_summary": {
            key: result.request_summary[key]
            for key in ("method", "path")
            if key in result.request_summary
        },
        "response_summary": {
            key: result.response_summary[key]
            for key in ("status_code",)
            if key in result.response_summary
        },
    }
