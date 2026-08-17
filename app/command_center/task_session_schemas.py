from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.command_center.schemas import StepResult, VerificationResult


TaskSessionState = Literal[
    "understanding",
    "resolving_context",
    "collecting_input",
    "awaiting_confirmation",
    "executing",
    "verifying",
    "succeeded",
    "failed",
]
InteractionType = Literal[
    "message", "question", "selection", "form", "confirmation", "result"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParameterSource(StrictModel):
    kind: Literal["user_input", "trusted_context", "step_output"]
    reference: str = Field(min_length=1, max_length=512)


class ContextEvidence(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    tool_id: str = Field(min_length=1, max_length=256)
    object_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class PrincipalContext(StrictModel):
    subject_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    permissions: frozenset[str] = Field(default_factory=frozenset)


class PlannedStep(StrictModel):
    step_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    tool_id: str = Field(min_length=1, max_length=256)
    side_effect: Literal["read", "write"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_sources: dict[str, ParameterSource] = Field(default_factory=dict)
    idempotency_key: str | None = None
    idempotency_guarantee: Literal["none", "header", "intrinsic"] = "none"


class ExecutionPlan(StrictModel):
    skill_id: UUID
    skill_version: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=2_000)
    target_objects: list[str] = Field(default_factory=list)
    selected_object: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[PlannedStep] = Field(min_length=1)
    verification_condition_ids: list[str] = Field(default_factory=list)
    compensation_step_ids: list[str] = Field(default_factory=list)


class MessageInteraction(StrictModel):
    type: Literal["message"] = "message"
    message: str


class QuestionInteraction(StrictModel):
    type: Literal["question"] = "question"
    prompt: str
    field_names: list[str] = Field(min_length=1)


class SelectionOption(StrictModel):
    value: str
    label: str
    description: str | None = None


class SelectionInteraction(StrictModel):
    type: Literal["selection"] = "selection"
    prompt: str
    field_name: str
    options: list[SelectionOption] = Field(min_length=1)


class FormInteraction(StrictModel):
    type: Literal["form"] = "form"
    title: str
    schema_: dict[str, Any] = Field(alias="schema")
    values: dict[str, Any] = Field(default_factory=dict)


class PlannedStepView(StrictModel):
    step_id: str
    name: str
    system: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ConfirmationInteraction(StrictModel):
    type: Literal["confirmation"] = "confirmation"
    title: str
    summary: str
    plan_revision: int = Field(ge=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_token: str = Field(min_length=32, max_length=256)
    systems: list[str] = Field(default_factory=list)
    target_objects: list[str] = Field(default_factory=list)
    write_steps: list[PlannedStepView] = Field(min_length=1)


class StepResultView(StrictModel):
    step_id: str
    name: str | None = None
    status: str
    summary: str | None = None


class ResultInteraction(StrictModel):
    type: Literal["result"] = "result"
    status: Literal[
        "succeeded",
        "failed",
        "partial_failure",
        "verification_incomplete",
        "unknown",
    ]
    code: str | None = None
    summary: str
    steps: list[StepResultView] = Field(default_factory=list)


NextInteraction = Annotated[
    MessageInteraction
    | QuestionInteraction
    | SelectionInteraction
    | FormInteraction
    | ConfirmationInteraction
    | ResultInteraction,
    Field(discriminator="type"),
]


class TaskSessionSnapshot(StrictModel):
    session_id: UUID
    state: TaskSessionState
    version: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=2_000)
    principal: PrincipalContext
    messages: list[dict[str, Any]] = Field(default_factory=list)
    skill_candidates: list[dict[str, Any]] = Field(default_factory=list)
    object_candidates: list[dict[str, Any]] = Field(default_factory=list)
    selected_skill_id: UUID | None = None
    selected_skill_version: int | None = None
    selected_object: dict[str, Any] | None = None
    context_evidence: list[ContextEvidence] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    input_sources: dict[str, ParameterSource] = Field(default_factory=dict)
    plan_revision: int = Field(default=0, ge=0)
    plan: ExecutionPlan | None = None
    plan_hash: str | None = None
    confirmation_token_hash: str | None = None
    confirmation_consumed: bool = False
    step_results: list[StepResult] = Field(default_factory=list)
    verification: VerificationResult | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    next_interaction: NextInteraction

    @model_validator(mode="after")
    def require_interaction_for_state(self) -> TaskSessionSnapshot:
        allowed: dict[str, set[str]] = {
            "understanding": {"message", "selection"},
            "resolving_context": {"message", "selection"},
            "collecting_input": {"question", "selection", "form"},
            "awaiting_confirmation": {"confirmation"},
            "executing": {"message"},
            "verifying": {"message"},
            "succeeded": {"result"},
            "failed": {"result"},
        }
        if self.next_interaction.type not in allowed[self.state]:
            raise ValueError("next interaction does not match task session state")
        return self


class TaskSessionHint(StrictModel):
    action_id: str | None = None
    skill_id: UUID | None = None
    skill_version: int | None = None
    parent_run_id: UUID | None = None
    selected_record_id: str | None = None
    selected_object: dict[str, Any] | None = None


class CreateTaskSessionRequest(StrictModel):
    goal: str = Field(min_length=1, max_length=2_000)
    hint: TaskSessionHint | None = None


class TaskSessionMessageRequest(StrictModel):
    version: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=2_000)


class TaskSessionInputRequest(StrictModel):
    version: int = Field(ge=1)
    values: dict[str, Any]


class TaskSessionConfirmationRequest(StrictModel):
    version: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_token: str = Field(min_length=32, max_length=256)
    approved: bool


class TaskSessionView(StrictModel):
    session_id: UUID
    state: TaskSessionState
    version: int
    goal: str
    plan_revision: int
    plan_hash: str | None = None
    next_interaction: NextInteraction
