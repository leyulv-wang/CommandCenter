from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Generic, Protocol, TypeVar
from uuid import UUID, uuid4

from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError
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
    "scope.application 是系统已经读取并校验过的可信起点，不要再调用 Tool 复查该采购申请；"
    "优先从其业务关联字段继续查询下游记录。相同 Tool 与相同关联参数成功返回后不要重复调用。"
    "调用预算有限，应在订单、收货和入库三个下游阶段之间分配查询。"
    "在输出任何业务结论前必须至少实际调用一个查询 Tool；仅凭采购申请字段不能判断"
    "是否已经生成订单、收货或入库。"
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
    _results_by_key: dict[str, StepResult] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def execute_once(
        self,
        *,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        executor: ToolExecutorLike,
    ) -> StepResult:
        key = json.dumps(
            {"tool_id": tool.tool_id, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        # LangChain may schedule multiple Tool calls concurrently. Serializing the
        # small read-only MVP ledger guarantees unique step IDs and prevents an
        # identical successful query from consuming the bounded request budget.
        with self._lock:
            cached = self._results_by_key.get(key)
            if cached is not None:
                return cached
            if len(self.step_results) >= self.max_tool_calls:
                raise PurchaseTrackingLimitError("Tool call limit exceeded")
            step_id = f"tool_{len(self.step_results) + 1:02d}"
            result = executor.execute(
                ExecutionCommand(
                    run_id=self.run_id,
                    step_id=step_id,
                    tool_id=tool.tool_id,
                    arguments=arguments,
                    reason="采购追踪智能体选择了已授权的只读 Tool",
                )
            )
            self.step_results.append(result)
            self._results_by_key[key] = result
            return result


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
            schema=None,
        )
        payload = {
            "scope": scope.model_dump(mode="json"),
            "available_tools": [_compact_tool(tool) for tool in self.tools],
        }
        try:
            loop_result = self._invoke_agent(agent, payload)
        except GraphRecursionError:
            if not ledger.step_results:
                raise
            # The loop is intentionally bounded. Evidence already collected is
            # handed to the independent structured summarizer and verifier,
            # which decide whether it is complete, pending, or insufficient.
            loop_result = {"messages": []}
        if not ledger.step_results:
            loop_result = self._invoke_agent(
                agent,
                {
                    **payload,
                    "protocol_correction": (
                        "上一次没有调用任何 Tool，因此没有资格形成业务结论。"
                        "请先调用至少一个与当前目标相关的只读查询 Tool，再根据真实返回作答。"
                    ),
                },
            )
        if not ledger.step_results:
            raise PurchaseTrackingProtocolError(
                "purchase tracking requires Tool evidence before conclusion"
            )
        summary_agent = self._create_agent(
            name="purchase_trace_summary",
            tools=[],
            prompt=(
                "你是采购追踪执行结果整理智能体。只能根据已执行 Tool 的真实 StepResult "
                "生成结构化追踪草稿，不得添加未查询到的业务事实。"
            ),
            schema=PurchaseTrackingDraft,
        )
        output = self._invoke_structured(
            summary_agent,
            PurchaseTrackingDraft,
            {
                "scope": scope.model_dump(mode="json"),
                "tool_loop_summary": _last_message_content(loop_result),
                "step_results": [
                    result.model_dump(mode="json") for result in ledger.step_results
                ],
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
        schema: type[SchemaT] | None,
    ) -> Any:
        return self.agent_factory(
            model=self.model,
            tools=tools,
            system_prompt=prompt,
            response_format=ProviderStrategy(schema) if schema is not None else None,
            name=name,
        )

    def _invoke_structured(
        self,
        agent: Any,
        schema: type[SchemaT],
        payload: dict[str, Any],
    ) -> SchemaT:
        result = self._invoke_agent(agent, payload)
        if not isinstance(result, dict) or "structured_response" not in result:
            raise PurchaseTrackingProtocolError(
                "LangChain agent did not return a structured response"
            )
        return schema.model_validate(result["structured_response"])

    def _invoke_agent(
        self,
        agent: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
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
        if not isinstance(result, dict):
            raise PurchaseTrackingProtocolError("LangChain agent returned invalid state")
        return result

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
            result = ledger.execute_once(
                tool=tool,
                arguments=arguments,
                executor=self.executor,
            )
            return json.dumps(
                {
                    "step_id": result.step_id,
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


def _last_message_content(result: dict[str, Any]) -> str:
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        return "Tool Loop 已结束，业务结论必须以 StepResult 为准。"
    last = messages[-1]
    content = getattr(last, "content", None)
    if content is None and isinstance(last, dict):
        content = last.get("content")
    if isinstance(content, str):
        return content[:4_000]
    return json.dumps(content, ensure_ascii=False, default=str)[:4_000]
