from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    AfterValidator,
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

_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"^eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$"),
    re.compile(r"^sk-[A-Za-z0-9_-]{20,}$"),
    re.compile(r"^ya29\.[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{20,}$"),
)


def _require_non_credential_identifier(value: str) -> str:
    if any(pattern.fullmatch(value) for pattern in _CREDENTIAL_VALUE_PATTERNS):
        raise ValueError("evidence identifier must not contain a credential value")
    return value

EvidenceFingerprint = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^hmac-sha256:[a-f0-9]{64}$",
    ),
]
EvidenceIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    ),
    AfterValidator(_require_non_credential_identifier),
]
EvidencePath = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=2_048,
        pattern=r"^/[^\x00-\x1f\x7f?#]*$",
    ),
]
SemanticEvidenceText = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=256,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
EvidenceOrigin = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=512,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]

_SENSITIVE_TEXT_MARKERS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "token",
        "apikey",
        "password",
        "captcha",
        "localstorage",
        "filecontent",
    }
)


def _require_safe_semantic_text(value: str) -> str:
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    if any(marker in normalized for marker in _SENSITIVE_TEXT_MARKERS):
        raise ValueError("semantic evidence must not carry sensitive values")
    return value


class _EvidenceModel(BaseModel):
    """Strict, already-redacted evidence accepted from a browser capture client."""

    model_config = ConfigDict(extra="forbid")


class ControlDescriptor(_EvidenceModel):
    """Semantic control metadata; it deliberately excludes the entered value."""

    role: EvidenceIdentifier | None = None
    label: SemanticEvidenceText | None = None
    accessible_name: SemanticEvidenceText | None = None
    input_type: EvidenceIdentifier | None = None
    selector_fingerprint: EvidenceFingerprint
    required: bool | None = None
    enabled: bool | None = None

    @field_validator("label", "accessible_name")
    @classmethod
    def reject_sensitive_semantic_text(cls, value: str | None) -> str | None:
        return _require_safe_semantic_text(value) if value is not None else value


class PageDescriptor(_EvidenceModel):
    """A page identity without raw query values or browser storage."""

    origin: EvidenceOrigin
    path: EvidencePath
    title: SemanticEvidenceText | None = None
    query_parameter_names: list[EvidenceIdentifier] = Field(default_factory=list)
    fingerprint: EvidenceFingerprint

    @field_validator("origin")
    @classmethod
    def require_origin_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in parsed.netloc)
        ):
            raise ValueError("origin must contain only scheme, host, and optional port")
        try:
            _ = parsed.port
        except ValueError as error:
            raise ValueError("origin port must be valid") from error
        return value

    @field_validator("title")
    @classmethod
    def reject_sensitive_title(cls, value: str | None) -> str | None:
        return _require_safe_semantic_text(value) if value is not None else value


class PageMutationEvidence(_EvidenceModel):
    mutation_id: UUID
    client_sequence: int = Field(ge=1)
    occurred_at: datetime
    page: PageDescriptor
    mutation_type: Literal[
        "navigation", "route_change", "dom_change", "form_state_change"
    ]
    changed_control_fingerprints: list[EvidenceFingerprint] = Field(default_factory=list)
    before_fingerprint: EvidenceFingerprint | None = None
    after_fingerprint: EvidenceFingerprint | None = None


class RecordedBrowserEvent(_EvidenceModel):
    event_id: UUID
    client_sequence: int = Field(ge=1)
    occurred_at: datetime
    event_type: Literal["click", "input", "select", "submit", "navigation"]
    page: PageDescriptor
    control: ControlDescriptor | None = None
    value_fingerprint: EvidenceFingerprint | None = None
    mutation_ids: list[UUID] = Field(default_factory=list)


class RecordedNetworkExchange(_EvidenceModel):
    exchange_id: UUID
    client_sequence: int = Field(ge=1)
    started_at: datetime
    completed_at: datetime
    method: Annotated[
        str,
        StringConstraints(strict=True, min_length=3, max_length=10, pattern=r"^[A-Z]+$"),
    ]
    path_template: EvidencePath
    query_parameter_names: list[EvidenceIdentifier] = Field(default_factory=list)
    request_fingerprint: EvidenceFingerprint | None = None
    response_status: int
    response_fingerprint: EvidenceFingerprint | None = None
    endpoint_fingerprint: EvidenceFingerprint | None = None

    @model_validator(mode="after")
    def require_ordered_timestamps(self) -> RecordedNetworkExchange:
        if self.completed_at < self.started_at:
            raise ValueError("network exchange completion must not precede start")
        return self


class RedactionSummary(_EvidenceModel):
    """Fixed aggregate counters; no redacted field names or values are retained."""

    redacted_field_count: int = Field(default=0, ge=0)
    fingerprinted_value_count: int = Field(default=0, ge=0)
    dropped_evidence_count: int = Field(default=0, ge=0)


class ExtensionEventBatch(_EvidenceModel):
    """One ordered, redacted extension upload for exactly one recording."""

    batch_id: UUID = Field(default_factory=uuid4)
    recording_id: UUID
    events: list[RecordedBrowserEvent | RecordedNetworkExchange] = Field(min_length=1)
    page_mutations: list[PageMutationEvidence] = Field(default_factory=list)
    redaction_summary: RedactionSummary = Field(default_factory=RedactionSummary)

    @model_validator(mode="after")
    def require_monotonic_client_sequence(self) -> ExtensionEventBatch:
        event_sequences = [event.client_sequence for event in self.events]
        mutation_sequences = [mutation.client_sequence for mutation in self.page_mutations]
        if (
            event_sequences != sorted(event_sequences)
            or mutation_sequences != sorted(mutation_sequences)
            or len((*event_sequences, *mutation_sequences))
            != len(set((*event_sequences, *mutation_sequences)))
        ):
            raise ValueError(
                "extension client sequences must be unique and monotonic per evidence type"
            )
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
    redaction_summary: RedactionSummary = Field(default_factory=RedactionSummary)


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


class AnalysisUncertainty(BaseModel):
    description: str = Field(min_length=1)
    source_ui_event_ids: list[UUID] = Field(default_factory=list)
    source_exchange_ids: list[UUID] = Field(default_factory=list)


class TraceSegment(BaseModel):
    segment_id: EvidenceIdentifier
    sequence: int = Field(ge=1)
    classification: Literal[
        "business_action",
        "supporting_lookup",
        "verification_query",
        "navigation",
        "static_or_telemetry",
        "uncertain",
    ]
    summary: str = Field(min_length=1)
    source_ui_event_ids: list[UUID] = Field(default_factory=list)
    source_exchange_ids: list[UUID] = Field(default_factory=list)
    source_mutation_ids: list[UUID] = Field(default_factory=list)


class TraceSegmentation(BaseModel):
    summary: str = Field(min_length=1)
    segments: list[TraceSegment]
    ignored_ui_event_ids: list[UUID] = Field(default_factory=list)
    ignored_exchange_ids: list[UUID] = Field(default_factory=list)
    uncertainties: list[AnalysisUncertainty] = Field(default_factory=list)
    conclusive: bool


class APIAttributionSegment(BaseModel):
    segment_id: EvidenceIdentifier
    primary_tool_ids: list[str] = Field(default_factory=list)
    supporting_tool_ids: list[str] = Field(default_factory=list)
    verification_tool_ids: list[str] = Field(default_factory=list)
    primary_exchange_ids: list[UUID] = Field(default_factory=list)
    supporting_exchange_ids: list[UUID] = Field(default_factory=list)
    verification_exchange_ids: list[UUID] = Field(default_factory=list)
    ignored_exchange_ids: list[UUID] = Field(default_factory=list)
    uncertain_exchange_ids: list[UUID] = Field(default_factory=list)
    evidence_summary: str = Field(min_length=1)


class APIAttributionAnalysis(BaseModel):
    segments: list[APIAttributionSegment]
    uncertainties: list[AnalysisUncertainty] = Field(default_factory=list)
    attributable: bool


class FieldMapping(BaseModel):
    skill_input_name: EvidenceIdentifier
    api_target: Annotated[
        str,
        StringConstraints(pattern=r"^(query|path|body)\.[A-Za-z][A-Za-z0-9_.-]*$"),
    ]
    source_ui_event_ids: list[UUID] = Field(default_factory=list)
    source_exchange_ids: list[UUID] = Field(default_factory=list)
    transformation: str = Field(min_length=1, max_length=128)
    evidence_summary: str = Field(min_length=1)


class FieldMappingAnalysis(BaseModel):
    mappings: list[FieldMapping]
    uncertainties: list[AnalysisUncertainty] = Field(default_factory=list)
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
