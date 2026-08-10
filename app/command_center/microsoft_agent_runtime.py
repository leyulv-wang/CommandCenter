from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
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
from pydantic import BaseModel

from app.command_center.agent_runtime import (
    RuntimeCapabilities,
    RuntimeConfigurationError,
    RuntimeLimitError,
    RuntimeLimits,
    RuntimeRequest,
    RuntimeResult,
    RuntimeTelemetry,
    RuntimeTool,
    RuntimeToolEvent,
    RuntimeUsage,
    SchemaT,
)


AgentFactory = Callable[[RuntimeRequest[Any], tuple[RuntimeTool, ...], "_RunObserver"], Any]
_HARD_MAX_MODEL_CALLS = 6
_HARD_MAX_TOOL_CALLS = 8


class MicrosoftAgentFrameworkRuntime:
    capabilities = RuntimeCapabilities(tool_loop=True)

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
        _reject_active_event_loop()
        started = perf_counter()
        trace_id = str(uuid4())
        observer = _RunObserver(_bounded_limits(request.limits))
        tools = tuple(observer.wrap_tool(tool) for tool in request.tools)
        agent = self._agent_factory(request, tools, observer)

        async def execute() -> Any:
            session = agent.create_session()
            return await asyncio.wait_for(
                agent.run(
                    json.dumps(_jsonable(request.payload), ensure_ascii=False),
                    session=session,
                    options={"response_format": request.output_schema},
                    middleware=[observer.function_middleware],
                ),
                timeout=request.limits.timeout_seconds,
            )

        try:
            response = asyncio.run(execute())
        except asyncio.TimeoutError as exc:
            raise RuntimeLimitError("agent runtime timed out") from exc

        observer.raise_tool_error()
        output = request.output_schema.model_validate(response.value)
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
    def __init__(self, limits: RuntimeLimits) -> None:
        self.limits = limits
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
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def wrapped_async(*args: Any, **kwargs: Any) -> Any:
                self._reserve_tool_call()
                started = perf_counter()
                try:
                    value = await function(*args, **kwargs)
                except Exception:
                    self._record_event(function.__name__, "failed", started)
                    raise
                self._record_event(function.__name__, "succeeded", started)
                return value

            return wrapped_async

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._reserve_tool_call()
            started = perf_counter()
            try:
                value = function(*args, **kwargs)
            except Exception:
                self._record_event(function.__name__, "failed", started)
                raise
            self._record_event(function.__name__, "succeeded", started)
            return value

        return wrapped

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


def _bounded_limits(limits: RuntimeLimits) -> RuntimeLimits:
    return RuntimeLimits(
        max_model_calls=min(limits.max_model_calls, _HARD_MAX_MODEL_CALLS),
        max_tool_calls=min(limits.max_tool_calls, _HARD_MAX_TOOL_CALLS),
        timeout_seconds=limits.timeout_seconds,
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
