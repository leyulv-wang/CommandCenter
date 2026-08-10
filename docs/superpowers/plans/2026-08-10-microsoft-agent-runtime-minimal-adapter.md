# Microsoft Agent Runtime Minimal Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a replaceable Agent Runtime boundary and migrate only `AgentSuite.match_request` to a Microsoft Agent Framework tool loop with call-scoped short-term memory.

**Architecture:** Keep `StructuredModel` for every existing agent role and inject a separate synchronous `AgentRuntime` only into request matching. A capability flag lets the legacy adapter receive the current full Skill payload while the Microsoft adapter receives two call-scoped read-only functions and lets the model discover Skill details dynamically. Microsoft framework objects stay inside one adapter; LangGraph, Pydantic business schemas, Skill storage, and Tool execution remain unchanged.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, LangGraph, Microsoft Agent Framework `agent-framework-core==1.13.0`, `agent-framework-openai==1.12.0`, OpenAI-compatible Chat Completions, pytest

## Global Constraints

- Work in `D:\python\CommandCenter` and run Python commands through `conda run -n langgraph`.
- Follow test-driven development: add one focused failing behavior, verify RED, implement only enough for GREEN, then refactor.
- Keep `AgentSuite.match_request(user_request, tasks, skills) -> TaskMatchDecision` unchanged for callers.
- Do not modify LangGraph state, Skill schemas, ToolCatalog, ToolExecutor, database tables, API routes, or frontend code.
- The new Runtime must remain behind project-owned Python types; `agents.py`, `execution_graph.py`, and schemas must not import `agent_framework`.
- Only `list_available_skills` and `get_available_skill` are exposed to the Microsoft matching agent; both operate on the current call's in-memory `skills` tuple.
- Do not expose network, filesystem, Shell, credentials, business write Tools, or `ToolExecutor` to this agent.
- A Microsoft Runtime failure must propagate; never retry the same business judgment with Legacy Runtime.
- A valid result must pass `TaskMatchDecision` validation and reference only supplied task and Skill IDs before execution continues.
- Runtime sessions are call-scoped and must not survive across two `match_request` invocations.
- Default `COMMAND_CENTER_AGENT_RUNTIME` to `legacy`; enable Microsoft only with explicit `microsoft` configuration.
- Reuse `.env.ai`; never log or persist `AI_CONFIG_API_KEY`.
- Use `OpenAIChatCompletionClient`, not the Responses client, because the existing configuration promises an OpenAI-compatible Chat Completions endpoint.
- Bound each run to 6 model calls, 8 tool calls, and `AI_CONFIG_TIMEOUT_SECONDS` wall-clock seconds.
- Log trace metadata, counts, tool status/duration, token counts when supplied, and final Skill ID; never log full prompts, full tool results, credentials, or hidden reasoning.

## File Map

- Create `app/command_center/agent_runtime.py`: project-owned Protocol, request/result/telemetry types, limits, exceptions, and Legacy adapter.
- Create `app/command_center/microsoft_agent_runtime.py`: the only production module importing Microsoft Agent Framework; builds and runs a call-scoped agent.
- Create `app/command_center/agent_runtime_factory.py`: reads runtime selection and `.env.ai`, then constructs the selected adapter.
- Modify `app/command_center/agents.py`: inject matching Runtime, build scoped Skill tools, validate result references, and emit safe telemetry.
- Modify `app/main.py`: compose `AgentSuite` with `build_agent_runtime`.
- Modify `.env.ai.example`: document `COMMAND_CENTER_AGENT_RUNTIME`.
- Modify `requirements.txt`: pin the two Microsoft framework packages.
- Create `tests/test_agent_runtime.py`: Runtime contract and Legacy compatibility.
- Create `tests/test_agent_matching_runtime.py`: dynamic discovery inputs, scoped tools, validation, isolation, and logging.
- Create `tests/test_microsoft_agent_runtime.py`: Microsoft adapter execution, limits, session, structured output, tool events, and usage.
- Create `tests/test_agent_runtime_factory.py`: environment selection, provider mapping, default, and fail-fast behavior.

---

### Task 1: Project-owned Runtime contract and Legacy adapter

**Files:**
- Create: `app/command_center/agent_runtime.py`
- Create: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces `RuntimeCapabilities(tool_loop: bool)`.
- Produces `RuntimeLimits(max_model_calls: int = 6, max_tool_calls: int = 8, timeout_seconds: float = 60.0)`.
- Produces `RuntimeRequest[SchemaT](role, instructions, payload, output_schema, tools, session_id, limits)`.
- Produces `RuntimeUsage`, `RuntimeToolEvent`, `RuntimeTelemetry`, and `RuntimeResult[SchemaT]`.
- Produces synchronous `AgentRuntime.run_structured(request) -> RuntimeResult[SchemaT]`.
- Produces `LegacyStructuredModelRuntime(model)` with `tool_loop=False`.

- [ ] **Step 1: Write the failing Runtime contract tests**

```python
# tests/test_agent_runtime.py
from app.command_center.agent_runtime import (
    LegacyStructuredModelRuntime,
    RuntimeLimits,
    RuntimeRequest,
)
from app.command_center.schemas import TaskMatchDecision


class RecordingModel:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def generate(self, schema, system_prompt, payload):
        self.calls.append((schema, system_prompt, payload))
        return schema.model_validate(self.output)


def test_legacy_runtime_preserves_structured_model_behavior():
    output = {
        "candidate_task_ids": ["TASK-1"],
        "selected_skill_id": "00000000-0000-0000-0000-000000000001",
        "literals": {},
        "summary": "matched",
    }
    model = RecordingModel(output)
    runtime = LegacyStructuredModelRuntime(model)
    request = RuntimeRequest(
        role="task_matcher",
        instructions="match",
        payload={"skills": [{"skill_id": output["selected_skill_id"]}]},
        output_schema=TaskMatchDecision,
        session_id="session-1",
        limits=RuntimeLimits(),
    )

    result = runtime.run_structured(request)

    assert result.output.summary == "matched"
    assert runtime.capabilities.tool_loop is False
    assert result.telemetry.runtime == "legacy_structured_model"
    assert result.telemetry.model_calls == 1
    assert model.calls[0][2] == request.payload
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_runtime.py -q
```

Expected: collection fails because `app.command_center.agent_runtime` does not exist.

- [ ] **Step 3: Implement the contract and Legacy adapter**

```python
# app/command_center/agent_runtime.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Protocol, TypeVar

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
```

Implement `LegacyStructuredModelRuntime.run_structured` using `time.perf_counter()`, `uuid4()`, and exactly one call to `self._model.generate(request.output_schema, request.instructions, request.payload)`. Set `default_limits = RuntimeLimits()`. Reject non-empty `request.tools` with `RuntimeConfigurationError` so Legacy never pretends to execute tools. Set provider to `structured_model`, model to `None`, empty tool events, and unknown token counts.

```python
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
```

- [ ] **Step 4: Run the Runtime tests and existing structured-model test**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_runtime.py tests/test_structured_agents.py::test_structured_model_retries_once_after_schema_validation_failure -q
```

Expected: PASS.

- [ ] **Step 5: Commit the independent Runtime boundary**

```powershell
git add app/command_center/agent_runtime.py tests/test_agent_runtime.py
git commit -m "feat: add replaceable agent runtime contract"
```

---

### Task 2: Move only task matching onto the Runtime seam

**Files:**
- Modify: `app/command_center/agents.py`
- Create: `tests/test_agent_matching_runtime.py`
- Modify: `tests/test_structured_agents.py`

**Interfaces:**
- Consumes `AgentRuntime`, `RuntimeRequest`, and `RuntimeResult` from Task 1.
- Changes constructor to `AgentSuite(model: StructuredModel, match_runtime: AgentRuntime | None = None)`.
- Produces call-scoped `list_available_skills()` and `get_available_skill(skill_id: str)` functions only when `runtime.capabilities.tool_loop` is true.
- Produces deterministic `_validate_match_references(decision, tasks, skills)`.

- [ ] **Step 1: Write failing matching seam tests**

```python
# tests/test_agent_matching_runtime.py
from uuid import uuid4

import pytest

from app.command_center.agent_runtime import (
    RuntimeCapabilities,
    RuntimeLimits,
    RuntimeResult,
    RuntimeTelemetry,
    RuntimeUsage,
)
from app.command_center.agents import AgentSuite
from app.command_center.schemas import SkillDefinition, TaskMatchDecision
from tests.test_command_center_schemas import valid_skill_payload


class CapturingRuntime:
    capabilities = RuntimeCapabilities(tool_loop=True)
    default_limits = RuntimeLimits()

    def __init__(self, selected_skill_id):
        self.selected_skill_id = selected_skill_id
        self.requests = []

    def run_structured(self, request):
        self.requests.append(request)
        summaries = request.tools[0]()
        detail = request.tools[1](str(self.selected_skill_id))
        assert summaries[0]["skill_id"] == str(self.selected_skill_id)
        assert detail["skill_id"] == str(self.selected_skill_id)
        output = TaskMatchDecision(
            candidate_task_ids=["TASK-1"],
            selected_skill_id=self.selected_skill_id,
            literals={},
            summary="matched",
        )
        return RuntimeResult(
            output=output,
            telemetry=RuntimeTelemetry(
                trace_id="trace-1",
                session_id=request.session_id,
                runtime="fake",
                provider="fake",
                model="fake-model",
                role=request.role,
                model_calls=3,
                tool_events=(),
                usage=RuntimeUsage(),
                duration_ms=1.0,
            ),
        )


def test_tool_loop_runtime_discovers_call_scoped_skills_without_prompt_injection():
    skill = SkillDefinition.model_validate(valid_skill_payload())
    runtime = CapturingRuntime(skill.skill_id)
    agents = AgentSuite(model=object(), match_runtime=runtime)

    decision = agents.match_request(
        "处理任务",
        [{"task_id": "TASK-1", "content": {}}],
        [skill],
    )

    assert decision.selected_skill_id == skill.skill_id
    assert "skills" not in runtime.requests[0].payload
    assert [tool.__name__ for tool in runtime.requests[0].tools] == [
        "list_available_skills",
        "get_available_skill",
    ]
```

Add these concrete helpers and tests in the same file:

```python
class OutputRuntime:
    capabilities = RuntimeCapabilities(tool_loop=True)
    default_limits = RuntimeLimits()

    def __init__(self, output):
        self.output = output
        self.requests = []

    def run_structured(self, request):
        self.requests.append(request)
        return RuntimeResult(
            output=request.output_schema.model_validate(self.output),
            telemetry=RuntimeTelemetry(
                trace_id="trace-output",
                session_id=request.session_id,
                runtime="fake",
                provider="fake",
                model="fake-model",
                role=request.role,
                model_calls=1,
                tool_events=(),
                usage=RuntimeUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                duration_ms=2.0,
            ),
        )


def decision_payload(skill_id, task_id="TASK-1"):
    return {
        "candidate_task_ids": [task_id],
        "selected_skill_id": str(skill_id),
        "literals": {},
        "summary": "matched",
    }


class RecordingModel:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def generate(self, schema, system_prompt, payload):
        self.calls.append((schema, system_prompt, payload))
        return schema.model_validate(self.output)


def test_match_rejects_skill_outside_supplied_candidates():
    skill = SkillDefinition.model_validate(valid_skill_payload())
    runtime = OutputRuntime(decision_payload(uuid4()))
    agents = AgentSuite(model=object(), match_runtime=runtime)
    with pytest.raises(ValueError, match="unknown Skill"):
        agents.match_request("处理任务", [{"task_id": "TASK-1"}], [skill])


def test_get_available_skill_rejects_unknown_id():
    class ProbeRuntime(OutputRuntime):
        def run_structured(self, request):
            request.tools[1]("00000000-0000-0000-0000-000000000099")

    skill = SkillDefinition.model_validate(valid_skill_payload())
    agents = AgentSuite(object(), match_runtime=ProbeRuntime({}))
    with pytest.raises(ValueError, match="not available"):
        agents.match_request("处理任务", [{"task_id": "TASK-1"}], [skill])


def test_match_rejects_unknown_candidate_task_id():
    skill = SkillDefinition.model_validate(valid_skill_payload())
    runtime = OutputRuntime(decision_payload(skill.skill_id, "TASK-OTHER"))
    with pytest.raises(ValueError, match="unknown task"):
        AgentSuite(object(), match_runtime=runtime).match_request(
            "处理任务", [{"task_id": "TASK-1"}], [skill]
        )


def test_two_match_calls_receive_different_sessions_and_scoped_tools():
    first = SkillDefinition.model_validate(valid_skill_payload())
    second = first.model_copy(update={"skill_id": uuid4(), "name": "Second"})

    class PerCallRuntime(OutputRuntime):
        def run_structured(self, request):
            skill_id = request.tools[0]()[0]["skill_id"]
            self.output = decision_payload(skill_id)
            return super().run_structured(request)

    runtime = PerCallRuntime({})
    agents = AgentSuite(object(), match_runtime=runtime)
    agents.match_request("first", [{"task_id": "TASK-1"}], [first])
    agents.match_request("second", [{"task_id": "TASK-1"}], [second])

    assert runtime.requests[0].session_id != runtime.requests[1].session_id
    assert runtime.requests[0].tools[0]()[0]["skill_id"] == str(first.skill_id)
    assert runtime.requests[1].tools[0]()[0]["skill_id"] == str(second.skill_id)


def test_runtime_log_contains_counts_but_not_skill_payload_or_secret(caplog):
    skill = SkillDefinition.model_validate(valid_skill_payload()).model_copy(
        update={"description": "SECRET-SKILL-CONTENT"}
    )
    runtime = OutputRuntime(decision_payload(skill.skill_id))
    with caplog.at_level("INFO", logger="app.command_center.agents"):
        AgentSuite(object(), match_runtime=runtime).match_request(
            "SECRET-USER-CONTENT", [{"task_id": "TASK-1"}], [skill]
        )
    assert "trace-output" in caplog.text
    assert "SECRET-SKILL-CONTENT" not in caplog.text
    assert "SECRET-USER-CONTENT" not in caplog.text


def test_default_constructor_keeps_legacy_full_skill_payload():
    skill = SkillDefinition.model_validate(valid_skill_payload())
    model = RecordingModel(decision_payload(skill.skill_id))
    AgentSuite(model).match_request("处理任务", [{"task_id": "TASK-1"}], [skill])
    assert model.calls[0][2]["skills"][0].skill_id == skill.skill_id
```

- [ ] **Step 2: Run matching tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_matching_runtime.py -q
```

Expected: constructor rejects `match_runtime` or `match_request` still calls `self.model.generate`.

- [ ] **Step 3: Add Runtime injection without changing other roles**

Implement this constructor shape:

```python
class AgentSuite:
    def __init__(self, model: StructuredModel, match_runtime: AgentRuntime | None = None):
        self.model = model
        self.match_runtime = match_runtime or LegacyStructuredModelRuntime(model)
```

Keep every method except `match_request` byte-for-byte on `self.model.generate`.

- [ ] **Step 4: Implement scoped discovery and compact output**

Inside `match_request`, first normalize supplied values:

```python
skill_by_id = {str(skill.skill_id): skill for skill in skills}

def list_available_skills() -> list[dict[str, Any]]:
    """List compact summaries of Skills available for this request."""
    return [
        {
            "skill_id": str(skill.skill_id),
            "version": skill.version,
            "name": skill.name,
            "description": skill.description,
            "status": skill.status,
            "inputs": [item.model_dump(mode="json") for item in skill.inputs],
            "trigger_examples": skill.trigger_examples[:5],
        }
        for skill in skills
    ]

def get_available_skill(skill_id: str) -> dict[str, Any]:
    """Get one available Skill definition by exact Skill ID."""
    skill = skill_by_id.get(skill_id)
    if skill is None:
        raise ValueError("Skill is not available in this request")
    return skill.model_dump(mode="json")
```

If `tool_loop` is true, omit `skills` from `payload` and attach both functions. If false, include the existing full `skills` payload and attach no functions. Always create a fresh `session_id=str(uuid4())` and pass `self.match_runtime.default_limits`.

- [ ] **Step 5: Validate references and log safe telemetry**

After `run_structured`, validate:

```python
known_skill_ids = {skill.skill_id for skill in skills}
known_task_ids = {str(task["task_id"]) for task in tasks if task.get("task_id")}
if result.output.selected_skill_id not in known_skill_ids:
    raise ValueError("agent match references unknown Skill")
if set(result.output.candidate_task_ids) - known_task_ids:
    raise ValueError("agent match references unknown task")
```

Log one `INFO` record named `agent_runtime_completed` with only the telemetry scalar fields, `tool_events` converted to `{name,status,duration_ms}`, token counts, and `selected_skill_id`. Never include `request.payload`, tool return values, `literals`, API keys, or instructions.

- [ ] **Step 6: Run focused and execution-graph regressions**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_runtime.py tests/test_agent_matching_runtime.py tests/test_structured_agents.py tests/test_execution_graph.py tests/test_connected_mes_execution.py tests/test_v1_vertical_loop.py -q
```

Expected: PASS and existing graph tests require no graph changes.

- [ ] **Step 7: Commit the vertical seam**

```powershell
git add app/command_center/agents.py tests/test_agent_matching_runtime.py tests/test_structured_agents.py
git commit -m "feat: route task matching through agent runtime"
```

---

### Task 3: Microsoft Agent Framework adapter with bounded tool loop

**Files:**
- Create: `app/command_center/microsoft_agent_runtime.py`
- Create: `tests/test_microsoft_agent_runtime.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces `MicrosoftAgentFrameworkRuntime(agent_factory, provider, model, default_limits)` with `tool_loop=True`.
- Production `agent_factory` returns an Agent Framework `ChatAgent` configured with instructions, tools, `temperature=0`, and observation middleware.
- Consumes `RuntimeRequest` and returns only project-owned `RuntimeResult`.

- [ ] **Step 1: Pin and install the smallest compatible packages**

Add exactly:

```text
agent-framework-core==1.13.0
agent-framework-openai==1.12.0
```

Run:

```powershell
conda run -n langgraph python -m pip install -r requirements.txt
conda run -n langgraph python -m pip check
```

Expected: installation succeeds on Python 3.12 and `pip check` reports no broken requirements. `agent-framework-openai==1.12.0` declares `agent-framework-core>=1.13.0,<2` and `openai>=2.25.0,<3`; the current environment's OpenAI 2.30.0 is compatible.

- [ ] **Step 2: Write failing adapter tests around an injected fake agent**

```python
# tests/test_microsoft_agent_runtime.py
import asyncio
from types import SimpleNamespace

import pytest

from app.command_center.agent_runtime import (
    RuntimeLimitError,
    RuntimeLimits,
    RuntimeRequest,
)
from app.command_center.microsoft_agent_runtime import MicrosoftAgentFrameworkRuntime
from app.command_center.schemas import TaskMatchDecision


class FakeAgent:
    def __init__(self, output):
        self.output = output
        self.sessions = []
        self.runs = []

    def create_session(self):
        session = object()
        self.sessions.append(session)
        return session

    async def run(self, prompt, *, session, options):
        self.runs.append((prompt, session, options))
        return SimpleNamespace(
            value=TaskMatchDecision.model_validate(self.output),
            usage_details=SimpleNamespace(
                input_token_count=12,
                output_token_count=8,
                total_token_count=20,
            ),
        )


def test_microsoft_runtime_uses_fresh_session_and_pydantic_response_format():
    output = {
        "candidate_task_ids": ["TASK-1"],
        "selected_skill_id": "00000000-0000-0000-0000-000000000001",
        "literals": {},
        "summary": "matched",
    }
    fake = FakeAgent(output)
    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: fake,
        provider="openai_compatible",
        model="test-model",
    )
    request = RuntimeRequest(
        role="task_matcher",
        instructions="match",
        payload={"user_request": "处理任务", "tasks": []},
        output_schema=TaskMatchDecision,
        session_id="session-1",
        limits=RuntimeLimits(timeout_seconds=1),
    )

    result = runtime.run_structured(request)

    assert result.output.summary == "matched"
    assert fake.runs[0][1] is fake.sessions[0]
    assert fake.runs[0][2]["response_format"] is TaskMatchDecision
    assert result.telemetry.usage.total_tokens == 20
```

Add these exact helpers and behavior tests:

```python
def make_request(*, tools=(), timeout=1.0):
    return RuntimeRequest(
        role="task_matcher",
        instructions="match",
        payload={"user_request": "处理任务", "tasks": [{"task_id": "TASK-1"}]},
        output_schema=TaskMatchDecision,
        tools=tools,
        session_id="session-1",
        limits=RuntimeLimits(timeout_seconds=timeout),
    )


def output_for(skill_id):
    return {
        "candidate_task_ids": ["TASK-1"],
        "selected_skill_id": skill_id,
        "literals": {},
        "summary": "matched",
    }


def test_microsoft_runtime_instruments_list_then_detail_tool_calls():
    skill_id = "00000000-0000-0000-0000-000000000001"

    def list_available_skills():
        return [{"skill_id": skill_id}]

    def get_available_skill(requested_skill_id: str):
        assert requested_skill_id == skill_id
        return {"skill_id": skill_id, "name": "Skill"}

    class ToolCallingAgent(FakeAgent):
        def __init__(self, tools):
            super().__init__(output_for(skill_id))
            self.tools = tools

        async def run(self, prompt, *, session, options):
            summary = self.tools[0]()[0]
            detail = self.tools[1](summary["skill_id"])
            assert detail["skill_id"] == skill_id
            return await super().run(prompt, session=session, options=options)

    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: ToolCallingAgent(tools),
        provider="openai_compatible",
        model="test-model",
    )
    result = runtime.run_structured(
        make_request(tools=(list_available_skills, get_available_skill))
    )
    assert [(event.name, event.status) for event in result.telemetry.tool_events] == [
        ("list_available_skills", "succeeded"),
        ("get_available_skill", "succeeded"),
    ]


def test_microsoft_runtime_rejects_ninth_tool_call_before_handler_runs():
    handler_calls = 0

    def list_available_skills():
        nonlocal handler_calls
        handler_calls += 1
        return []

    class ExcessToolAgent(FakeAgent):
        def __init__(self, tool):
            super().__init__(output_for("00000000-0000-0000-0000-000000000001"))
            self.tool = tool

        async def run(self, prompt, *, session, options):
            for _ in range(9):
                self.tool()

    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: ExcessToolAgent(tools[0]),
        provider="openai_compatible",
        model="test-model",
    )
    with pytest.raises(RuntimeLimitError, match="tool call limit"):
        runtime.run_structured(make_request(tools=(list_available_skills,)))
    assert handler_calls == 8


def test_microsoft_runtime_rejects_seventh_model_call_before_provider_runs():
    provider_calls = 0

    class ExcessModelAgent(FakeAgent):
        def __init__(self, observer):
            super().__init__(output_for("00000000-0000-0000-0000-000000000001"))
            self.observer = observer

        async def run(self, prompt, *, session, options):
            nonlocal provider_calls

            async def call_next():
                nonlocal provider_calls
                provider_calls += 1

            for _ in range(7):
                await self.observer.chat_middleware(None, call_next)

    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: ExcessModelAgent(observer),
        provider="openai_compatible",
        model="test-model",
    )
    with pytest.raises(RuntimeLimitError, match="model call limit"):
        runtime.run_structured(make_request())
    assert provider_calls == 6


def test_microsoft_runtime_times_out_without_fallback():
    class SlowAgent(FakeAgent):
        async def run(self, prompt, *, session, options):
            await asyncio.sleep(0.05)

    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: SlowAgent(output_for(
            "00000000-0000-0000-0000-000000000001"
        )),
        provider="openai_compatible",
        model="test-model",
    )
    with pytest.raises(RuntimeLimitError, match="timed out"):
        runtime.run_structured(make_request(timeout=0.001))


def test_microsoft_runtime_validates_plain_dict_response_value():
    class DictResponseAgent(FakeAgent):
        async def run(self, prompt, *, session, options):
            return SimpleNamespace(value=self.output, usage_details=None)

    fake = DictResponseAgent(output_for("00000000-0000-0000-0000-000000000001"))
    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: fake,
        provider="openai_compatible",
        model="test-model",
    )
    result = runtime.run_structured(make_request())
    assert isinstance(result.output, TaskMatchDecision)


def test_microsoft_runtime_does_not_reuse_framework_session():
    fake = FakeAgent(output_for("00000000-0000-0000-0000-000000000001"))
    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: fake,
        provider="openai_compatible",
        model="test-model",
    )
    runtime.run_structured(make_request())
    runtime.run_structured(make_request())
    assert len(fake.sessions) == 2
    assert fake.sessions[0] is not fake.sessions[1]
```

Keep `import asyncio` in this test file for `SlowAgent`.

- [ ] **Step 3: Run adapter tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_microsoft_agent_runtime.py -q
```

Expected: collection fails because `microsoft_agent_runtime.py` is absent.

- [ ] **Step 4: Implement the synchronous adapter boundary**

`MicrosoftAgentFrameworkRuntime.run_structured` must:

```python
started = perf_counter()
trace_id = str(uuid4())
observer = _RunObserver(request.limits)
tools = tuple(observer.wrap_tool(tool) for tool in request.tools)
agent = self._agent_factory(request, tools, observer)

async def execute():
    session = agent.create_session()
    return await asyncio.wait_for(
        agent.run(
            json.dumps(_jsonable(request.payload), ensure_ascii=False),
            session=session,
            options={"response_format": request.output_schema},
        ),
        timeout=request.limits.timeout_seconds,
    )

response = asyncio.run(execute())
output = request.output_schema.model_validate(response.value)
```

The CommandCenter call path is synchronous (`def` FastAPI endpoint → synchronous LangGraph), so reject invocation from an already-running event loop with `RuntimeConfigurationError("synchronous AgentRuntime cannot run inside an active event loop")`. Do not create an unmanaged background thread as a hidden workaround.

- [ ] **Step 5: Implement model/tool limits and telemetry normalization**

Create private `_RunObserver` with:

```python
def before_model_call(self) -> None:
    if self.model_calls >= self.limits.max_model_calls:
        raise RuntimeLimitError("agent runtime exceeded model call limit")
    self.model_calls += 1

def wrap_tool(self, function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if self.tool_calls >= self.limits.max_tool_calls:
            raise RuntimeLimitError("agent runtime exceeded tool call limit")
        self.tool_calls += 1
        started = perf_counter()
        try:
            value = function(*args, **kwargs)
        except Exception:
            self.events.append(RuntimeToolEvent(function.__name__, "failed", elapsed_ms(started)))
            raise
        self.events.append(RuntimeToolEvent(function.__name__, "succeeded", elapsed_ms(started)))
        return value
    return wrapped
```

Use an Agent Framework chat middleware to call `observer.before_model_call()` immediately before `await call_next()`. Normalize `response.usage_details.input_token_count`, `output_token_count`, and `total_token_count`; leave each value `None` when the provider omits it. Convert `asyncio.TimeoutError` to `RuntimeLimitError("agent runtime timed out")` while preserving other framework/tool exceptions.

- [ ] **Step 6: Add a framework integration test through a mocked Chat Completions transport**

Add this network-free contract test. It exercises the real `OpenAIChatCompletionClient` and Agent Framework function loop; the fake transport returns two tool calls followed by the structured result:

```python
import json

import httpx
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI


def completion(message, finish_reason, response_id):
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def test_real_framework_owns_list_detail_final_tool_loop():
    skill_id = "00000000-0000-0000-0000-000000000001"
    requests = []
    responses = iter([
        completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-list",
                    "type": "function",
                    "function": {"name": "list_available_skills", "arguments": "{}"},
                }],
            },
            "tool_calls",
            "response-1",
        ),
        completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-detail",
                    "type": "function",
                    "function": {
                        "name": "get_available_skill",
                        "arguments": json.dumps({"skill_id": skill_id}),
                    },
                }],
            },
            "tool_calls",
            "response-2",
        ),
        completion(
            {
                "role": "assistant",
                "content": json.dumps(output_for(skill_id)),
            },
            "stop",
            "response-3",
        ),
    ])

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))

    async_client = AsyncOpenAI(
        api_key="test-key",
        base_url="http://test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = OpenAIChatCompletionClient(async_client=async_client, model="test-model")

    def list_available_skills():
        return [{"skill_id": skill_id, "name": "Skill"}]

    def get_available_skill(skill_id: str):
        return {"skill_id": skill_id, "name": "Skill", "inputs": []}

    def agent_factory(request, tools, observer):
        return client.as_agent(
            name=request.role,
            instructions=request.instructions,
            tools=list(tools),
            temperature=0,
            middleware=[observer.chat_middleware],
        )

    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=agent_factory,
        provider="openai_compatible",
        model="test-model",
    )
    result = runtime.run_structured(
        make_request(tools=(list_available_skills, get_available_skill))
    )

    assert isinstance(result.output, TaskMatchDecision)
    assert [event.name for event in result.telemetry.tool_events] == [
        "list_available_skills",
        "get_available_skill",
    ]
    assert any(message["role"] == "tool" for message in requests[1]["messages"])
    assert sum(message["role"] == "tool" for message in requests[2]["messages"]) == 2
```

Do not bypass the Agent Framework loop by manually invoking the two functions in this integration test.

- [ ] **Step 7: Run focused tests and package validation**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_microsoft_agent_runtime.py tests/test_agent_runtime.py -q
conda run -n langgraph python -m pip check
```

Expected: PASS.

- [ ] **Step 8: Commit the Microsoft adapter**

```powershell
git add requirements.txt app/command_center/microsoft_agent_runtime.py tests/test_microsoft_agent_runtime.py
git commit -m "feat: add Microsoft agent framework runtime"
```

---

### Task 4: Environment factory and application composition

**Files:**
- Create: `app/command_center/agent_runtime_factory.py`
- Create: `tests/test_agent_runtime_factory.py`
- Modify: `app/main.py`
- Modify: `.env.ai.example`

**Interfaces:**
- Produces `build_agent_runtime(model, config_path=None) -> AgentRuntime`.
- `legacy` returns `LegacyStructuredModelRuntime(model)` without importing the Microsoft adapter.
- `microsoft` calls `MicrosoftAgentFrameworkRuntime.from_openai_compatible(...)`; all Microsoft imports stay inside the adapter module.
- `build_command_center_components` constructs one `StructuredModel`, then injects the selected matching Runtime into `AgentSuite`.

- [ ] **Step 1: Write failing factory tests**

```python
# tests/test_agent_runtime_factory.py
import pytest

from app.command_center.agent_runtime import (
    LegacyStructuredModelRuntime,
    RuntimeConfigurationError,
)
from app.command_center.agent_runtime_factory import build_agent_runtime


def test_runtime_factory_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("COMMAND_CENTER_AGENT_RUNTIME", raising=False)
    runtime = build_agent_runtime(model=object())
    assert isinstance(runtime, LegacyStructuredModelRuntime)


def test_runtime_factory_rejects_unknown_name(monkeypatch):
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "other")
    with pytest.raises(RuntimeConfigurationError, match="legacy or microsoft"):
        build_agent_runtime(model=object())
```

Add Microsoft selection and fail-fast tests:

```python
def test_microsoft_runtime_maps_existing_ai_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=http://provider/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=SECRET-KEY\n"
        "AI_CONFIG_TIMEOUT_SECONDS=12.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "microsoft")
    captured = {}

    class FakeMicrosoftRuntime:
        @classmethod
        def from_openai_compatible(cls, **kwargs):
            captured.update(kwargs)
            return cls()

    monkeypatch.setattr(
        "app.command_center.agent_runtime_factory._load_microsoft_runtime_class",
        lambda: FakeMicrosoftRuntime,
    )
    runtime = build_agent_runtime(model=object(), config_path=env_file)
    assert isinstance(runtime, FakeMicrosoftRuntime)
    assert captured == {
        "base_url": "http://provider/v1",
        "model": "test-model",
        "api_key": "SECRET-KEY",
        "timeout_seconds": 12.5,
    }
    assert "SECRET-KEY" not in repr(runtime)


def test_microsoft_runtime_requires_provider_values(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.ai"
    env_file.write_text("AI_CONFIG_MODEL_NAME=test-model\n", encoding="utf-8")
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "microsoft")
    with pytest.raises(RuntimeConfigurationError, match="AI_CONFIG_MODEL_BASE_URL"):
        build_agent_runtime(model=object(), config_path=env_file)


def test_legacy_does_not_require_provider_values(monkeypatch, tmp_path):
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "legacy")
    missing = tmp_path / "missing.env.ai"
    assert isinstance(
        build_agent_runtime(model=object(), config_path=missing),
        LegacyStructuredModelRuntime,
    )
```

- [ ] **Step 2: Run factory tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_runtime_factory.py -q
```

Expected: collection fails because the factory module does not exist.

- [ ] **Step 3: Implement explicit selection and provider construction**

Use this selection shape:

```python
def _load_microsoft_runtime_class():
    from app.command_center.microsoft_agent_runtime import MicrosoftAgentFrameworkRuntime

    return MicrosoftAgentFrameworkRuntime


runtime_name = os.getenv("COMMAND_CENTER_AGENT_RUNTIME", "legacy").strip().lower()
if runtime_name == "legacy":
    return LegacyStructuredModelRuntime(model)
if runtime_name != "microsoft":
    raise RuntimeConfigurationError(
        "COMMAND_CENTER_AGENT_RUNTIME must be legacy or microsoft"
    )
```

After validating Microsoft configuration, call `_load_microsoft_runtime_class()` inside `try/except ImportError` and translate the import failure into `RuntimeConfigurationError("microsoft runtime requires agent-framework-core==1.13.0 and agent-framework-openai==1.12.0")`.

For `microsoft`, load the same `COMMAND_CENTER_AI_ENV_FILE` path as `StructuredModel.from_environment`, require the four existing AI settings, and call:

```python
return MicrosoftAgentFrameworkRuntime.from_openai_compatible(
    base_url=base_url,
    api_key=api_key,
    model=model_name,
    timeout_seconds=timeout_seconds,
)
```

Implement `from_openai_compatible` in `microsoft_agent_runtime.py`. It creates `AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_seconds)`, passes it to `OpenAIChatCompletionClient(async_client=async_client, model=model)`, and builds an `agent_factory` that calls `client.as_agent(name=request.role, instructions=request.instructions, tools=list(tools), temperature=0, middleware=[observer.chat_middleware])`. Keep the adapter import inside the factory's Microsoft branch so Legacy startup does not import optional framework packages. Convert `ImportError` to a clear `RuntimeConfigurationError` naming both pinned packages.

- [ ] **Step 4: Wire application composition once**

Replace:

```python
agents = agents or AgentSuite(StructuredModel.from_environment())
```

with:

```python
if agents is None:
    structured_model = StructuredModel.from_environment()
    agents = AgentSuite(
        structured_model,
        match_runtime=build_agent_runtime(structured_model),
    )
```

Do not alter injected `agents` behavior in tests. Add `COMMAND_CENTER_AGENT_RUNTIME=legacy` to `.env.ai.example` with a comment that `microsoft` enables only request matching.

- [ ] **Step 5: Run factory, composition, and API regressions**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_runtime_factory.py tests/test_real_mes_readonly_loop.py tests/test_command_center_api.py tests/test_api.py -q
```

Expected: PASS; tests injecting their own agents do not require AI environment settings.

- [ ] **Step 6: Commit configuration and composition**

```powershell
git add app/command_center/agent_runtime_factory.py tests/test_agent_runtime_factory.py app/main.py .env.ai.example
git commit -m "feat: configure task matching runtime"
```

---

### Task 5: Full regression and local Microsoft smoke verification

**Files:**
- Modify implementation or tests only if a failing verification proves a defect.
- Modify: `README.md` only to document the new runtime switch and scope.

**Interfaces:**
- Confirms Legacy remains the default operational path.
- Confirms Microsoft mode reaches the configured OpenAI-compatible provider and exposes only the two read-only Skill functions.

- [ ] **Step 1: Document operation and rollback**

Add a concise README section containing:

```text
COMMAND_CENTER_AGENT_RUNTIME=legacy      # default and rollback
COMMAND_CENTER_AGENT_RUNTIME=microsoft   # only AgentSuite.match_request

Microsoft mode uses the existing .env.ai provider values. It keeps session
history only inside one match_request call and exposes no business execution
Tools. Restart the backend after changing the value.
```

- [ ] **Step 2: Run all backend tests**

Run:

```powershell
conda run -n langgraph python -m pytest -q
```

Expected: all tests PASS with `COMMAND_CENTER_AGENT_RUNTIME` unset or `legacy`.

- [ ] **Step 3: Run static repository and dependency checks**

Run:

```powershell
conda run -n langgraph python -m pip check
rg -n "agent_framework" app tests
rg -n "AI_CONFIG_API_KEY|api_key" app/command_center/agent_runtime.py app/command_center/microsoft_agent_runtime.py app/command_center/agents.py
git diff --check
```

Expected:

- production `agent_framework` imports occur only in `microsoft_agent_runtime.py` or the Microsoft-only factory branch;
- no API key appears in Runtime telemetry/log construction;
- `pip check` and `git diff --check` succeed.

- [ ] **Step 4: Run one opt-in provider smoke test without business side effects**

Set `COMMAND_CENTER_AGENT_RUNTIME=microsoft`, use the existing `.env.ai`, and invoke only a `match_request` fixture containing one synthetic task and one in-memory published Skill. Verify logs show:

```text
runtime=microsoft_agent_framework
tool names are a subset of {list_available_skills, get_available_skill}
selected_skill_id equals the supplied Skill
no ToolExecutor or external business API call occurred
```

If the configured provider lacks tool calling or Pydantic structured output, record the provider capability failure and leave `legacy` as the active configuration; do not add provider-specific business heuristics or silent fallback.

- [ ] **Step 5: Restore the safe default and rerun the matching regression**

Run:

```powershell
$env:COMMAND_CENTER_AGENT_RUNTIME='legacy'
conda run -n langgraph python -m pytest tests/test_agent_matching_runtime.py tests/test_execution_graph.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit documentation and any evidence-driven corrections**

```powershell
git add README.md
git commit -m "docs: explain agent runtime selection"
```

Do not push or create a pull request unless the user requests it.
