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
