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
