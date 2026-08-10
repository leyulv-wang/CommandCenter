from __future__ import annotations

import asyncio
import inspect
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from functools import wraps
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from agent_framework import (
    ChatContext,
    FunctionInvocationContext,
    MiddlewareTermination,
    chat_middleware as framework_chat_middleware,
    function_middleware as framework_function_middleware,
)
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.command_center.agent_runtime import (
    RuntimeCapabilities,
    RuntimeConfigurationError,
    RuntimeFailureCategory,
    RuntimeFailureSummary,
    RuntimeLimitError,
    RuntimeLimits,
    RuntimeRequest,
    RuntimeResult,
    RuntimeTelemetry,
    RuntimeTool,
    RuntimeToolEvent,
    RuntimeUsage,
    SchemaT,
    attach_runtime_failure,
)


AgentFactory = Callable[[RuntimeRequest[Any], tuple[RuntimeTool, ...], "_RunObserver"], Any]
_HARD_MAX_MODEL_CALLS = 6
_HARD_MAX_TOOL_CALLS = 8


class MicrosoftAgentFrameworkRuntime:
    capabilities = RuntimeCapabilities(tool_loop=True)

    @classmethod
    def from_openai_compatible(
        cls,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> "MicrosoftAgentFrameworkRuntime":
        async_client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_seconds,
        )
        client = OpenAIChatCompletionClient(async_client=async_client, model=model)

        def agent_factory(
            request: RuntimeRequest[Any],
            tools: tuple[RuntimeTool, ...],
            observer: _RunObserver,
        ) -> Any:
            return client.as_agent(
                name=request.role,
                instructions=request.instructions,
                tools=list(tools),
                default_options={"temperature": 0},
                middleware=[observer.chat_middleware],
            )

        return cls(
            agent_factory=agent_factory,
            provider="openai_compatible",
            model=model,
            default_limits=RuntimeLimits(timeout_seconds=timeout_seconds),
        )

    def __init__(
        self,
        agent_factory: AgentFactory,
        provider: str,
        model: str,
        default_limits: RuntimeLimits | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._provider = provider
        self._model = model
        self.default_limits = _bounded_limits(default_limits or RuntimeLimits())

    def run_structured(self, request: RuntimeRequest[SchemaT]) -> RuntimeResult[SchemaT]:
        started = perf_counter()
        trace_id = str(uuid4())
        _reject_active_event_loop()
        limits = _bounded_limits(
            request.limits, timeout_ceiling=self.default_limits.timeout_seconds
        )
        if request.requires_tool_evidence and not request.tools:
            raise RuntimeConfigurationError(
                "required tool evidence requires at least one tool"
            )
        observer = _RunObserver(
            limits,
            requires_tool_evidence=request.requires_tool_evidence,
            response_format=request.output_schema,
        )
        tools = tuple(observer.wrap_tool(tool) for tool in request.tools)
        agent_request = request
        if request.requires_tool_evidence:
            agent_request = replace(
                request,
                instructions=(
                    request.instructions
                    + "\n在生成最终答案前，必须先调用至少一个所提供的工具获取本次请求的事实证据；"
                    "不得根据工具名称猜测结果。"
                ),
            )
        try:
            agent = self._agent_factory(agent_request, tools, observer)
        except Exception as exc:
            _attach_failure(
                exc,
                RuntimeFailureCategory.MODEL_OR_PROTOCOL_ERROR,
                request,
                observer,
                trace_id,
                started,
                self._provider,
                self._model,
            )
            raise

        async def execute() -> Any:
            session = agent.create_session()
            return await asyncio.wait_for(
                agent.run(
                    json.dumps(_jsonable(request.payload), ensure_ascii=False),
                    session=session,
                    options={"response_format": request.output_schema},
                    middleware=[observer.function_middleware],
                ),
                timeout=limits.timeout_seconds,
            )

        try:
            response = asyncio.run(execute())
        except asyncio.TimeoutError as exc:
            error = RuntimeLimitError("agent runtime timed out")
            _attach_failure(
                error,
                RuntimeFailureCategory.TIMEOUT,
                request,
                observer,
                trace_id,
                started,
                self._provider,
                self._model,
            )
            raise error from exc
        except Exception as exc:
            category = (
                RuntimeFailureCategory.LIMIT_EXCEEDED
                if isinstance(exc, RuntimeLimitError)
                else RuntimeFailureCategory.MODEL_OR_PROTOCOL_ERROR
            )
            _attach_failure(
                exc,
                category,
                request,
                observer,
                trace_id,
                started,
                self._provider,
                self._model,
            )
            raise

        try:
            observer.raise_tool_error()
        except Exception as exc:
            category = (
                RuntimeFailureCategory.LIMIT_EXCEEDED
                if isinstance(exc, RuntimeLimitError)
                else RuntimeFailureCategory.TOOL_ERROR
            )
            _attach_failure(
                exc,
                category,
                request,
                observer,
                trace_id,
                started,
                self._provider,
                self._model,
            )
            raise
        try:
            output = request.output_schema.model_validate(response.value)
        except Exception as exc:
            _attach_failure(
                exc,
                RuntimeFailureCategory.MODEL_OR_PROTOCOL_ERROR,
                request,
                observer,
                trace_id,
                started,
                self._provider,
                self._model,
            )
            raise
        usage_details = getattr(response, "usage_details", None)
        telemetry = RuntimeTelemetry(
            trace_id=trace_id,
            session_id=request.session_id,
            runtime="microsoft_agent_framework",
            provider=self._provider,
            model=self._model,
            role=request.role,
            model_calls=observer.model_calls,
            tool_events=tuple(observer.events),
            usage=RuntimeUsage(
                input_tokens=_usage_value(usage_details, "input_token_count"),
                output_tokens=_usage_value(usage_details, "output_token_count"),
                total_tokens=_usage_value(usage_details, "total_token_count"),
            ),
            duration_ms=_elapsed_ms(started),
        )
        return RuntimeResult(output=output, telemetry=telemetry)


class _RunObserver:
    def __init__(
        self,
        limits: RuntimeLimits,
        *,
        requires_tool_evidence: bool = False,
        response_format: type[BaseModel] | None = None,
    ) -> None:
        self.limits = limits
        self.requires_tool_evidence = requires_tool_evidence
        self.response_format = response_format
        self.model_calls = 0
        self.tool_calls = 0
        self.events: list[RuntimeToolEvent] = []
        self._tool_error: Exception | None = None
        self._lock = Lock()

    def before_model_call(self) -> None:
        if self.model_calls >= self.limits.max_model_calls:
            raise RuntimeLimitError("agent runtime exceeded model call limit")
        self.model_calls += 1

    @framework_chat_middleware
    async def chat_middleware(
        self, context: ChatContext, call_next: Callable[[], Any]
    ) -> None:
        self.before_model_call()
        if self.requires_tool_evidence:
            if self.tool_calls == 0:
                context.options.pop("response_format", None)
            else:
                context.options["response_format"] = self.response_format
        await call_next()

    @framework_function_middleware
    async def function_middleware(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await call_next()
        except Exception as exc:
            self._record_tool_error(exc)
            raise MiddlewareTermination("tool invocation failed") from exc

    def wrap_tool(self, function: RuntimeTool) -> RuntimeTool:
        name = _callable_name(function)
        if _is_async_callable(function):

            @wraps(function)
            async def wrapped_async(*args: Any, **kwargs: Any) -> Any:
                self._reserve_tool_call()
                started = perf_counter()
                try:
                    value = function(*args, **kwargs)
                    if inspect.isawaitable(value):
                        value = await value
                except Exception:
                    self._record_event(name, "failed", started)
                    raise
                self._record_event(name, "succeeded", started)
                return value

            _set_callable_name(wrapped_async, name)
            return wrapped_async

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._reserve_tool_call()
            started = perf_counter()
            try:
                value = function(*args, **kwargs)
            except Exception:
                self._record_event(name, "failed", started)
                raise
            if inspect.isawaitable(value):
                return self._await_tool_result(value, name, started)
            self._record_event(name, "succeeded", started)
            return value

        _set_callable_name(wrapped, name)
        return wrapped

    async def _await_tool_result(
        self, value: Awaitable[Any], name: str, started: float
    ) -> Any:
        try:
            result = await value
        except Exception:
            self._record_event(name, "failed", started)
            raise
        self._record_event(name, "succeeded", started)
        return result

    def _reserve_tool_call(self) -> None:
        with self._lock:
            if self.tool_calls >= self.limits.max_tool_calls:
                raise RuntimeLimitError("agent runtime exceeded tool call limit")
            self.tool_calls += 1

    def _record_event(self, name: str, status: str, started: float) -> None:
        event = RuntimeToolEvent(name, status, _elapsed_ms(started))
        with self._lock:
            self.events.append(event)

    def _record_tool_error(self, error: Exception) -> None:
        with self._lock:
            if self._tool_error is None:
                self._tool_error = error

    def raise_tool_error(self) -> None:
        with self._lock:
            error = self._tool_error
        if error is not None:
            raise error


def _reject_active_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeConfigurationError(
        "synchronous AgentRuntime cannot run inside an active event loop"
    )


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _usage_value(usage_details: Any, name: str) -> int | None:
    if usage_details is None:
        return None
    if isinstance(usage_details, Mapping):
        return usage_details.get(name)
    return getattr(usage_details, name, None)


def _callable_name(function: RuntimeTool) -> str:
    name = getattr(function, "__name__", None)
    if isinstance(name, str) and name:
        return name
    return type(function).__name__


def _is_async_callable(function: RuntimeTool) -> bool:
    return inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(
        getattr(function, "__call__", None)
    )


def _set_callable_name(function: RuntimeTool, name: str) -> None:
    function.__name__ = name
    function.__qualname__ = name


def _bounded_limits(
    limits: RuntimeLimits, *, timeout_ceiling: float | None = None
) -> RuntimeLimits:
    if (
        not isinstance(limits.max_model_calls, int)
        or isinstance(limits.max_model_calls, bool)
        or limits.max_model_calls <= 0
        or not isinstance(limits.max_tool_calls, int)
        or isinstance(limits.max_tool_calls, bool)
        or limits.max_tool_calls <= 0
        or not math.isfinite(limits.timeout_seconds)
        or limits.timeout_seconds <= 0
    ):
        raise RuntimeConfigurationError(
            "runtime limits require positive call counts and a finite positive timeout"
        )
    timeout_seconds = limits.timeout_seconds
    if timeout_ceiling is not None:
        if not math.isfinite(timeout_ceiling) or timeout_ceiling <= 0:
            raise RuntimeConfigurationError("runtime limits require a finite timeout")
        timeout_seconds = min(timeout_seconds, timeout_ceiling)
    return RuntimeLimits(
        max_model_calls=min(limits.max_model_calls, _HARD_MAX_MODEL_CALLS),
        max_tool_calls=min(limits.max_tool_calls, _HARD_MAX_TOOL_CALLS),
        timeout_seconds=timeout_seconds,
    )


def _attach_failure(
    error: Exception,
    category: RuntimeFailureCategory,
    request: RuntimeRequest[Any],
    observer: _RunObserver,
    trace_id: str,
    started: float,
    provider: str,
    model: str,
) -> None:
    telemetry = RuntimeTelemetry(
        trace_id=trace_id,
        session_id=request.session_id,
        runtime="microsoft_agent_framework",
        provider=provider,
        model=model,
        role=request.role,
        model_calls=observer.model_calls,
        tool_events=tuple(observer.events),
        usage=RuntimeUsage(),
        duration_ms=_elapsed_ms(started),
    )
    attach_runtime_failure(
        error,
        RuntimeFailureSummary(failure_category=category, telemetry=telemetry),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
