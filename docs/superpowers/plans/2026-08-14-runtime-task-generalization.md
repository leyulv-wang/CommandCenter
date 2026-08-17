# Runtime Task Generalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent, generic TaskSession protocol that lets natural-language requests and Skill Action buttons select an existing Skill, collect missing inputs, confirm writes, execute safely, verify results, and recover without purchase-specific branches.

**Architecture:** Add focused TaskSession schema, policy, executor, and orchestration modules beside the existing CommandCenter runtime. Persist each session as a versioned JSON snapshot in SQLite, let agents propose semantic choices and plans, and apply deterministic validation to Tool allowlists, schemas, confirmation hashes, idempotency, retries, and state transitions. Keep legacy task-run endpoints intact while the Vue panel adopts the new `next_interaction` protocol.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, LangGraph/structured model runtime, httpx, pytest, Vue 3, TypeScript, Vite, Element Plus, Vitest.

## Global Constraints

- Run Python commands with `conda run -n langgraph`; do not hard-code AI credentials or values from `.env.ai`.
- Runtime generalization consumes existing Skills; browser recording, Skill learning, and browser replay are out of scope.
- Agents make semantic and business judgments; deterministic code enforces security, permissions, schemas, published Skill versions, idempotency, retry limits, confirmation, and auditability.
- The generic path must not match purchase keywords, know purchase field names, depend on sample IDs, or call a purchase-specific route.
- Simple scalar gaps use `question`; candidates use `selection`; objects, arrays, dates, or multi-field constraints use a JSON Schema `form`.
- Read-only plans execute without confirmation; every plan containing a write requires one confirmation bound to `session_id + plan_revision + plan_hash`.
- Any change to Skill version, business object, write target, arguments, steps, or side effects creates a new plan revision and invalidates prior confirmation.
- Only read calls and end-to-end idempotency-protected writes may retry transient transport failures or HTTP 502/503/504; validation, permission, business failures, and non-idempotent writes never auto-retry.
- Stop after a failed write, retain evidence for successful prior steps, and run compensation only when the Skill explicitly declares and validation approves it.
- Existing task-run, detail, purchase-progress, purchase-follow-up, and dynamic action endpoints remain compatible during migration.

## File Structure

- Create `app/command_center/task_session_schemas.py`: TaskSession state, plan, evidence, interaction, request, and response contracts.
- Create `app/command_center/task_session_policy.py`: state transition rules, canonical plan hashing, plan validation, confirmation validation, and retry classification.
- Create `app/command_center/task_session_inputs.py`: Skill input JSON Schema construction, trusted-value mapping, and hybrid interaction selection.
- Create `app/command_center/task_session_context.py`: bounded read-only Tool planning and evidence normalization.
- Create `app/command_center/task_session_executor.py`: resumable per-step Skill execution, bounded retries, checkpoint callbacks, and result verification handoff.
- Create `app/command_center/task_session_service.py`: TaskSession orchestration and the five public service operations.
- Modify `app/command_center/schemas.py`: backward-compatible structured Skill input schemas and explicit Tool idempotency metadata.
- Modify `app/command_center/models.py`: `TaskSessionRow` persistence model.
- Modify `app/command_center/repository.py`: create/get/compare-and-swap TaskSession snapshots.
- Modify `app/command_center/agents.py`: semantic TaskSession agent methods using structured output.
- Modify `app/command_center/tool_catalog.py`: expose declared Tool idempotency support from approved OpenAPI metadata.
- Modify `app/command_center/tool_executor.py`: precise transient/business error evidence and retry-safety calculation.
- Modify `app/command_center/router.py`: TaskSession HTTP contracts and routes without changing legacy routes.
- Modify `app/main.py`: compose the generic TaskSession dependencies and inject them into `CommandCenterService`.
- Modify `app/command_center/service.py`: narrow delegation methods only; keep existing task-run behavior.
- Create `frontend/src/components/TaskInteractionRenderer.vue`: render the six `next_interaction` variants.
- Create `frontend/src/components/DynamicSchemaForm.vue`: render supported JSON Schema object/array/date inputs.
- Modify `frontend/src/api/types.ts`: discriminated TaskSession and interaction types.
- Modify `frontend/src/api/commandCenter.ts`: five TaskSession API calls.
- Modify `frontend/src/components/NaturalLanguageTaskPanel.vue`: use TaskSession as the primary generic flow and keep legacy detail/progress compatibility.
- Create backend tests `tests/test_task_session_schemas.py`, `tests/test_task_session_policy.py`, `tests/test_task_session_inputs.py`, `tests/test_task_session_agents.py`, `tests/test_task_session_context.py`, `tests/test_task_session_executor.py`, `tests/test_task_session_service.py`, and `tests/test_task_session_contracts.py`.
- Modify backend tests `tests/test_command_center_repository.py`, `tests/test_command_center_api.py`, `tests/test_tool_executor.py`, `tests/test_structured_agents.py`, and `tests/test_real_mes_readonly_loop.py`.
- Create frontend tests `frontend/src/components/__tests__/TaskInteractionRenderer.spec.ts` and `frontend/src/components/__tests__/DynamicSchemaForm.spec.ts`.
- Modify frontend test `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`.

---

### Task 1: Define the TaskSession and Skill input contracts

**Files:**
- Create: `app/command_center/task_session_schemas.py`
- Modify: `app/command_center/schemas.py`
- Create: `tests/test_task_session_schemas.py`
- Modify: `tests/test_command_center_schemas.py`

**Interfaces:**
- Consumes: existing `SkillDefinition`, `SkillInput`, `StepResult`, and `VerificationResult`.
- Produces: `TaskSessionState`, `InteractionType`, `ParameterSource`, `ContextEvidence`, `PlannedStep`, `ExecutionPlan`, `TaskSessionSnapshot`, `TaskSessionView`, `CreateTaskSessionRequest`, `TaskSessionMessageRequest`, `TaskSessionInputRequest`, and `TaskSessionConfirmationRequest`.

- [ ] **Step 1: Write failing schema tests for the state and interaction union**

```python
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
import pytest

from app.command_center.task_session_schemas import (
    ConfirmationInteraction,
    NextInteraction,
    QuestionInteraction,
    TaskSessionSnapshot,
)


def test_next_interaction_is_discriminated_by_type():
    adapter = TypeAdapter(NextInteraction)
    value = adapter.validate_python({
        "type": "question",
        "prompt": "请输入报销金额",
        "field_names": ["amount"],
    })
    assert isinstance(value, QuestionInteraction)


def test_confirmation_requires_plan_identity():
    with pytest.raises(ValidationError):
        ConfirmationInteraction.model_validate({
            "type": "confirmation",
            "title": "确认提交",
            "summary": "创建一条报销记录",
            "plan_revision": 1,
        })


def test_session_rejects_interaction_that_does_not_match_state():
    with pytest.raises(ValidationError, match="interaction"):
        TaskSessionSnapshot.model_validate({
            "session_id": str(uuid4()),
            "state": "awaiting_confirmation",
            "version": 1,
            "goal": "创建报销记录",
            "principal": {
                "subject_id": "local-user",
                "tenant_id": "local",
                "permissions": ["command-center:execute"],
            },
            "next_interaction": {
                "type": "question",
                "prompt": "金额是多少",
                "field_names": ["amount"],
            },
        })
```

- [ ] **Step 2: Run the new schema tests and verify the module is missing**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_schemas.py -q`

Expected: FAIL with `ModuleNotFoundError: app.command_center.task_session_schemas`.

- [ ] **Step 3: Implement strict TaskSession contracts**

Create Pydantic models with `ConfigDict(extra="forbid")`. Use this exact public shape:

```python
TaskSessionState = Literal[
    "understanding", "resolving_context", "collecting_input",
    "awaiting_confirmation", "executing", "verifying",
    "succeeded", "failed",
]
InteractionType = Literal[
    "message", "question", "selection", "form", "confirmation", "result"
]

class ParameterSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["user_input", "trusted_context", "step_output"]
    reference: str = Field(min_length=1, max_length=512)

class ContextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    tool_id: str
    object_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime

class PrincipalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    permissions: frozenset[str] = Field(default_factory=frozenset)

class PlannedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    name: str
    tool_id: str
    side_effect: Literal["read", "write"]
    arguments: dict[str, Any]
    argument_sources: dict[str, ParameterSource]
    idempotency_key: str | None = None
    idempotency_guarantee: Literal["none", "header", "intrinsic"] = "none"

class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: UUID
    skill_version: int = Field(ge=1)
    summary: str
    target_objects: list[str] = Field(default_factory=list)
    selected_object: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[PlannedStep] = Field(min_length=1)
    verification_condition_ids: list[str] = Field(default_factory=list)
    compensation_step_ids: list[str] = Field(default_factory=list)

class TaskSessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    state: TaskSessionState
    version: int = Field(ge=1)
    goal: str
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
    plan_revision: int = 0
    plan: ExecutionPlan | None = None
    plan_hash: str | None = None
    confirmation_token_hash: str | None = None
    confirmation_consumed: bool = False
    step_results: list[StepResult] = Field(default_factory=list)
    verification: VerificationResult | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    next_interaction: NextInteraction

class TaskSessionHint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str | None = None
    skill_id: UUID | None = None
    skill_version: int | None = None
    parent_run_id: UUID | None = None
    selected_record_id: str | None = None
    selected_object: dict[str, Any] | None = None

class CreateTaskSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=2_000)
    hint: TaskSessionHint | None = None

class TaskSessionMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=2_000)

class TaskSessionInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    values: dict[str, Any]

class TaskSessionConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_token: str = Field(min_length=32, max_length=256)
    approved: bool

class TaskSessionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    state: TaskSessionState
    version: int
    goal: str
    plan_revision: int
    plan_hash: str | None = None
    next_interaction: NextInteraction
```

Define the six interaction models and `NextInteraction` as an annotated discriminated union on `type`. A `selection` carries a `field_name` plus `{value, label, description}` options; clients submit the chosen value through `TaskSessionInputRequest.values[field_name]`. Reserve `_skill_id` and `_object_id` for server-driven Skill and business-object selection. A `confirmation` carries `plan_revision`, `plan_hash`, `confirmation_token`, systems, target objects, and a fully expanded list of write steps. A `result` carries `status: Literal["succeeded", "failed", "partial_failure", "verification_incomplete", "unknown"]`, optional stable `code`, and step summaries. Use `code="no_matching_published_skill"` when resolution finds no eligible Skill. Add a model validator mapping `awaiting_confirmation` to `confirmation`, terminal states to `result`, and `collecting_input` to `question | selection | form`. `principal` is supplied by the trusted service composition, never by `CreateTaskSessionRequest`, and is omitted from `TaskSessionView`.

- [ ] **Step 4: Extend `SkillInput` without breaking stored Skills**

Change the field to accept object inputs and optional JSON Schema while keeping all old payloads valid. Also add an explicit compensation declaration; compensation is never inferred from an ordinary Skill step:

```python
class SkillInput(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    description: str
    required: bool = True
    source_hint: str | None = None
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_schema_for_complex_input(self) -> SkillInput:
        if self.type in {"array", "object"} and self.json_schema is None:
            # Backward compatibility: old published array inputs remain readable;
            # InputCollector will reject interactive rendering until schema exists.
            return self
        if self.json_schema and self.json_schema.get("type") != self.type:
            raise ValueError("json_schema type must match Skill input type")
        return self

class SkillCompensationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger_step_id: str
    compensates_step_ids: list[str] = Field(min_length=1)
    step: SkillStep

class SkillDefinition(BaseModel):
    # Keep all existing fields unchanged.
    compensations: list[SkillCompensationDefinition] = Field(default_factory=list)
```

Add tests proving an old array input loads unchanged, a mismatched `json_schema.type` fails, old Skills without `compensations` load as an empty list, and every compensation references existing ordinary step IDs while its compensation `step.side_effect` is `write` and has an idempotency template.

- [ ] **Step 5: Run schema tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_schemas.py tests/test_command_center_schemas.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the contract**

```powershell
git add app/command_center/task_session_schemas.py app/command_center/schemas.py tests/test_task_session_schemas.py tests/test_command_center_schemas.py
git commit -m "feat: define task session protocol"
```

### Task 2: Persist sessions with optimistic concurrency

**Files:**
- Modify: `app/command_center/models.py`
- Modify: `app/command_center/repository.py`
- Modify: `tests/test_command_center_repository.py`

**Interfaces:**
- Consumes: `TaskSessionSnapshot` from Task 1.
- Produces: `TaskSessionConflictError`, `CommandCenterRepository.create_task_session(snapshot)`, `get_task_session(session_id)`, `update_task_session(snapshot, *, expected_version)`, and `list_task_sessions_by_state(states)`.

- [ ] **Step 1: Write failing repository tests**

```python
def test_repository_compare_and_swaps_task_session(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    snapshot = task_session_snapshot(version=1)
    repository.create_task_session(snapshot)

    updated = snapshot.model_copy(update={"version": 2, "goal": "更新后的目标"})
    repository.update_task_session(updated, expected_version=1)

    assert repository.get_task_session(snapshot.session_id).version == 2
    with pytest.raises(TaskSessionConflictError):
        repository.update_task_session(
            updated.model_copy(update={"version": 3}),
            expected_version=1,
        )


def test_repository_rejects_duplicate_task_session(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    snapshot = task_session_snapshot(version=1)
    repository.create_task_session(snapshot)
    with pytest.raises(TaskSessionConflictError):
        repository.create_task_session(snapshot)


def test_repository_lists_only_resumable_states(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    repository.create_task_session(task_session_snapshot(state="executing"))
    repository.create_task_session(task_session_snapshot(state="succeeded"))
    rows = repository.list_task_sessions_by_state({"executing", "verifying"})
    assert [row.state for row in rows] == ["executing"]
```

- [ ] **Step 2: Run the repository tests and verify they fail**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_repository.py -q`

Expected: FAIL because TaskSession repository methods do not exist.

- [ ] **Step 3: Add the persistence row and compare-and-swap methods**

Add this model:

```python
class TaskSessionRow(Base):
    __tablename__ = "task_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Use a single SQL `UPDATE task_sessions SET state, version, payload_json, updated_at WHERE session_id = :id AND version = :expected_version` operation and require `rowcount == 1`:

```python
class TaskSessionConflictError(RuntimeError):
    pass

def create_task_session(self, snapshot: TaskSessionSnapshot) -> TaskSessionSnapshot:
    with self.session_factory() as session:
        if session.get(TaskSessionRow, str(snapshot.session_id)) is not None:
            raise TaskSessionConflictError("task session already exists")
        session.add(TaskSessionRow(
            session_id=str(snapshot.session_id),
            state=snapshot.state,
            version=snapshot.version,
            payload_json=snapshot.model_dump_json(),
            updated_at=datetime.now(UTC),
        ))
        session.commit()
    return snapshot

def get_task_session(self, session_id: UUID) -> TaskSessionSnapshot:
    with self.session_factory() as session:
        row = session.get(TaskSessionRow, str(session_id))
        if row is None:
            raise KeyError(f"Task session not found: {session_id}")
        return TaskSessionSnapshot.model_validate_json(row.payload_json)

def update_task_session(
    self,
    snapshot: TaskSessionSnapshot,
    *,
    expected_version: int,
) -> TaskSessionSnapshot:
    statement = (
        update(TaskSessionRow)
        .where(
            TaskSessionRow.session_id == str(snapshot.session_id),
            TaskSessionRow.version == expected_version,
        )
        .values(
            state=snapshot.state,
            version=snapshot.version,
            payload_json=snapshot.model_dump_json(),
            updated_at=datetime.now(UTC),
        )
    )
    with self.session_factory() as session:
        result = session.execute(statement)
        if result.rowcount != 1:
            session.rollback()
            raise TaskSessionConflictError("task session version conflict")
        session.commit()
    return snapshot

def list_task_sessions_by_state(
    self,
    states: set[TaskSessionState],
) -> list[TaskSessionSnapshot]:
    with self.session_factory() as session:
        rows = session.scalars(
            select(TaskSessionRow)
            .where(TaskSessionRow.state.in_(sorted(states)))
            .order_by(TaskSessionRow.updated_at, TaskSessionRow.session_id)
        ).all()
        return [TaskSessionSnapshot.model_validate_json(row.payload_json) for row in rows]
```

Serialize with `snapshot.model_dump_json()` and deserialize with `TaskSessionSnapshot.model_validate_json()`. Store no separate credential fields.

- [ ] **Step 4: Run repository tests**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit persistence**

```powershell
git add app/command_center/models.py app/command_center/repository.py tests/test_command_center_repository.py
git commit -m "feat: persist versioned task sessions"
```

### Task 3: Enforce plan, confirmation, idempotency, and retry policy

**Files:**
- Create: `app/command_center/task_session_policy.py`
- Modify: `app/command_center/tool_catalog.py`
- Modify: `app/command_center/tool_executor.py`
- Modify: `external_systems/common.py`
- Create: `tests/test_task_session_policy.py`
- Modify: `tests/test_tool_executor.py`
- Modify: `tests/test_external_systems.py`

**Interfaces:**
- Consumes: `ExecutionPlan`, `SkillDefinition`, `ToolCatalog`, `ToolDefinition`, and `StepResult`.
- Produces: `PlanValidationError`, `ValidatedPlan`, `canonical_plan_hash(plan)`, `issue_confirmation_token()`, `confirmation_token_hash(token)`, `validate_confirmation`, and `RetryDecision classify_retry(step, result, attempt)`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_plan_validator_rejects_tool_not_pinned_by_skill():
    with pytest.raises(PlanValidationError, match="Skill step"):
        validator.validate(
            plan_with_tool("other:delete"),
            published_skill(),
            principal=allowed_principal(),
        )


def test_plan_validator_rejects_untraceable_argument():
    plan = valid_plan()
    plan.steps[0].argument_sources.pop("body.amount")
    with pytest.raises(PlanValidationError, match="source"):
        validator.validate(plan, published_skill(), principal=allowed_principal())


def test_plan_validator_enforces_tool_permission():
    with pytest.raises(PermissionError, match="Tool permission"):
        validator.validate(
            valid_plan(),
            published_skill(),
            principal=PrincipalContext(
                subject_id="employee-9",
                tenant_id="tenant-a",
                permissions=frozenset(),
            ),
        )


def test_plan_validator_rejects_sensitive_parameter_sources():
    plan = valid_plan()
    plan.steps[0].argument_sources["body.amount"] = ParameterSource(
        kind="trusted_context",
        reference="response.authorization",
    )
    with pytest.raises(PlanValidationError, match="sensitive"):
        validator.validate(plan, published_skill(), principal=allowed_principal())


def test_confirmation_is_bound_to_revision_and_hash():
    token = issue_confirmation_token()
    token_hash = confirmation_token_hash(token)
    validate_confirmation(
        supplied_token=token,
        stored_token_hash=token_hash,
        supplied_revision=2,
        stored_revision=2,
        supplied_plan_hash=canonical_plan_hash(valid_plan()),
        stored_plan_hash=canonical_plan_hash(valid_plan()),
        consumed=False,
    )
    with pytest.raises(ConfirmationError):
        validate_confirmation(
            supplied_token=token,
            stored_token_hash=token_hash,
            supplied_revision=1,
            stored_revision=2,
            supplied_plan_hash=canonical_plan_hash(valid_plan()),
            stored_plan_hash=canonical_plan_hash(valid_plan()),
            consumed=False,
        )


@pytest.mark.parametrize("status_code", [502, 503, 504])
def test_idempotent_write_retries_only_transient_status(status_code):
    decision = classify_retry(
        write_step(idempotency_guarantee="header"),
        failed_result(error={"category": "transient", "status_code": status_code}),
        attempt=1,
    )
    assert decision.retry is True


def test_non_idempotent_write_never_retries_uncertain_response():
    decision = classify_retry(
        write_step(idempotency_guarantee="none"),
        failed_result(error={"category": "transient", "code": "ReadTimeout"}),
        attempt=1,
    )
    assert decision == RetryDecision(retry=False, terminal_status="unknown")
```

- [ ] **Step 2: Run policy tests and verify they fail**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_policy.py tests/test_tool_executor.py -q`

Expected: FAIL because policy functions and Tool idempotency metadata do not exist.

- [ ] **Step 3: Declare end-to-end Tool idempotency explicitly**

Add to `ToolDefinition`:

```python
idempotency_guarantee: Literal["none", "header", "intrinsic"] = "none"
```

Parse only approved OpenAPI extensions:

```python
raw_mode = operation.get("x-command-center-idempotency", "none")
if raw_mode not in {"none", "header", "intrinsic"}:
    raise ValueError("unsupported Tool idempotency guarantee")
```

For `header`, `ToolExecutor` sends `Idempotency-Key`; for `intrinsic`, it records the key fingerprint but does not assume a header contract. A key on an `idempotency_guarantee="none"` Tool must not make `retry_safe=True`.

Annotate the local purchase-follow-up POST route with `openapi_extra={"x-command-center-idempotency": "header"}` because that endpoint already requires `Idempotency-Key` and persists the first response. Add a test against `/openapi.json` proving the extension is present. Do not infer idempotency merely because an HTTP header parameter exists.

- [ ] **Step 4: Implement canonical hashing and deterministic validation**

```python
def canonical_plan_hash(plan: ExecutionPlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

class PlanValidator:
    def __init__(self, catalog: Any, permission_checker: Callable[[PrincipalContext, Any], bool]):
        self.catalog = catalog
        self.permission_checker = permission_checker

    def validate(
        self,
        plan: ExecutionPlan,
        skill: SkillDefinition,
        *,
        principal: PrincipalContext,
    ) -> ValidatedPlan:
        if skill.status != "published":
            raise PlanValidationError("generic sessions require a published Skill")
        if (plan.skill_id, plan.skill_version) != (skill.skill_id, skill.version):
            raise PlanValidationError("plan does not pin the selected Skill version")
        if [step.step_id for step in plan.steps] != [step.step_id for step in skill.steps]:
            raise PlanValidationError("plan steps do not match Skill step order")
        validated_steps: list[PlannedStep] = []
        for planned, declared in zip(plan.steps, skill.steps, strict=True):
            if (planned.tool_id, planned.side_effect) != (
                declared.tool_id, declared.side_effect
            ):
                raise PlanValidationError("plan step does not match Skill step")
            tool = self.catalog.get(planned.tool_id)
            if not self.permission_checker(principal, tool):
                raise PermissionError("Tool permission denied")
            validate_tool_arguments(tool, planned.arguments, require_read=False)
            binding_targets = set(declared.input_bindings)
            if binding_targets != set(planned.argument_sources):
                raise PlanValidationError("every Skill binding requires one source")
            if any(is_sensitive_reference(source.reference) for source in planned.argument_sources.values()):
                raise PlanValidationError("sensitive values cannot be plan parameters")
            if planned.side_effect == "write" and (
                not plan.target_objects or not planned.idempotency_key
            ):
                raise PlanValidationError("write steps require target and stable key")
            validated_steps.append(planned.model_copy(update={
                "idempotency_guarantee": tool.idempotency_guarantee,
            }))
        declared_compensations = {
            item.step.step_id for item in skill.compensations
        }
        if set(plan.compensation_step_ids) - declared_compensations:
            raise PlanValidationError("plan references undeclared compensation")
        validated = plan.model_copy(update={"steps": validated_steps})
        return ValidatedPlan(plan=validated, plan_hash=canonical_plan_hash(validated))
```

Require one source for every immutable Skill binding target, such as `body.amount` or `body.items`. A source attached to `body.items` covers the complete validated array value and is not expanded into index-specific provenance. Reject extra source targets and materialized arguments not produced by a declared binding. `ValidatedPlan` contains exactly `plan: ExecutionPlan` and `plan_hash: str`.

Implement the default permission checker with exact, configurable scopes:

```python
def default_tool_permission_checker(principal: PrincipalContext, tool: Any) -> bool:
    scopes = principal.permissions
    return bool({
        "command-center:*",
        f"tool:{tool.tool_id}",
        f"system:{tool.system_code}:{tool.side_effect}",
    } & scopes)
```

The local single-user composition receives `command-center:*`. A future authentication adapter replaces the trusted principal provider without changing request bodies or the TaskSession protocol.

Use `secrets.token_urlsafe(32)` for confirmation tokens and store only a SHA-256 hash. Compare token hashes with `hmac.compare_digest`.

- [ ] **Step 5: Classify Tool failures without leaking response bodies**

Update `ToolExecutor` to put these stable fields in `StepResult.error`:

```python
{
    "category": "transient" | "validation" | "permission" | "business" | "protocol",
    "code": "ReadTimeout" | "ConnectError" | "RemoteProtocolError" | "HTTPStatusError" | "ResponseTooLarge" | "InvalidJSON" | "InvalidArguments",
    "status_code": int | None,
    "message": safe_message,
}
```

Map timeouts, connection errors, and 502/503/504 to `transient`; 400/409/422 to `business`; 401/403 to `permission`; local argument/schema failures to `validation`; response-size/JSON protocol failures to `protocol`. Do not store response bodies. Set `retry_safe` only for reads or Tools declaring `header | intrinsic` idempotency with a stable key.

- [ ] **Step 6: Implement bounded retry decisions**

```python
MAX_ATTEMPTS = 3

@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    terminal_status: Literal["failed", "unknown"] = "failed"

def classify_retry(step: PlannedStep, result: StepResult, attempt: int) -> RetryDecision:
    if result.status != "failed" or attempt >= MAX_ATTEMPTS:
        return RetryDecision(False)
    transient = result.error.get("category") == "transient"
    if step.side_effect == "read":
        return RetryDecision(transient)
    protected = step.idempotency_guarantee in {"header", "intrinsic"}
    if transient and protected:
        return RetryDecision(True)
    if transient and not protected:
        return RetryDecision(False, "unknown")
    return RetryDecision(False)
```

- [ ] **Step 7: Run policy and executor tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_policy.py tests/test_tool_executor.py tests/test_tool_catalog.py tests/test_external_systems.py -q`

Expected: PASS.

- [ ] **Step 8: Commit policy**

```powershell
git add app/command_center/task_session_policy.py app/command_center/tool_catalog.py app/command_center/tool_executor.py external_systems/common.py tests/test_task_session_policy.py tests/test_tool_executor.py tests/test_tool_catalog.py tests/test_external_systems.py
git commit -m "feat: enforce generic execution policy"
```

### Task 4: Build hybrid input collection from Skill schemas

**Files:**
- Create: `app/command_center/task_session_inputs.py`
- Create: `tests/test_task_session_inputs.py`

**Interfaces:**
- Consumes: `SkillDefinition`, `SkillInput`, existing collected values, trusted context values, and `ParameterSource`.
- Produces: `InputCollectionResult` and `collect_skill_inputs(skill, supplied, trusted_context)`.

- [ ] **Step 1: Write failing hybrid-mode tests**

```python
def test_one_missing_scalar_returns_question():
    result = collect_skill_inputs(
        scalar_skill("amount", "number"),
        supplied={},
        trusted_context={},
    )
    assert result.complete is False
    assert result.interaction.type == "question"
    assert result.interaction.field_names == ["amount"]


def test_complex_array_returns_schema_form():
    skill = skill_with_input({
        "name": "items",
        "type": "array",
        "description": "费用明细",
        "json_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "amount"],
                "properties": {
                    "category": {"type": "string", "title": "类别"},
                    "amount": {"type": "number", "title": "金额"},
                },
            },
        },
    })
    result = collect_skill_inputs(skill, supplied={}, trusted_context={})
    assert result.interaction.type == "form"
    assert result.interaction.schema["properties"]["items"]["type"] == "array"


def test_trusted_context_value_records_provenance():
    result = collect_skill_inputs(
        scalar_skill("employee_id", "string", source_hint="employee.id"),
        supplied={},
        trusted_context={"employee": {"id": "E-9"}},
    )
    assert result.values == {"employee_id": "E-9"}
    assert result.sources["employee_id"].kind == "trusted_context"


def test_complex_input_without_json_schema_is_not_guessed():
    with pytest.raises(InputSchemaError, match="json_schema"):
        collect_skill_inputs(old_array_skill(), supplied={}, trusted_context={})
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_inputs.py -q`

Expected: FAIL because `task_session_inputs` does not exist.

- [ ] **Step 3: Implement deterministic interaction selection**

```python
class InputCollectionResult(BaseModel):
    complete: bool
    values: dict[str, Any]
    sources: dict[str, ParameterSource]
    interaction: QuestionInteraction | FormInteraction | None = None

def collect_skill_inputs(
    skill: SkillDefinition,
    *,
    supplied: dict[str, Any],
    trusted_context: dict[str, Any],
) -> InputCollectionResult:
    definitions = {item.name: item for item in skill.inputs}
    unknown = set(supplied) - set(definitions)
    if unknown:
        raise InputSchemaError(f"unknown Skill inputs: {sorted(unknown)}")
    values: dict[str, Any] = {}
    sources: dict[str, ParameterSource] = {}
    for name, raw in supplied.items():
        values[name] = validate_input_value(definitions[name], raw)
        sources[name] = ParameterSource(kind="user_input", reference=name)
    for item in skill.inputs:
        if item.name in values or not item.source_hint:
            continue
        found, raw = resolve_data_path(trusted_context, item.source_hint)
        if found:
            values[item.name] = validate_input_value(item, raw)
            sources[item.name] = ParameterSource(
                kind="trusted_context",
                reference=item.source_hint,
            )
    missing = [item for item in skill.inputs if item.required and item.name not in values]
    if not missing:
        return InputCollectionResult(complete=True, values=values, sources=sources)
    complex_gap = len(missing) > MAX_CONVERSATIONAL_FIELDS or any(
        requires_form(item) for item in missing
    )
    interaction = (
        build_form_interaction(missing, values)
        if complex_gap
        else QuestionInteraction(
            type="question",
            prompt="；".join(item.description for item in missing),
            field_names=[item.name for item in missing],
        )
    )
    return InputCollectionResult(
        complete=False,
        values=values,
        sources=sources,
        interaction=interaction,
    )
```

Implement `resolve_data_path` as dot-separated dictionary/list traversal with no `eval`; it returns `(False, None)` on a missing path. Implement `validate_input_value` with explicit recursive validation for the supported JSON Schema subset: object `properties`/`required`, array `items`, scalar `type`, `enum`, and string `format` values `date`/`date-time`. Reject `$ref`, `oneOf`, `anyOf`, and unknown types with `InputSchemaError`; do not add a new dependency. `build_form_interaction` creates one object schema whose `properties` are the missing inputs and whose `required` list contains required names. The `>2 fields` rule is an interaction complexity boundary, not a business rule. Keep it as a named constant `MAX_CONVERSATIONAL_FIELDS = 2` so product configuration can replace it later. Date means a string schema with `format: "date"` or `"date-time"` and always uses a form.

- [ ] **Step 4: Run input tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_inputs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit input collection**

```powershell
git add app/command_center/task_session_inputs.py tests/test_task_session_inputs.py
git commit -m "feat: collect generic skill inputs"
```

### Task 5: Add TaskSession semantic agent methods

**Files:**
- Modify: `app/command_center/agents.py`
- Modify: `app/command_center/task_session_schemas.py`
- Create: `app/command_center/task_session_context.py`
- Create: `tests/test_task_session_agents.py`
- Create: `tests/test_task_session_context.py`

**Interfaces:**
- Consumes: bounded published Skill summaries, the user goal, trusted object candidates, collected inputs, and context evidence.
- Produces: `TaskIntentResolution`, `TaskContextInterpretation`, `TaskPlanProposal`, `AgentSuite.resolve_task_intent`, `AgentSuite.interpret_task_context`, `AgentSuite.propose_task_plan`, and `ReadOnlyTaskContextResolver.resolve`.

- [ ] **Step 1: Write failing structured-agent tests**

```python
def test_intent_agent_receives_business_context_and_exact_skill_versions():
    model = CapturingStructuredModel({
        "status": "matched",
        "skill_id": str(SKILL_ID),
        "skill_version": 3,
        "candidate_object_ids": ["expense-42"],
        "summary": "使用报销 Skill 处理所选单据",
    })
    agents = AgentSuite(model)
    result = agents.resolve_task_intent(
        goal="提交这张报销单",
        skills=[published_expense_skill(version=3)],
        object_candidates=[{"id": "expense-42", "title": "差旅报销"}],
    )
    assert result.skill_version == 3
    assert result.extracted_inputs == {}
    assert "expense-42" in model.last_prompt
    assert "采购" not in model.last_prompt


def test_plan_agent_must_cite_parameter_sources():
    model = CapturingStructuredModel({
        "summary": "创建报销记录",
        "target_object_ids": ["expense-42"],
        "argument_sources": {
            "create.body.amount": {
                "kind": "user_input",
                "reference": "amount",
            }
        },
    })
    proposal = AgentSuite(model).propose_task_plan(
        goal="创建报销记录",
        skill=published_expense_skill(),
        selected_object={"id": "expense-42"},
        inputs={"amount": 88},
        input_sources={
            "amount": ParameterSource(kind="user_input", reference="amount")
        },
        evidence=[],
    )
    assert proposal.argument_sources["create.body.amount"].reference == "amount"
```

- [ ] **Step 2: Run tests and verify the methods are absent**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_agents.py -q`

Expected: FAIL with missing TaskSession agent schemas or methods.

- [ ] **Step 3: Define bounded agent outputs**

```python
class TaskIntentResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["matched", "needs_skill_selection", "needs_object_selection", "not_applicable"]
    skill_id: UUID | None = None
    skill_version: int | None = None
    candidate_skill_ids: list[UUID] = Field(default_factory=list, max_length=10)
    candidate_object_ids: list[str] = Field(default_factory=list, max_length=50)
    extracted_inputs: dict[str, Any] = Field(default_factory=dict)
    summary: str

class ContextObjectCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str
    label: str
    evidence_id: str
    record_path: str

class TaskContextInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[ContextObjectCandidate] = Field(default_factory=list, max_length=50)
    trusted_value_paths: dict[str, str] = Field(default_factory=dict, max_length=50)
    summary: str

class TaskPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    target_object_ids: list[str]
    argument_sources: dict[str, ParameterSource]
```

The agent may select only exact IDs included in the prompt. It does not invent steps or Tools; deterministic compilation uses the selected immutable `SkillDefinition.steps`.

`extracted_inputs` may contain only names declared by the selected Skill, and code validates every value with `validate_input_value`; record its source as `ParameterSource(kind="user_input", reference="goal")`. Add a test where the goal contains employee ID `E-9` and assert the service does not ask for it again.

- [ ] **Step 4: Add `AgentSuite` methods using the existing structured runtime**

```python
def resolve_task_intent(
    self,
    *,
    goal: str,
    skills: list[SkillDefinition],
    object_candidates: list[dict[str, Any]],
) -> TaskIntentResolution:
    payload = bounded_task_intent_payload(skills, object_candidates)
    return self.model.generate(
        TaskIntentResolution,
        TASK_INTENT_PROMPT.format(goal=goal, payload=json.dumps(payload, ensure_ascii=False)),
    )

def propose_task_plan(
    self,
    *,
    goal: str,
    skill: SkillDefinition,
    selected_object: dict[str, Any] | None,
    inputs: dict[str, Any],
    input_sources: dict[str, ParameterSource],
    evidence: list[ContextEvidence],
) -> TaskPlanProposal:
    payload = bounded_task_plan_payload(
        skill=skill,
        selected_object=selected_object,
        inputs=inputs,
        input_sources=input_sources,
        evidence=evidence,
    )
    return self.model.generate(
        TaskPlanProposal,
        TASK_PLAN_PROMPT.format(goal=goal, payload=json.dumps(payload, ensure_ascii=False)),
    )

def interpret_task_context(
    self,
    *,
    goal: str,
    skill: SkillDefinition,
    evidence: list[ContextEvidence],
) -> TaskContextInterpretation:
    payload = bounded_context_evidence_payload(evidence)
    interpretation = self.model.generate(
        TaskContextInterpretation,
        TASK_CONTEXT_PROMPT.format(
            goal=goal,
            skill=compact_skill(skill),
            payload=json.dumps(payload, ensure_ascii=False),
        ),
    )
    validate_interpretation_paths(interpretation, evidence)
    return interpretation
```

Bound prompt payloads using the existing Skill summary limits. Explicitly instruct the model that it proposes semantic mappings, while code supplies Skill step order, Tool IDs, side effects, and security policy. Return `not_applicable` instead of guessing when no Skill fits. `validate_interpretation_paths` resolves each `evidence_id + record_path`, requires the value to be a dictionary, and requires `object_id` to equal the selected record's visible `id` value; it rejects invented paths or IDs. For systems whose stable identity field is not `id`, the published Skill Action's `object_id_field` supplies that field name.

- [ ] **Step 5: Write and implement the bounded read-only context resolver**

```python
def test_context_resolver_rejects_agent_write_plan():
    agents = PlanningAgents(direct_plan(tool_id="finance:create-expense"))
    resolver = ReadOnlyTaskContextResolver(
        agents=agents,
        tools=lambda: [read_tool(), write_tool()],
        runner=recording_direct_runner(),
        redactor=test_redactor(),
    )
    with pytest.raises(ValueError, match="read-only"):
        resolver.resolve(goal="读取员工资料", selected_object={"id": "E-9"})


def test_context_resolver_returns_normalized_evidence():
    resolver = resolver_with_read_result({"id": "E-9", "department": "研发"})
    evidence = resolver.resolve(goal="读取员工资料", selected_object={"id": "E-9"})
    assert evidence[0].tool_id == "hr:get-employee"
    assert evidence[0].object_id == "E-9"
    assert evidence[0].output["department"] == "研发"
```

Implement this exact interface in `task_session_context.py`:

```python
class ReadOnlyTaskContextResolver:
    def __init__(
        self,
        *,
        agents: Any,
        tools: Callable[[], list[Any]],
        runner: DirectToolRunner,
        redactor: TraceRedactor,
    ):
        self.agents = agents
        self.tools = tools
        self.runner = runner
        self.redactor = redactor

    def resolve(
        self,
        *,
        goal: str,
        selected_object: dict[str, Any] | None,
    ) -> list[ContextEvidence]:
        available = [tool for tool in self.tools() if tool.side_effect == "read"]
        plan = self.agents.plan_tool_request(
            user_request=goal,
            task_context={"selected_object": selected_object},
            tools=available,
        )
        if plan.status == "needs_input":
            return []
        if plan.status != "matched":
            return []
        if any(self.runner.catalog.get(step.tool_id).side_effect != "read" for step in plan.steps):
            raise ValueError("context resolution is read-only")
        run = self.runner.run(plan, run_id=uuid4())
        if run.status != "succeeded":
            raise ContextResolutionError(run.step_results)
        object_id = str(selected_object.get("id")) if selected_object and selected_object.get("id") else None
        return [
            ContextEvidence(
                evidence_id=f"context:{step.step_id}",
                tool_id=step.tool_id,
                object_id=object_id,
                arguments=next(item.arguments for item in plan.steps if item.step_id == step.step_id),
                output=self.redactor.redact_payload(step.normalized_output),
                observed_at=step.ended_at,
            )
            for step in run.step_results
        ]
```

The resolver passes only read Tool definitions and independently rechecks each returned Tool before execution. Add a test proving sensitive response keys are redacted before `ContextEvidence` is returned or persisted.

- [ ] **Step 6: Run agent, context, and existing AgentSuite tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_agents.py tests/test_task_session_context.py tests/test_structured_agents.py tests/test_direct_tool_runner.py -q`

Expected: PASS.

- [ ] **Step 7: Commit agent and context capabilities**

```powershell
git add app/command_center/agents.py app/command_center/task_session_schemas.py app/command_center/task_session_context.py tests/test_task_session_agents.py tests/test_task_session_context.py
git commit -m "feat: add task session agent judgments"
```

### Task 6: Execute and resume Skill steps safely

**Files:**
- Create: `app/command_center/task_session_executor.py`
- Create: `tests/test_task_session_executor.py`

**Interfaces:**
- Consumes: a validated `ExecutionPlan`, immutable `SkillDefinition`, prior `StepResult` evidence, `ToolExecutor.execute(ExecutionCommand)`, and a checkpoint callback.
- Produces: `TaskExecutionOutcome` and `ResumableTaskExecutor.execute`.

- [ ] **Step 1: Write failing executor tests**

```python
def test_executor_skips_checkpointed_success_after_restart():
    tool_executor = RecordingExecutor()
    prior = succeeded_result(step_id="read-source", output={"id": "42"})
    outcome = ResumableTaskExecutor(tool_executor, redactor=test_redactor()).execute(
        plan=two_step_plan(),
        skill=two_step_skill(),
        prior_results=[prior],
        checkpoint=lambda result: None,
    )
    assert [call.step_id for call in tool_executor.calls] == ["create-target"]
    assert outcome.status == "succeeded"


def test_executor_retries_transient_idempotent_write_with_same_key():
    tool_executor = SequenceExecutor(
        failed_result(category="transient", code="ReadTimeout"),
        succeeded_result(output={"id": "created-1"}),
    )
    ResumableTaskExecutor(
        tool_executor,
        redactor=test_redactor(),
        backoff=lambda _: None,
    ).execute(
        plan=idempotent_write_plan(),
        skill=idempotent_write_skill(),
        prior_results=[],
        checkpoint=lambda result: None,
    )
    assert len(tool_executor.calls) == 2
    assert tool_executor.calls[0].idempotency_key == tool_executor.calls[1].idempotency_key


def test_executor_stops_after_business_failure_without_future_writes():
    tool_executor = SequenceExecutor(
        succeeded_result(step_id="create-a"),
        failed_result(step_id="create-b", category="business"),
    )
    outcome = ResumableTaskExecutor(tool_executor, redactor=test_redactor()).execute(
        plan=three_write_plan(),
        skill=three_write_skill(),
        prior_results=[],
        checkpoint=lambda result: None,
    )
    assert len(tool_executor.calls) == 2
    assert outcome.status == "partial_failure"


def test_executor_reports_unknown_for_unprotected_write_timeout():
    outcome = ResumableTaskExecutor(
        SequenceExecutor(failed_result(category="transient", code="ReadTimeout")),
        redactor=test_redactor(),
    ).execute(
        plan=unprotected_write_plan(),
        skill=unprotected_write_skill(),
        prior_results=[],
        checkpoint=lambda result: None,
    )
    assert outcome.status == "unknown"
```

- [ ] **Step 2: Run executor tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_executor.py -q`

Expected: FAIL because `ResumableTaskExecutor` is missing.

- [ ] **Step 3: Implement per-step resume and checkpoints**

```python
class TaskExecutionOutcome(BaseModel):
    status: Literal["succeeded", "failed", "partial_failure", "unknown"]
    step_results: list[StepResult]
    outputs: dict[str, Any]

class ResumableTaskExecutor:
    def __init__(
        self,
        executor: Any,
        *,
        redactor: TraceRedactor,
        backoff: Callable[[int], None] = default_backoff,
    ):
        self.executor = executor
        self.redactor = redactor
        self.backoff = backoff

    def execute(
        self,
        *,
        plan: ExecutionPlan,
        skill: SkillDefinition,
        prior_results: list[StepResult],
        checkpoint: Callable[[StepResult], None],
    ) -> TaskExecutionOutcome:
        results = list(prior_results)
        by_step = {item.step_id: item for item in results}
        context = rebuild_binding_context(results)
        writes_succeeded = any(
            item.status == "succeeded" and item.side_effect.get("occurred")
            for item in results
        )
        for declared_step, planned_step in zip(skill.steps, plan.steps, strict=True):
            prior = by_step.get(planned_step.step_id)
            if prior and prior.status == "succeeded":
                continue
            command = materialize_command(declared_step, planned_step, context)
            result = self.executor.execute(command)
            attempt = 1
            while True:
                checkpoint(redact_step_result(result, self.redactor))
                results.append(result)
                if result.status == "succeeded":
                    break
                decision = classify_retry(planned_step, result, attempt)
                if not decision.retry:
                    status = (
                        "unknown" if decision.terminal_status == "unknown"
                        else "partial_failure" if writes_succeeded
                        else "failed"
                    )
                    compensations = run_declared_compensations(
                        skill=skill,
                        plan=plan,
                        failed_step_id=planned_step.step_id,
                        context=context,
                        executor=self.executor,
                        checkpoint=lambda item: checkpoint(
                            redact_step_result(item, self.redactor)
                        ),
                    )
                    return TaskExecutionOutcome(
                        status=status,
                        step_results=results,
                        compensation_results=compensations,
                        outputs=outputs_from_context(context),
                    )
                self.backoff(attempt)
                attempt += 1
                result = self.executor.execute(command)
            by_step[result.step_id] = result
            add_result_to_context(context, result)
            writes_succeeded = writes_succeeded or bool(result.side_effect.get("occurred"))
        return TaskExecutionOutcome(
            status="succeeded",
            step_results=results,
            compensation_results=[],
            outputs=outputs_from_context(context),
        )
```

Define the named helpers in the same module. `materialize_command` resolves only expressions declared by the immutable Skill and raises if its arguments differ from `PlannedStep.arguments`; it copies `PlannedStep.idempotency_key` unchanged. `rebuild_binding_context`, `add_result_to_context`, and `outputs_from_context` use the existing mapping keys `task`, `literal`, and `steps`, with the selected object and inputs stored on `ExecutionPlan` as validated execution context fields. `redact_step_result` runs `TraceRedactor.redact_payload` over `normalized_output`, `error`, and side-effect evidence before persistence; raw values exist only in the current in-memory binding context. Add a test containing `authorization`, `cookie`, `password`, and `api_key` output fields and assert only `[REDACTED]` reaches the checkpoint. Persist each sanitized result through `checkpoint` before advancing. A prior successful step is skipped; an uncertain protected write reuses its original key; an uncertain unprotected write returns `unknown`. Use at most three attempts and inject `backoff` so tests do not sleep.

- [ ] **Step 4: Add explicit compensation behavior tests and implementation**

```python
def test_compensation_runs_only_when_plan_declares_validated_step():
    outcome = executor.execute(
        plan=plan_with_compensation("delete-created-a"),
        skill=skill_with_declared_compensation("delete-created-a"),
        prior_results=[],
        checkpoint=lambda result: None,
    )
    assert [call.step_id for call in tool_executor.calls] == [
        "create-a", "create-b", "delete-created-a"
    ]

def test_executor_never_infers_compensation():
    outcome = executor.execute(
        plan=plan_without_compensation(),
        skill=skill_without_compensation(),
        prior_results=[],
        checkpoint=lambda result: None,
    )
    assert "delete-created-a" not in [call.step_id for call in tool_executor.calls]
```

Run compensation in reverse declaration order only after the triggering failure. Record compensation results separately in `TaskExecutionOutcome`; never overwrite original step results.

- [ ] **Step 5: Run executor tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_executor.py tests/test_skill_runner.py -q`

Expected: PASS, including legacy SkillRunner regression.

- [ ] **Step 6: Commit resumable execution**

```powershell
git add app/command_center/task_session_executor.py tests/test_task_session_executor.py
git commit -m "feat: execute task sessions with recovery"
```

### Task 7: Orchestrate the complete TaskSession state machine

**Files:**
- Create: `app/command_center/task_session_service.py`
- Modify: `app/command_center/service.py`
- Create: `tests/test_task_session_service.py`

**Interfaces:**
- Consumes: repository compare-and-swap methods, trusted principal provider, TaskSession agents, `collect_skill_inputs`, `PlanValidator`, `ResumableTaskExecutor`, published Skill provider, read-only context resolver, and result verifier.
- Produces: `TaskSessionService.create`, `add_message`, `submit_inputs`, `confirm`, `get`, internal `resume_pending`, and narrow public delegation methods on `CommandCenterService`.

- [ ] **Step 1: Write failing read-only and input-collection flow tests**

```python
def test_read_only_session_executes_without_confirmation(session_service):
    created = session_service.create(CreateTaskSessionRequest(goal="查询我的假期余额"))
    assert created.state == "succeeded"
    assert created.next_interaction.type == "result"
    assert session_service.executor.calls[0].side_effect == "read"


def test_simple_missing_input_pauses_for_question(session_service):
    created = session_service.create(CreateTaskSessionRequest(goal="创建报销记录"))
    assert created.state == "collecting_input"
    assert created.next_interaction.type == "question"

    resumed = session_service.submit_inputs(
        created.session_id,
        TaskSessionInputRequest(version=created.version, values={"amount": 88}),
    )
    assert resumed.state == "awaiting_confirmation"


def test_object_ambiguity_pauses_for_selection(session_service):
    created = session_service.create(CreateTaskSessionRequest(goal="提交这张申请"))
    assert created.next_interaction.type == "selection"
    assert {item.value for item in created.next_interaction.options} == {"A", "B"}
```

- [ ] **Step 2: Run service tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_service.py -q`

Expected: FAIL because `TaskSessionService` does not exist.

- [ ] **Step 3: Implement legal state transitions and automatic advancement**

```python
ALLOWED_TRANSITIONS = {
    "understanding": {"resolving_context", "collecting_input", "failed"},
    "resolving_context": {"collecting_input", "failed"},
    "collecting_input": {"collecting_input", "awaiting_confirmation", "executing", "failed"},
    "awaiting_confirmation": {"awaiting_confirmation", "executing", "collecting_input", "failed"},
    "executing": {"executing", "verifying", "failed"},
    "verifying": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
}

class TaskSessionService:
    def create(self, request: CreateTaskSessionRequest) -> TaskSessionView:
        snapshot = new_task_session_snapshot(request, principal=self.principal_provider())
        self.repository.create_task_session(snapshot)
        return snapshot_to_view(self._advance(snapshot))

    def add_message(self, session_id: UUID, request: TaskSessionMessageRequest) -> TaskSessionView:
        snapshot = self._load_at_version(session_id, request.version)
        snapshot.messages.append({"role": "user", "content": request.message})
        return snapshot_to_view(self._advance(self._save_next(snapshot)))

    def submit_inputs(self, session_id: UUID, request: TaskSessionInputRequest) -> TaskSessionView:
        snapshot = self._load_at_version(session_id, request.version)
        snapshot = apply_submitted_inputs(snapshot, request.values)
        snapshot = invalidate_plan(snapshot)
        return snapshot_to_view(self._advance(self._save_next(snapshot)))

    def confirm(self, session_id: UUID, request: TaskSessionConfirmationRequest) -> TaskSessionView:
        snapshot = self._load_at_version(session_id, request.version)
        validate_confirmation_request(snapshot, request)
        snapshot = consume_confirmation(snapshot, approved=request.approved)
        return snapshot_to_view(self._advance(self._save_next(snapshot)))

    def get(self, session_id: UUID) -> TaskSessionView:
        return snapshot_to_view(self.repository.get_task_session(session_id))

    def resume_pending(self) -> list[UUID]:
        resumed: list[UUID] = []
        snapshots = self.repository.list_task_sessions_by_state({"executing", "verifying"})
        for snapshot in snapshots:
            try:
                self._advance(snapshot)
                resumed.append(snapshot.session_id)
            except TaskSessionConflictError:
                continue
        return resumed
```

The constructor requires `principal_provider: Callable[[], PrincipalContext]`; no HTTP body field can override its result. Implement the named pure helpers in the same module. `_load_at_version` raises `TaskSessionConflictError` on mismatch. `_save_next` copies the snapshot with `version + 1` and invokes repository compare-and-swap using the prior version. `invalidate_plan` clears plan/hash/token/consumed state and increments the plan revision only when a prior normalized plan existed. Create a private `_advance(snapshot)` loop with a maximum of 12 automatic transitions per request. At each boundary, persist with expected-version compare-and-swap. Stop when user interaction is required or a terminal state is reached. A loop-limit breach becomes a protocol failure, not another model call.

During `understanding`, validate `TaskIntentResolution.extracted_inputs` against the selected Skill and merge them as user-input values sourced from `goal`. During `resolving_context`, persist redacted read evidence, call `interpret_task_context`, validate every cited path, and copy trusted values/records from evidence rather than from model output. Zero candidates proceeds to input collection, one candidate becomes `selected_object`, and multiple candidates return a `selection` on reserved field `_object_id`. Submitting `_object_id` must choose one of the persisted candidate IDs; submitting `_skill_id` must choose one of the persisted Skill candidates. Remove reserved fields before validating Skill inputs.

- [ ] **Step 4: Compile plans from immutable Skill steps**

After `AgentSuite.propose_task_plan`, materialize each `SkillStep.input_bindings` from selected object, collected inputs, trusted evidence, and successful step outputs. Use the agent proposal only to select/cite allowed sources. Build `ExecutionPlan`, pass it to `PlanValidator`, increment `plan_revision`, and calculate `plan_hash`.

For each write step, calculate the stable key before validation as SHA-256 of canonical JSON containing `principal.tenant_id`, Skill ID/version, sorted target object IDs, step ID, and materialized Tool arguments. Do not include `session_id`, confirmation token, timestamps, or retry attempt. This makes the same confirmed business write converge across retries and duplicate sessions while changed arguments produce a different key.

If the normalized plan contains no writes, enter `executing`. If it contains a write, issue a confirmation token, store only its hash, and return a complete `ConfirmationInteraction`.

- [ ] **Step 5: Write and implement confirmation invalidation tests**

```python
def test_changed_input_invalidates_previous_confirmation(session_service):
    pending = session_service.create(write_request())
    old_token = pending.next_interaction.confirmation_token
    changed = session_service.submit_inputs(
        pending.session_id,
        TaskSessionInputRequest(version=pending.version, values={"amount": 99}),
    )
    assert changed.plan_revision == pending.plan_revision + 1
    assert changed.plan_hash != pending.plan_hash
    with pytest.raises(ConfirmationError):
        session_service.confirm(
            changed.session_id,
            TaskSessionConfirmationRequest(
                version=changed.version,
                plan_revision=pending.plan_revision,
                plan_hash=pending.plan_hash,
                confirmation_token=old_token,
                approved=True,
            ),
        )


def test_confirmation_token_is_single_use(session_service):
    pending = session_service.create(write_request())
    completed = approve(pending, session_service)
    with pytest.raises(ConfirmationError):
        approve(pending, session_service)
```

Only `approved=True` enters execution. `approved=False` creates a terminal failed result with code `user_declined`; it performs no Tool call.

- [ ] **Step 6: Checkpoint execution and verify results**

Before execution set `confirmation_consumed=True` in the same compare-and-swap update that enters `executing`. Pass a checkpoint callback that appends each `StepResult` and persists a new version. On successful execution enter `verifying` and call the existing verifier with the selected Skill, step results, and observed context. Map verification `passed` to `succeeded`; `failed` or `inconclusive` becomes a result with the correct `failed` or `verification_incomplete` status.

- [ ] **Step 7: Add restart and partial-failure tests**

```python
def test_get_resumes_executing_session_without_repeating_success(tmp_path):
    first_service = service_with_crash_after_checkpoint(tmp_path)
    pending = first_service.create(write_request())
    with pytest.raises(SimulatedCrash):
        approve(pending, first_service)

    second_service = service_from_same_database(tmp_path)
    second_service.resume_pending()
    resumed = second_service.get(pending.session_id)
    assert resumed.state == "succeeded"
    assert second_service.executor.called_steps == ["second-step"]


def test_partial_failure_preserves_success_and_stops(session_service):
    result = execute_three_step_failure(session_service)
    assert result.next_interaction.status == "partial_failure"
    assert [step.status for step in result.step_results] == ["succeeded", "failed"]
```

- [ ] **Step 8: Add narrow delegation to `CommandCenterService`**

Add optional constructor dependency `task_session_service: TaskSessionService | None = None`, five HTTP-facing methods that call `_require_task_session_service()` then delegate, and one internal `resume_pending_task_sessions()` method for application startup. Do not add TaskSession logic to the existing 40 KB service module. `get_task_session` remains read-only and never resumes execution.

- [ ] **Step 9: Run service and legacy service tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_service.py tests/test_command_center_service.py -q`

Expected: PASS.

- [ ] **Step 10: Commit orchestration**

```powershell
git add app/command_center/task_session_service.py app/command_center/service.py tests/test_task_session_service.py tests/test_command_center_service.py
git commit -m "feat: orchestrate persistent task sessions"
```

### Task 8: Expose the TaskSession API and compose runtime dependencies

**Files:**
- Modify: `app/command_center/router.py`
- Modify: `app/main.py`
- Modify: `tests/test_command_center_api.py`
- Modify: `tests/test_real_mes_readonly_loop.py`

**Interfaces:**
- Consumes: the five TaskSession delegation methods from Task 7.
- Produces: `POST /task-sessions`, `POST /task-sessions/{id}/messages`, `POST /task-sessions/{id}/inputs`, `POST /task-sessions/{id}/confirmations`, and `GET /task-sessions/{id}`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_create_task_session_returns_next_interaction():
    response = client_for(FakeCommandCenterService()).post(
        "/task-sessions",
        json={"goal": "查询我的假期余额"},
    )
    assert response.status_code == 201
    assert response.json()["next_interaction"]["type"] == "result"


def test_submit_inputs_passes_optimistic_version():
    service = FakeCommandCenterService()
    response = client_for(service).post(
        f"/task-sessions/{service.session_id}/inputs",
        json={"version": 4, "values": {"amount": 88}},
    )
    assert response.status_code == 200
    assert service.input_request.version == 4


def test_stale_session_version_returns_409_without_internal_detail():
    service = FakeCommandCenterService(conflict=True)
    response = client_for(service).post(
        f"/task-sessions/{service.session_id}/messages",
        json={"version": 1, "message": "继续"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "task session version conflict"


def test_client_cannot_supply_principal_or_permissions():
    response = client_for(FakeCommandCenterService()).post(
        "/task-sessions",
        json={
            "goal": "删除记录",
            "principal": {
                "subject_id": "attacker",
                "tenant_id": "other-tenant",
                "permissions": ["command-center:*"],
            },
        },
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run API tests and verify 404 failures**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_api.py -q`

Expected: FAIL because TaskSession routes are absent.

- [ ] **Step 3: Add typed routes and safe error mapping**

Use the Task 1 request models directly as FastAPI bodies. Map errors as follows:

```python
except KeyError:                 # 404, generic not-found text
except TaskSessionConflictError: # 409, task session version conflict
except ConfirmationError:        # 409, confirmation is no longer valid
except (PlanValidationError, InputSchemaError, ValidationError): # 422
except PermissionError:          # 403
```

Never include model prompts, credentials, HTTP response bodies, or Python exception representations in API errors.

- [ ] **Step 4: Compose the generic runtime in `build_command_center_components`**

Construct one routing catalog and one Tool executor, then wire:

```python
task_redactor = TraceRedactor(fingerprint_key=secrets.token_bytes(32))
task_sessions = TaskSessionService(
    repository=repository,
    principal_provider=lambda: PrincipalContext(
        subject_id="local-user",
        tenant_id="local",
        permissions=frozenset({"command-center:*"}),
    ),
    agents=agents,
    skills=lambda: repository.list_published_skills(),
    catalog=execution_catalog,
    context_resolver=ReadOnlyTaskContextResolver(
        agents=agents,
        tools=executable_tools,
        runner=DirectToolRunner(execution_catalog, execution_executor),
        redactor=task_redactor,
    ),
    validator=PlanValidator(execution_catalog, default_tool_permission_checker),
    executor=ResumableTaskExecutor(execution_executor, redactor=task_redactor),
    verifier=agents,
)
```

Pass it into `CommandCenterService(task_session_service=task_sessions)`. The generic Skill provider is published-only. Existing `executable_skill_set` remains unchanged for legacy task-run compatibility.

Move the existing `executable_tools` closure outside the `if execution_graph is None` block so both the legacy graph and TaskSession context resolver share the same lazy, read-only Tool discovery. Keep its existing per-system error handling and do not contact catalogs until a task actually resolves context.

- [ ] **Step 5: Test lazy startup and no external network at composition time**

Extend `tests/test_real_mes_readonly_loop.py` so construction with fake catalogs does not contact MES and asserts `components.service.task_session_service` is configured. The read-only resolver may contact a system only while advancing an actual session.

Add a FastAPI lifespan hook, not a mutating GET route:

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    get_command_center_service().resume_pending_task_sessions()
    yield

app = FastAPI(title="Configurable Form Agent MVP", lifespan=lifespan)
```

Add a test with one persisted `executing` session proving application startup calls recovery once, while repeated `GET /task-sessions/{id}` calls make no Tool calls and do not change the session version.

- [ ] **Step 6: Run API and composition tests**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_api.py tests/test_real_mes_readonly_loop.py -q`

Expected: PASS.

- [ ] **Step 7: Commit API wiring**

```powershell
git add app/command_center/router.py app/main.py tests/test_command_center_api.py tests/test_real_mes_readonly_loop.py
git commit -m "feat: expose task session API"
```

### Task 9: Render all TaskSession interactions in Vue

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/commandCenter.ts`
- Create: `frontend/src/components/DynamicSchemaForm.vue`
- Create: `frontend/src/components/TaskInteractionRenderer.vue`
- Create: `frontend/src/components/__tests__/DynamicSchemaForm.spec.ts`
- Create: `frontend/src/components/__tests__/TaskInteractionRenderer.spec.ts`

**Interfaces:**
- Consumes: TaskSession API JSON from Task 8.
- Produces: TypeScript discriminated union `NextInteraction`, `TaskSessionView`, API functions, and renderer events `submit-message`, `submit-inputs`, `submit-selection`, and `confirm`.

- [ ] **Step 1: Add failing API and renderer tests**

```ts
it('narrows and renders a confirmation plan', () => {
  const wrapper = mount(TaskInteractionRenderer, {
    props: { session: confirmationSession },
    global: { plugins: [ElementPlus] },
  })
  expect(wrapper.get('[data-testid="confirmation-summary"]').text())
    .toContain('创建报销记录')
  expect(wrapper.findAll('[data-testid="write-step"]')).toHaveLength(1)
})

it('submits array form values as one input payload', async () => {
  const wrapper = mount(DynamicSchemaForm, {
    props: { schema: expenseItemsSchema, modelValue: {} },
    global: { plugins: [ElementPlus] },
  })
  await wrapper.get('[data-testid="add-items-row"]').trigger('click')
  await wrapper.get('[data-path="items.0.category"]').setValue('差旅')
  await wrapper.get('[data-path="items.0.amount"]').setValue('88')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('submit')?.[0][0]).toEqual({
    items: [{ category: '差旅', amount: 88 }],
  })
})
```

- [ ] **Step 2: Run frontend tests and verify missing components**

Run: `cd frontend; npm test -- --run src/components/__tests__/DynamicSchemaForm.spec.ts src/components/__tests__/TaskInteractionRenderer.spec.ts`

Expected: FAIL because components and types are absent.

- [ ] **Step 3: Define exact discriminated TypeScript contracts**

```ts
export type TaskSessionState =
  | 'understanding' | 'resolving_context' | 'collecting_input'
  | 'awaiting_confirmation' | 'executing' | 'verifying'
  | 'succeeded' | 'failed'

export type NextInteraction =
  | { type: 'message'; message: string }
  | { type: 'question'; prompt: string; field_names: string[] }
  | { type: 'selection'; prompt: string; options: SelectionOption[] }
  | { type: 'form'; title: string; schema: JsonSchema; values: Record<string, unknown> }
  | { type: 'confirmation'; title: string; summary: string; plan_revision: number; plan_hash: string; confirmation_token: string; systems: string[]; target_objects: string[]; write_steps: PlannedStepView[] }
  | { type: 'result'; status: 'succeeded' | 'failed' | 'partial_failure' | 'verification_incomplete' | 'unknown'; code?: string; summary: string; steps: StepResultView[] }

export interface TaskSessionView {
  session_id: string
  state: TaskSessionState
  version: number
  goal: string
  plan_revision: number
  plan_hash?: string
  next_interaction: NextInteraction
}
```

Add `createTaskSession`, `sendTaskSessionMessage`, `submitTaskSessionInputs`, `confirmTaskSession`, and `getTaskSession`. Each mutation sends the current `version`.

- [ ] **Step 4: Implement the supported JSON Schema form subset**

`DynamicSchemaForm.vue` supports:

- object `properties` and `required`;
- string, number, integer, boolean, and enum;
- string `format: date | date-time` using Element Plus date controls;
- arrays whose `items` are scalar or object schemas;
- add/remove array rows;
- client-side required validation before emit.

Reject unsupported constructs (`oneOf`, `anyOf`, recursive `$ref`) with a visible “当前表单结构暂不支持，请联系管理员完善 Skill Schema” result. Do not silently coerce unsupported shapes.

- [ ] **Step 5: Implement the interaction renderer**

Use `interaction.type` switching only; do not inspect Skill names or field names. Confirmation renders every write step, system, target object, and key argument summary before the approve button. The decline button emits the same confirmation payload with `approved: false`.

- [ ] **Step 6: Run component tests and TypeScript build**

Run: `cd frontend; npm test -- --run src/components/__tests__/DynamicSchemaForm.spec.ts src/components/__tests__/TaskInteractionRenderer.spec.ts; npm run build`

Expected: tests PASS and build succeeds.

- [ ] **Step 7: Commit the generic renderer**

```powershell
git add frontend/src/api/types.ts frontend/src/api/commandCenter.ts frontend/src/components/DynamicSchemaForm.vue frontend/src/components/TaskInteractionRenderer.vue frontend/src/components/__tests__/DynamicSchemaForm.spec.ts frontend/src/components/__tests__/TaskInteractionRenderer.spec.ts
git commit -m "feat: render generic task interactions"
```

### Task 10: Make TaskSession the primary panel flow and migrate dynamic Actions

**Files:**
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`
- Modify: `frontend/src/components/TaskResultTable.vue`
- Modify: `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`
- Modify: `frontend/src/components/__tests__/TaskResultTable.spec.ts`
- Modify: `app/command_center/service.py`
- Modify: `tests/test_command_center_service.py`

**Interfaces:**
- Consumes: TaskSession API/client and renderer from Task 9.
- Produces: natural-language TaskSession creation and structured Action shortcuts using the same `/task-sessions` endpoint.

- [ ] **Step 1: Rewrite panel tests around TaskSession creation**

```ts
it('starts natural language work through TaskSession', async () => {
  api.createTaskSession.mockResolvedValue(readOnlyResultSession)
  const wrapper = mountPanel()
  await wrapper.get('textarea').setValue('查询我的假期余额')
  await wrapper.get('[data-testid="start-task-session"]').trigger('click')
  await flushPromises()
  expect(api.createTaskSession).toHaveBeenCalledWith({
    goal: '查询我的假期余额',
  })
  expect(wrapper.text()).toContain('剩余 5 天')
})

it('starts an Action as a structured shortcut instead of executing directly', async () => {
  const wrapper = mountPanelWithLegacyQueryResult()
  await wrapper.get('[data-action-id="create-follow-up"]').trigger('click')
  expect(api.createTaskSession).toHaveBeenCalledWith({
    goal: '为所选业务对象创建跟进任务',
    hint: {
      action_id: 'create-follow-up',
      skill_id: 'skill-1',
      skill_version: 1,
      selected_object: expect.objectContaining({ id: 'record-9' }),
    },
  })
  expect(api.executeTaskAction).not.toHaveBeenCalled()
})

it('offers the legacy query only when no published Skill matches', async () => {
  api.createTaskSession.mockResolvedValue(noMatchingSkillSession)
  const wrapper = mountPanel()
  await submitGoal(wrapper, '查询采购申请列表')
  expect(wrapper.get('[data-testid="legacy-query-fallback"]').isVisible()).toBe(true)
  await wrapper.get('[data-testid="legacy-query-fallback"]').trigger('click')
  expect(api.createTaskRun).toHaveBeenCalledWith('查询采购申请列表')
})
```

- [ ] **Step 2: Run the panel tests and verify old direct-action assertions fail**

Run: `cd frontend; npm test -- --run src/components/__tests__/NaturalLanguageTaskPanel.spec.ts src/components/__tests__/TaskResultTable.spec.ts`

Expected: FAIL until the panel switches to TaskSession.

- [ ] **Step 3: Integrate `TaskInteractionRenderer`**

Replace the primary `TaskRunView` state with `TaskSessionView`. Route renderer events to the appropriate API call, always replacing local state with the server response. On HTTP 409, call `getTaskSession(session_id)` and render the latest interaction with a warning that another submission already advanced the task.

When the terminal result has `code="no_matching_published_skill"`, show a neutral “使用兼容查询” button that calls the existing `createTaskRun` with the unchanged goal. Do not trigger that fallback automatically and do not key it to purchase words. Keep the returned legacy query result, detail, and purchase-progress rendering behind their current buttons. Do not rename or change their endpoints.

- [ ] **Step 4: Pass a complete trusted object in Action shortcut hints**

Change `TaskResultTable` action emit from `(actionId, recordId)` to one object:

```ts
export interface TaskActionInvocation {
  action: AvailableTaskAction
  record: Record<string, unknown>
}
```

The backend treats the record as a hint until it verifies that the object came from the parent trusted task-run evidence. Add `parent_run_id` and `selected_record_id` to the create request hint; do not accept an arbitrary browser object as trusted context.

Only Actions whose exact Skill version is published use the TaskSession shortcut. If a legacy task run exposes an Action backed only by a `verified_candidate`, retain the direct legacy action call and label it “兼容执行”; do not silently broaden the generic TaskSession Skill provider. Add tests for both published and verified-candidate action metadata. Once the current cross-system Skill is explicitly published, the panel automatically uses TaskSession without another UI change.

Add `task_session_eligible: boolean` to `AvailableTaskAction`. In `_attach_available_actions`, set it from the exact Skill version's status (`published` is true; every other status is false). The frontend chooses the protocol only from this server metadata and never infers eligibility from labels or IDs.

- [ ] **Step 5: Add backend shortcut verification and tests**

In `TaskSessionService.create`, when a hint includes `parent_run_id`, load that task run and find `selected_record_id` inside its stored outputs using the existing bounded record traversal helper. Ignore client-supplied record fields and copy the trusted stored record. Require hinted Skill ID/version/action ID to match an available action attached to that exact record.

```python
def test_action_hint_uses_record_from_parent_run_not_browser_payload(service):
    created = service.create_task_session(CreateTaskSessionRequest(
        goal="创建跟进任务",
        hint={
            "parent_run_id": str(parent_run_id),
            "selected_record_id": "record-9",
            "selected_object": {"id": "record-9", "owner": "tampered"},
            "skill_id": str(skill.skill_id),
            "skill_version": skill.version,
            "action_id": skill.action.action_id,
        },
    ))
    stored = repository.get_task_session(created.session_id)
    assert stored.selected_object["owner"] == "trusted server value"
```

- [ ] **Step 6: Run panel, service, and compatibility tests**

Run: `cd frontend; npm test -- --run src/components/__tests__/NaturalLanguageTaskPanel.spec.ts src/components/__tests__/TaskResultTable.spec.ts`

Run: `conda run -n langgraph python -m pytest tests/test_task_session_service.py tests/test_command_center_service.py tests/test_command_center_api.py -q`

Expected: PASS. Published Actions use TaskSession; verified-candidate Actions and legacy detail/progress endpoints retain their existing response shapes and compatibility path.

- [ ] **Step 7: Commit panel migration**

```powershell
git add frontend/src/components/NaturalLanguageTaskPanel.vue frontend/src/components/TaskResultTable.vue frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts frontend/src/components/__tests__/TaskResultTable.spec.ts app/command_center/service.py tests/test_command_center_service.py
git commit -m "feat: route task actions through sessions"
```

### Task 11: Prove generalization with non-purchase contract systems

**Files:**
- Create: `tests/test_task_session_contracts.py`
- Modify: `tests/test_execution_graph.py`
- Modify: `tests/test_skill_runner.py`

**Interfaces:**
- Consumes: the full TaskSession service with fake Tool catalogs and executors.
- Produces: cross-domain acceptance coverage proving the generic path contains no purchase assumptions.

- [ ] **Step 1: Add a read-only HR Skill contract**

```python
def test_hr_leave_balance_is_read_only_and_needs_no_confirmation(contract_service):
    result = contract_service.create(CreateTaskSessionRequest(
        goal="查看员工 E-9 的剩余年假",
        hint={"skill_id": str(HR_SKILL_ID), "skill_version": 1},
    ))
    assert result.state == "succeeded"
    assert result.next_interaction.type == "result"
    assert result.next_interaction.summary == "员工 E-9 剩余年假 5 天"
    assert contract_service.confirmations_issued == 0
```

- [ ] **Step 2: Add a multi-step finance Skill contract**

```python
def test_finance_expense_uses_form_confirmation_and_idempotent_write(contract_service):
    collecting = contract_service.create(CreateTaskSessionRequest(
        goal="提交一张包含两条费用的报销单",
        hint={"skill_id": str(FINANCE_SKILL_ID), "skill_version": 1},
    ))
    assert collecting.next_interaction.type == "form"

    pending = contract_service.submit_inputs(
        collecting.session_id,
        TaskSessionInputRequest(
            version=collecting.version,
            values={"items": [
                {"category": "差旅", "amount": 88},
                {"category": "餐费", "amount": 32},
            ]},
        ),
    )
    assert pending.next_interaction.type == "confirmation"
    completed = approve(pending, contract_service)
    assert completed.state == "succeeded"
    assert contract_service.finance_api.created_count == 1
```

- [ ] **Step 3: Add failure and recovery contracts**

Cover these exact cases in the same file:

```python
@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_calls", "expected_records"),
    [
        ("changed_target", "confirmation_rejected", 0, 0),
        ("duplicate_confirmation", "succeeded", 1, 1),
        ("idempotent_timeout", "succeeded", 2, 1),
        ("business_failure", "failed", 1, 0),
        ("partial_failure", "partial_failure", 2, 1),
        ("restart_after_success", "succeeded", 1, 1),
        ("unprotected_timeout", "unknown", 1, 1),
    ],
)
def test_failure_and_recovery_contracts(
    contract_harness,
    scenario,
    expected_status,
    expected_calls,
    expected_records,
):
    outcome = contract_harness.run(scenario)
    assert outcome.status == expected_status
    assert outcome.tool_calls == expected_calls
    assert outcome.target_records == expected_records
```

Implement `contract_harness.run` as a fixture backed by the real repository, TaskSessionService, fake agents, fake `hr_system`/`finance_system` catalogs, and a stateful fake Tool executor. For `changed_target`, catch `ConfirmationError` and return the synthetic status `confirmation_rejected`. For `unprotected_timeout`, model one target record because the point of `unknown` is that the request may have reached the remote system. Assert no fixture, prompt, route, or source file used by the generic service contains `purchase_follow_up`, `applyNo`, or a purchase sample ID.

- [ ] **Step 4: Run contract and legacy runtime tests**

Run: `conda run -n langgraph python -m pytest tests/test_task_session_contracts.py tests/test_execution_graph.py tests/test_skill_runner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit generic contracts**

```powershell
git add tests/test_task_session_contracts.py tests/test_execution_graph.py tests/test_skill_runner.py
git commit -m "test: prove task session generalization"
```

### Task 12: Run full verification and document the operational test path

**Files:**
- Create: `docs/task-session-testing.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all implemented TaskSession APIs and the existing local frontend/backend startup commands.
- Produces: a repeatable operator test for read-only, hybrid input, write confirmation, duplicate submission, and legacy compatibility.

- [ ] **Step 1: Write the operational test document**

Document these exact flows without using production credentials:

```text
1. Start backend and frontend.
2. Publish or load the HR read-only fixture Skill.
3. Submit “查看员工 E-9 的剩余年假”; verify no confirmation appears.
4. Publish or load the finance fixture Skill.
5. Submit “提交一张包含两条费用的报销单”.
6. Verify a dynamic array form appears; enter two rows.
7. Verify the confirmation lists the exact target, system, arguments, and write step.
8. Confirm once; record the returned external ID.
9. Resubmit the same confirmation/request; verify the same external ID and one target record.
10. Change an amount after a plan is shown; verify the old confirmation is rejected.
11. Run the existing purchase query, detail, and progress buttons; verify compatibility.
```

Include API examples using `Invoke-RestMethod` with session `version`, `plan_revision`, `plan_hash`, and confirmation token copied from the preceding response. State that fixture Skills are for test only.

- [ ] **Step 2: Run backend formatting and full tests**

Run: `conda run -n langgraph python -m pytest -q`

Expected: all backend tests PASS. Classify any failure according to AGENTS.md before changing implementation or tests.

- [ ] **Step 3: Run frontend tests and production build**

Run: `cd frontend; npm test -- --run; npm run build`

Expected: all frontend tests PASS and Vite build succeeds; chunk-size warnings are informational unless a new regression appears.

- [ ] **Step 4: Check source and diff hygiene**

Run:

```powershell
git diff --check
Select-String -Path app\command_center\task_session_*.py -Pattern 'applyNo|purchase_follow_up|1938559676014665730'
git status --short
```

Expected: `git diff --check` is clean; the generic TaskSession modules contain none of the forbidden purchase-specific strings; status includes only intentional files.

- [ ] **Step 5: Commit documentation**

```powershell
git add docs/task-session-testing.md README.md
git commit -m "docs: add task session verification guide"
```

- [ ] **Step 6: Request code review before integration**

Use `superpowers:requesting-code-review` to review spec compliance, security boundaries, failure classification, and the absence of purchase-specific generic logic. Address findings using `superpowers:receiving-code-review`, then rerun Steps 2–4 before merging.
