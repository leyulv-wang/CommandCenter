import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

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

    asyncio.run(async_client.close())
