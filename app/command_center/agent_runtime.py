from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Generic, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)
RuntimeTool = Callable[..., Any]


@dataclass(frozen=True)
class RuntimeCapabilities:
    tool_loop: bool


@dataclass(frozen=True)
class RuntimeLimits:
    max_model_calls: int = 6
    max_tool_calls: int = 8
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class RuntimeRequest(Generic[SchemaT]):
    role: str
    instructions: str
    payload: Any
    output_schema: type[SchemaT]
    tools: tuple[RuntimeTool, ...] = ()
    session_id: str | None = None
    limits: RuntimeLimits = field(default_factory=RuntimeLimits)


@dataclass(frozen=True)
class RuntimeUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class RuntimeToolEvent:
    name: str
    status: str
    duration_ms: float


@dataclass(frozen=True)
class RuntimeTelemetry:
    trace_id: str
    session_id: str | None
    runtime: str
    provider: str
    model: str | None
    role: str
    model_calls: int
    tool_events: tuple[RuntimeToolEvent, ...]
    usage: RuntimeUsage
    duration_ms: float


@dataclass(frozen=True)
class RuntimeResult(Generic[SchemaT]):
    output: SchemaT
    telemetry: RuntimeTelemetry


class AgentRuntime(Protocol):
    capabilities: RuntimeCapabilities
    default_limits: RuntimeLimits

    def run_structured(self, request: RuntimeRequest[SchemaT]) -> RuntimeResult[SchemaT]:
        raise NotImplementedError


class RuntimeLimitError(RuntimeError):
    pass


class RuntimeConfigurationError(RuntimeError):
    pass


class LegacyStructuredModelRuntime:
    capabilities = RuntimeCapabilities(tool_loop=False)
    default_limits = RuntimeLimits()

    def __init__(self, model: Any):
        self._model = model

    def run_structured(self, request: RuntimeRequest[SchemaT]) -> RuntimeResult[SchemaT]:
        if request.tools:
            raise RuntimeConfigurationError("legacy runtime does not execute tools")
        started = perf_counter()
        output = self._model.generate(
            request.output_schema,
            request.instructions,
            request.payload,
        )
        telemetry = RuntimeTelemetry(
            trace_id=str(uuid4()),
            session_id=request.session_id,
            runtime="legacy_structured_model",
            provider="structured_model",
            model=None,
            role=request.role,
            model_calls=1,
            tool_events=(),
            usage=RuntimeUsage(),
            duration_ms=(perf_counter() - started) * 1000,
        )
        return RuntimeResult(output=output, telemetry=telemetry)
