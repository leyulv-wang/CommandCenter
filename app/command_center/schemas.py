from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class UIEvent(BaseModel):
    event_id: UUID
    sequence: int
    timestamp: datetime
    page_url: str
    action_type: Literal["click", "input", "select", "submit", "navigation"]
    target: dict[str, Any] = Field(default_factory=dict)
    value_ref: str | None = None
    screenshot_ref: str | None = None


class APIExchange(BaseModel):
    exchange_id: UUID
    sequence: int
    started_at: datetime
    completed_at: datetime
    system_code: str
    method: str
    path: str
    request_body: dict[str, Any] = Field(default_factory=dict)
    response_status: int
    response_body: dict[str, Any] = Field(default_factory=dict)
    matched_tool_id: str | None = None
    match_status: Literal["matched", "not_allowed", "unknown"]


class OperationTrace(BaseModel):
    trace_id: UUID
    recording_id: UUID
    objective: str
    source_task: dict[str, Any]
    started_at: datetime
    ended_at: datetime
    ui_events: list[UIEvent] = Field(default_factory=list)
    api_exchanges: list[APIExchange] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class InputBinding(BaseModel):
    tool_field: str
    expression: str

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, value: str) -> str:
        allowed = ("task.", "steps.", "literal.")
        if not value.startswith(allowed):
            raise ValueError("binding must reference task, steps, or literal")
        return value


class BusinessAction(BaseModel):
    action_id: str
    sequence: int
    intent: str
    source_ui_event_ids: list[UUID] = Field(default_factory=list)
    source_exchange_ids: list[UUID] = Field(default_factory=list)
    tool_id: str
    input_bindings: list[InputBinding] = Field(default_factory=list)
    output_observations: list[dict[str, Any]] = Field(default_factory=list)


class DemonstrationAnalysis(BaseModel):
    summary: str
    business_actions: list[BusinessAction]
    ignored_ui_event_ids: list[UUID] = Field(default_factory=list)
    uncertainties: list[dict[str, Any]] = Field(default_factory=list)
    compilable: bool


class SkillInput(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean"]
    description: str
    required: bool = True
    source_hint: str | None = None


class SkillOutput(BaseModel):
    name: str
    type: str
    description: str


class SkillStep(BaseModel):
    step_id: str
    name: str
    tool_id: str
    input_bindings: dict[str, str]
    output_bindings: dict[str, str] = Field(default_factory=dict)
    side_effect: Literal["read", "write"]
    idempotency_key_template: str | None = None

    @field_validator("input_bindings")
    @classmethod
    def validate_bindings(cls, value: dict[str, str]) -> dict[str, str]:
        for target, expression in value.items():
            if not target.startswith(("body.", "path.")):
                raise ValueError("tool binding target must start with body. or path.")
            if not expression.startswith(("task.", "steps.", "literal.")):
                raise ValueError("binding must reference task, steps, or literal")
        return value

    @model_validator(mode="after")
    def require_write_idempotency(self) -> SkillStep:
        if self.side_effect == "write" and not self.idempotency_key_template:
            raise ValueError("write steps require an idempotency key template")
        return self


class SuccessCondition(BaseModel):
    condition_id: str
    description: str
    verification_tool_id: str
    assertion: dict[str, Any]


class SkillDefinition(BaseModel):
    skill_id: UUID
    version: int = Field(ge=1)
    name: str
    description: str
    status: Literal["candidate", "testing", "published", "rejected", "runtime_failed"]
    trigger_examples: list[str]
    source_recording_id: UUID
    inputs: list[SkillInput]
    outputs: list[SkillOutput]
    steps: list[SkillStep]
    success_conditions: list[SuccessCondition]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    published_at: datetime | None = None


class TestCase(BaseModel):
    case_id: str
    category: Literal["normal", "parameter_variation", "idempotency"]
    description: str
    fixture: dict[str, Any]
    invocation: dict[str, Any]
    expected: dict[str, Any]


class TestPlan(BaseModel):
    skill_id: UUID
    skill_version: int
    cases: list[TestCase]


class ExecutionCommand(BaseModel):
    run_id: UUID
    skill_id: UUID
    skill_version: int
    step_id: str
    tool_id: str
    arguments: dict[str, Any]
    idempotency_key: str | None = None
    reason: str


class StepResult(BaseModel):
    run_id: UUID
    step_id: str
    tool_id: str
    status: Literal["succeeded", "failed", "skipped"]
    started_at: datetime
    ended_at: datetime
    request_summary: dict[str, Any] = Field(default_factory=dict)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    normalized_output: dict[str, Any] = Field(default_factory=dict)
    side_effect: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)
    retry_safe: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    status: Literal["passed", "failed", "inconclusive"]
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    side_effects: dict[str, Any] = Field(default_factory=dict)
    duplicate_detected: bool = False
    summary: str


class TaskMatchDecision(BaseModel):
    candidate_task_ids: list[str]
    selected_skill_id: UUID
    literals: dict[str, Any] = Field(default_factory=dict)
    summary: str
