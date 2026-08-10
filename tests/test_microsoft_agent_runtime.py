import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

import app.command_center.microsoft_agent_runtime as microsoft_agent_runtime
from app.command_center.agent_runtime import (
    RuntimeConfigurationError,
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

    async def run(self, prompt, *, session, options, middleware=()):
        self.runs.append((prompt, session, options))
        return SimpleNamespace(
            value=TaskMatchDecision.model_validate(self.output),
            usage_details=SimpleNamespace(
                input_token_count=12,
                output_token_count=8,
                total_token_count=20,
            ),
        )


def make_request(*, tools=(), timeout=1.0, limits=None):
    return RuntimeRequest(
        role="task_matcher",
        instructions="match",
        payload={"user_request": "处理任务", "tasks": [{"task_id": "TASK-1"}]},
        output_schema=TaskMatchDecision,
        tools=tools,
        session_id="session-1",
        limits=limits or RuntimeLimits(timeout_seconds=timeout),
    )


def output_for(skill_id):
    return {
        "candidate_task_ids": ["TASK-1"],
        "selected_skill_id": skill_id,
        "literals": {},
        "summary": "matched",
    }


def test_from_openai_compatible_builds_fixed_version_agent_factory(monkeypatch):
    calls = {}
    output = output_for("00000000-0000-0000-0000-000000000001")

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            calls["async_client_instance"] = self
            calls["async_client"] = kwargs

    class FakeOpenAIChatCompletionClient:
        def __init__(self, **kwargs):
            calls["chat_client"] = kwargs

        def as_agent(self, **kwargs):
            calls["agent_factory"] = kwargs
            return FakeAgent(output)

    monkeypatch.setattr(microsoft_agent_runtime, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(
        microsoft_agent_runtime,
        "OpenAIChatCompletionClient",
        FakeOpenAIChatCompletionClient,
    )

    runtime = MicrosoftAgentFrameworkRuntime.from_openai_compatible(
        base_url="https://provider.example/v1",
        api_key="test-secret-key",
        model="provider-model",
        timeout_seconds=12.5,
    )
    real_agent_factory = runtime._agent_factory

    def capture_agent_factory(request, tools, observer):
        calls["observer"] = observer
        return real_agent_factory(request, tools, observer)

    runtime._agent_factory = capture_agent_factory
    result = runtime.run_structured(make_request())

    assert calls["async_client"] == {
        "base_url": "https://provider.example/v1",
        "api_key": "test-secret-key",
        "timeout": 12.5,
    }
    assert calls["chat_client"] == {
        "async_client": calls["async_client_instance"],
        "model": "provider-model",
    }
    agent_factory_args = calls["agent_factory"]
    assert agent_factory_args == {
        "name": "task_matcher",
        "instructions": "match",
        "tools": [],
        "default_options": {"temperature": 0},
        "middleware": [calls["observer"].chat_middleware],
    }
    assert runtime.default_limits == RuntimeLimits(timeout_seconds=12.5)
    assert result.telemetry.provider == "openai_compatible"
    assert result.telemetry.model == "provider-model"
    assert "test-secret-key" not in repr(runtime)


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

        async def run(self, prompt, *, session, options, middleware=()):
            summary = self.tools[0]()[0]
            detail = self.tools[1](summary["skill_id"])
            assert detail["skill_id"] == skill_id
            return await super().run(
                prompt, session=session, options=options, middleware=middleware
            )

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

        async def run(self, prompt, *, session, options, middleware=()):
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

        async def run(self, prompt, *, session, options, middleware=()):
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
        async def run(self, prompt, *, session, options, middleware=()):
            await asyncio.sleep(0.05)

    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: SlowAgent(
            output_for("00000000-0000-0000-0000-000000000001")
        ),
        provider="openai_compatible",
        model="test-model",
    )
    with pytest.raises(RuntimeLimitError, match="timed out"):
        runtime.run_structured(make_request(timeout=0.001))


def test_microsoft_runtime_validates_plain_dict_response_value():
    class DictResponseAgent(FakeAgent):
        async def run(self, prompt, *, session, options, middleware=()):
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


def test_microsoft_runtime_rejects_active_event_loop():
    runtime = MicrosoftAgentFrameworkRuntime(
        agent_factory=lambda request, tools, observer: FakeAgent(
            output_for("00000000-0000-0000-0000-000000000001")
        ),
        provider="openai_compatible",
        model="test-model",
    )

    async def invoke():
        with pytest.raises(RuntimeConfigurationError, match="active event loop"):
            runtime.run_structured(make_request())

    asyncio.run(invoke())


def completion(message, finish_reason, response_id):
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def test_real_framework_owns_list_detail_final_tool_loop():
    skill_id = "00000000-0000-0000-0000-000000000001"
    requests = []
    responses = iter(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-list",
                            "type": "function",
                            "function": {
                                "name": "list_available_skills",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                "tool_calls",
                "response-1",
            ),
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-detail",
                            "type": "function",
                            "function": {
                                "name": "get_available_skill",
                                "arguments": json.dumps({"skill_id": skill_id}),
                            },
                        }
                    ],
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
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))

    async_client = AsyncOpenAI(
        api_key="test-key",
        base_url="http://test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = OpenAIChatCompletionClient(
        async_client=async_client, model="test-model"
    )

    def list_available_skills():
        return [{"skill_id": skill_id, "name": "Skill"}]

    def get_available_skill(skill_id: str):
        return {"skill_id": skill_id, "name": "Skill", "inputs": []}

    def agent_factory(request, tools, observer):
        return client.as_agent(
            name=request.role,
            instructions=request.instructions,
            tools=list(tools),
            default_options={"temperature": 0},
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
    assert result.telemetry.usage.input_tokens == 30
    assert result.telemetry.usage.output_tokens == 15
    assert result.telemetry.usage.total_tokens == 45

    asyncio.run(async_client.close())


def make_real_runtime(response_payloads, requests, observers=None):
    responses = iter(response_payloads)

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))

    async_client = AsyncOpenAI(
        api_key="test-key",
        base_url="http://test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = OpenAIChatCompletionClient(
        async_client=async_client, model="test-model"
    )

    def agent_factory(request, tools, observer):
        if observers is not None:
            observers.append(observer)
        return client.as_agent(
            name=request.role,
            instructions=request.instructions,
            tools=list(tools),
            default_options={"temperature": 0},
            middleware=[observer.chat_middleware],
        )

    return (
        MicrosoftAgentFrameworkRuntime(
            agent_factory=agent_factory,
            provider="openai_compatible",
            model="test-model",
        ),
        async_client,
    )


def tool_call_message(name, arguments, call_id):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
    }


def test_real_framework_tool_exception_fails_runtime_without_another_provider_call():
    skill_id = "00000000-0000-0000-0000-000000000001"
    requests = []
    observers = []
    runtime, async_client = make_real_runtime(
        [
            completion(
                tool_call_message("failing_tool", {}, "call-fail"),
                "tool_calls",
                "response-fail",
            ),
            completion(
                {
                    "role": "assistant",
                    "content": json.dumps(output_for(skill_id)),
                },
                "stop",
                "response-should-not-run",
            ),
        ],
        requests,
        observers,
    )

    def failing_tool():
        raise ValueError("tool exploded")

    try:
        with pytest.raises(ValueError, match="tool exploded"):
            runtime.run_structured(make_request(tools=(failing_tool,)))
        assert len(requests) == 1
        assert [(event.name, event.status) for event in observers[0].events] == [
            ("failing_tool", "failed")
        ]
    finally:
        asyncio.run(async_client.close())


@pytest.mark.parametrize(
    ("requested_limit", "expected_provider_calls"),
    [(100, 6), (2, 2)],
)
def test_real_framework_enforces_hard_and_lower_model_call_limits(
    requested_limit, expected_provider_calls
):
    requests = []
    response_payloads = [
        completion(
            tool_call_message("loop_tool", {}, f"call-{index}"),
            "tool_calls",
            f"response-{index}",
        )
        for index in range(expected_provider_calls + 1)
    ]
    response_payloads.append(
        completion(
            {
                "role": "assistant",
                "content": json.dumps(
                    output_for("00000000-0000-0000-0000-000000000001")
                ),
            },
            "stop",
            "response-final",
        )
    )
    runtime, async_client = make_real_runtime(response_payloads, requests)

    def loop_tool():
        return "continue"

    try:
        with pytest.raises(RuntimeLimitError, match="model call limit"):
            runtime.run_structured(
                make_request(
                    tools=(loop_tool,),
                    limits=RuntimeLimits(
                        max_model_calls=requested_limit,
                        max_tool_calls=100,
                        timeout_seconds=1,
                    ),
                )
            )
        assert len(requests) == expected_provider_calls
    finally:
        asyncio.run(async_client.close())


@pytest.mark.parametrize(
    ("requested_limit", "batch_size", "expected_handler_calls"),
    [(100, 9, 8), (2, 3, 2)],
)
def test_real_framework_tool_limit_fails_without_another_provider_call(
    requested_limit, batch_size, expected_handler_calls
):
    skill_id = "00000000-0000-0000-0000-000000000001"
    requests = []
    tool_calls = [
        {
            "id": f"call-{index}",
            "type": "function",
            "function": {
                "name": "bounded_tool",
                "arguments": json.dumps({"value": index}),
            },
        }
        for index in range(batch_size)
    ]
    runtime, async_client = make_real_runtime(
        [
            completion(
                {"role": "assistant", "content": None, "tool_calls": tool_calls},
                "tool_calls",
                "response-tools",
            ),
            completion(
                {
                    "role": "assistant",
                    "content": json.dumps(output_for(skill_id)),
                },
                "stop",
                "response-should-not-run",
            ),
        ],
        requests,
    )
    handler_calls = 0
    counter_lock = threading.Lock()

    def bounded_tool(value: int):
        nonlocal handler_calls
        with counter_lock:
            handler_calls += 1
        return value

    try:
        with pytest.raises(RuntimeLimitError, match="tool call limit"):
            runtime.run_structured(
                make_request(
                    tools=(bounded_tool,),
                    limits=RuntimeLimits(
                        max_model_calls=100,
                        max_tool_calls=requested_limit,
                        timeout_seconds=1,
                    ),
                )
            )
        assert handler_calls == expected_handler_calls
        assert len(requests) == 1
    finally:
        asyncio.run(async_client.close())


def test_real_framework_async_tool_records_true_duration_and_success():
    skill_id = "00000000-0000-0000-0000-000000000001"
    requests = []
    observers = []
    runtime, async_client = make_real_runtime(
        [
            completion(
                tool_call_message("slow_async_tool", {}, "call-slow"),
                "tool_calls",
                "response-tool",
            ),
            completion(
                {
                    "role": "assistant",
                    "content": json.dumps(output_for(skill_id)),
                },
                "stop",
                "response-final",
            ),
        ],
        requests,
        observers,
    )

    async def slow_async_tool():
        await asyncio.sleep(0.02)
        return "done"

    try:
        result = runtime.run_structured(make_request(tools=(slow_async_tool,)))
        assert result.output.summary == "matched"
        event = observers[0].events[0]
        assert event.status == "succeeded"
        assert event.duration_ms >= 15
    finally:
        asyncio.run(async_client.close())


def test_real_framework_async_tool_exception_records_failure_and_stops():
    skill_id = "00000000-0000-0000-0000-000000000001"
    requests = []
    observers = []
    runtime, async_client = make_real_runtime(
        [
            completion(
                tool_call_message("failing_async_tool", {}, "call-async-fail"),
                "tool_calls",
                "response-tool",
            ),
            completion(
                {
                    "role": "assistant",
                    "content": json.dumps(output_for(skill_id)),
                },
                "stop",
                "response-should-not-run",
            ),
        ],
        requests,
        observers,
    )

    async def failing_async_tool():
        await asyncio.sleep(0.02)
        raise ValueError("async tool exploded")

    try:
        with pytest.raises(ValueError, match="async tool exploded"):
            runtime.run_structured(make_request(tools=(failing_async_tool,)))
        assert len(requests) == 1
        event = observers[0].events[0]
        assert event.status == "failed"
        assert event.duration_ms >= 15
    finally:
        asyncio.run(async_client.close())


def make_dynamic_callable_runtime(requests, observers, final_output):
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            advertised_name = body["tools"][0]["function"]["name"]
            return httpx.Response(
                200,
                json=completion(
                    tool_call_message(advertised_name, {}, "call-object"),
                    "tool_calls",
                    "response-tool",
                ),
            )
        return httpx.Response(
            200,
            json=completion(
                {"role": "assistant", "content": json.dumps(final_output)},
                "stop",
                "response-final",
            ),
        )

    async_client = AsyncOpenAI(
        api_key="test-key",
        base_url="http://test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = OpenAIChatCompletionClient(
        async_client=async_client, model="test-model"
    )

    def agent_factory(request, tools, observer):
        observers.append(observer)
        return client.as_agent(
            name=request.role,
            instructions=request.instructions,
            tools=list(tools),
            default_options={"temperature": 0},
            middleware=[observer.chat_middleware],
        )

    return (
        MicrosoftAgentFrameworkRuntime(
            agent_factory=agent_factory,
            provider="openai_compatible",
            model="test-model",
        ),
        async_client,
    )


def test_real_framework_async_callable_object_uses_stable_name_and_true_duration():
    class SuccessfulAsyncCallable:
        async def __call__(self):
            await asyncio.sleep(0.02)
            return "done"

    requests = []
    observers = []
    runtime, async_client = make_dynamic_callable_runtime(
        requests,
        observers,
        output_for("00000000-0000-0000-0000-000000000001"),
    )

    try:
        result = runtime.run_structured(
            make_request(tools=(SuccessfulAsyncCallable(),))
        )
        assert result.output.summary == "matched"
        assert requests[0]["tools"][0]["function"]["name"] == (
            "SuccessfulAsyncCallable"
        )
        assert len(requests) == 2
        event = observers[0].events[0]
        assert event.name == "SuccessfulAsyncCallable"
        assert event.status == "succeeded"
        assert event.duration_ms >= 15
    finally:
        asyncio.run(async_client.close())


def test_real_framework_async_callable_object_failure_stops_provider_and_is_timed():
    class FailingAsyncCallable:
        async def __call__(self):
            await asyncio.sleep(0.02)
            raise ValueError("callable object exploded")

    requests = []
    observers = []
    runtime, async_client = make_dynamic_callable_runtime(
        requests,
        observers,
        output_for("00000000-0000-0000-0000-000000000001"),
    )

    try:
        with pytest.raises(ValueError, match="callable object exploded"):
            runtime.run_structured(make_request(tools=(FailingAsyncCallable(),)))
        assert requests[0]["tools"][0]["function"]["name"] == (
            "FailingAsyncCallable"
        )
        assert len(requests) == 1
        event = observers[0].events[0]
        assert event.name == "FailingAsyncCallable"
        assert event.status == "failed"
        assert event.duration_ms >= 15
    finally:
        asyncio.run(async_client.close())
