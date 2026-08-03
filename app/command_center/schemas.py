from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


BindingExpression = Annotated[
    str,
    StringConstraints(pattern=r"^(task|steps|literal)\..+$"),
]


class _EvidenceModel(BaseModel):
    """Strict, already-redacted evidence accepted from a browser capture client."""

    model_config = ConfigDict(extra="forbid")


class ControlDescriptor(_EvidenceModel):
    """Semantic control metadata; it deliberately excludes the entered value."""

    role: str | None = None
    label: str | None = None
    accessible_name: str | None = None
    input_type: str | None = None
    selector_fingerprint: str
    required: bool | None = None
    enabled: bool | None = None


class PageDescriptor(_EvidenceModel):
    """A page identity without raw query values or browser storage."""

    origin: str
    path: str
    title: str | None = None
    query_parameter_names: list[str] = Field(default_factory=list)
    fingerprint: str


class PageMutationEvidence(_EvidenceModel):
    mutation_id: UUID
    client_sequence: int = Field(ge=1)
    occurred_at: datetime
    page: PageDescriptor
    mutation_type: Literal[
        "navigation", "route_change", "dom_change", "form_state_change"
    ]
    changed_control_fingerprints: list[str] = Field(default_factory=list)
    before_fingerprint: str | None = None
    after_fingerprint: str | None = None


class RecordedBrowserEvent(_EvidenceModel):
    event_id: UUID
    client_sequence: int = Field(ge=1)
    occurred_at: datetime
    event_type: Literal["click", "input", "select", "submit", "navigation"]
    page: PageDescriptor
    control: ControlDescriptor | None = None
    value_fingerprint: str | None = None
    mutation_ids: list[UUID] = Field(default_factory=list)


class RecordedNetworkExchange(_EvidenceModel):
    exchange_id: UUID
    client_sequence: int = Field(ge=1)
    started_at: datetime
    completed_at: datetime
    method: str
    path_template: str
    query_parameter_names: list[str] = Field(default_factory=list)
    request_fingerprint: str | None = None
    response_status: int
    response_fingerprint: str | None = None
    endpoint_fingerprint: str | None = None

    @model_validator(mode="after")
    def require_ordered_timestamps(self) -> RecordedNetworkExchange:
        if self.completed_at < self.started_at:
            raise ValueError("network exchange completion must not precede start")
        return self


class ExtensionEventBatch(_EvidenceModel):
    """One ordered, redacted extension upload for exactly one recording."""

    recording_id: UUID
    events: list[RecordedBrowserEvent | RecordedNetworkExchange] = Field(min_length=1)
    page_mutations: list[PageMutationEvidence] = Field(default_factory=list)
    redaction_summary: dict[str, int] = Field(default_factory=dict)

    @field_validator("redaction_summary")
    @classmethod
    def require_non_negative_redaction_counts(
        cls, value: dict[str, int]
    ) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("redaction counts must be non-negative")
        return value

    @model_validator(mode="after")
    def require_monotonic_client_sequence(self) -> ExtensionEventBatch:
        sequences = [event.client_sequence for event in self.events]
        sequences.extend(mutation.client_sequence for mutation in self.page_mutations)
        if len(sequences) != len(set(sequences)) or sequences != sorted(sequences):
            raise ValueError("extension client sequences must be unique and monotonic")
        return self


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
    capture_source: Literal["playwright", "browser_extension"] = "playwright"
    page_mutations: list[PageMutationEvidence] = Field(default_factory=list)
    redaction_summary: dict[str, int] = Field(default_factory=dict)


class InputBinding(BaseModel):
    tool_field: str
    expression: BindingExpression


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
    input_bindings: dict[str, BindingExpression]
    output_bindings: dict[str, str] = Field(default_factory=dict)
    side_effect: Literal["read", "write"]
    idempotency_key_template: str | None = None

    @field_validator("input_bindings")
    @classmethod
    def validate_bindings(
        cls,
        value: dict[str, BindingExpression],
    ) -> dict[str, BindingExpression]:
        for target in value:
            if not target.startswith(("body.", "path.", "query.")):
                raise ValueError(
                    "tool binding target must start with body., path., or query."
                )
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
    status: Literal[
        "candidate",
        "testing",
        "verified_candidate",
        "published",
        "rejected",
        "runtime_failed",
    ]
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
