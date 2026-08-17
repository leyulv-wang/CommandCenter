from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable
from uuid import UUID, uuid4

from app.command_center.repository import (
    CommandCenterRepository,
    TaskSessionConflictError,
)
from app.command_center.schemas import SkillDefinition
from app.command_center.task_session_inputs import (
    collect_skill_inputs,
    validate_input_value,
)
from app.command_center.task_session_policy import (
    PlanValidator,
    canonical_plan_hash,
    confirmation_token_hash,
    issue_confirmation_token,
    validate_confirmation,
)
from app.command_center.task_session_schemas import (
    ConfirmationInteraction,
    CreateTaskSessionRequest,
    ExecutionPlan,
    MessageInteraction,
    ParameterSource,
    PlannedStep,
    PlannedStepView,
    PrincipalContext,
    QuestionInteraction,
    ResultInteraction,
    SelectionInteraction,
    SelectionOption,
    StepResultView,
    TaskSessionConfirmationRequest,
    TaskSessionInputRequest,
    TaskSessionMessageRequest,
    TaskSessionSnapshot,
    TaskSessionState,
    TaskSessionView,
)


ALLOWED_TRANSITIONS: dict[TaskSessionState, set[TaskSessionState]] = {
    "understanding": {"resolving_context", "collecting_input", "failed"},
    "resolving_context": {"collecting_input", "failed"},
    "collecting_input": {
        "collecting_input",
        "awaiting_confirmation",
        "executing",
        "failed",
    },
    "awaiting_confirmation": {
        "awaiting_confirmation",
        "executing",
        "collecting_input",
        "failed",
    },
    "executing": {"executing", "verifying", "failed"},
    "verifying": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
}


class TaskSessionService:
    def __init__(
        self,
        *,
        repository: CommandCenterRepository,
        principal_provider: Callable[[], PrincipalContext],
        agents: Any,
        skills: Callable[[], list[SkillDefinition]],
        catalog: Any,
        context_resolver: Any,
        validator: PlanValidator,
        executor: Any,
        verifier: Any,
    ) -> None:
        self.repository = repository
        self.principal_provider = principal_provider
        self.agents = agents
        self.skills = skills
        self.catalog = catalog
        self.context_resolver = context_resolver
        self.validator = validator
        self.executor = executor
        self.verifier = verifier

    def create(self, request: CreateTaskSessionRequest) -> TaskSessionView:
        selected_object = self._trusted_hint_object(request)
        snapshot = TaskSessionSnapshot(
            session_id=uuid4(),
            state="understanding",
            version=1,
            goal=request.goal,
            principal=self.principal_provider(),
            messages=[{"role": "user", "content": request.goal}],
            selected_skill_id=request.hint.skill_id if request.hint else None,
            selected_skill_version=request.hint.skill_version if request.hint else None,
            selected_object=selected_object,
            next_interaction=MessageInteraction(message="正在理解任务"),
        )
        self.repository.create_task_session(snapshot)
        return _snapshot_to_view(self._advance(snapshot))

    def _trusted_hint_object(
        self, request: CreateTaskSessionRequest
    ) -> dict[str, Any] | None:
        hint = request.hint
        if hint is None or hint.parent_run_id is None:
            return None
        if not (
            hint.selected_record_id
            and hint.action_id
            and hint.skill_id
            and hint.skill_version
        ):
            raise ValueError("action shortcut hint is incomplete")
        parent = self.repository.get_task_run(hint.parent_run_id)
        action = next(
            (
                item
                for item in parent.get("available_actions", [])
                if item.get("action_id") == hint.action_id
                and str(item.get("record_id")) == hint.selected_record_id
                and str(item.get("skill_id")) == str(hint.skill_id)
                and int(item.get("skill_version", 0)) == hint.skill_version
                and item.get("task_session_eligible") is True
            ),
            None,
        )
        if action is None:
            raise ValueError("action shortcut is not available for the saved record")
        outputs = parent.get("final_response", {}).get("outputs")
        record = _find_record_by_identity(outputs, hint.selected_record_id)
        if record is None:
            raise ValueError("selected record is not present in trusted task evidence")
        return deepcopy(record)

    def add_message(
        self, session_id: UUID, request: TaskSessionMessageRequest
    ) -> TaskSessionView:
        snapshot = self._load_at_version(session_id, request.version)
        if snapshot.state in {"succeeded", "failed"}:
            raise ValueError("terminal task sessions cannot accept messages")
        messages = [
            *snapshot.messages,
            {"role": "user", "content": request.message},
        ]
        snapshot = self._transition(
            snapshot,
            "understanding",
            messages=messages,
            goal=f"{snapshot.goal}\n{request.message}"[:2_000],
            plan=None,
            plan_hash=None,
            confirmation_token_hash=None,
            confirmation_consumed=False,
            next_interaction=MessageInteraction(message="正在重新理解任务"),
            allow_reset=True,
        )
        return _snapshot_to_view(self._advance(snapshot))

    def submit_inputs(
        self, session_id: UUID, request: TaskSessionInputRequest
    ) -> TaskSessionView:
        snapshot = self._load_at_version(session_id, request.version)
        if snapshot.state not in {
            "understanding",
            "resolving_context",
            "collecting_input",
            "awaiting_confirmation",
        }:
            raise ValueError("task session is not collecting input")
        values = dict(request.values)
        selected_skill_id = snapshot.selected_skill_id
        selected_skill_version = snapshot.selected_skill_version
        selected_object = snapshot.selected_object

        if "_skill_id" in values:
            chosen = str(values.pop("_skill_id"))
            candidate = next(
                (
                    item
                    for item in snapshot.skill_candidates
                    if str(item.get("skill_id")) == chosen
                ),
                None,
            )
            if candidate is None:
                raise ValueError("selected Skill is not an available candidate")
            selected_skill_id = UUID(chosen)
            selected_skill_version = int(candidate["version"])
        if "_object_id" in values:
            chosen = str(values.pop("_object_id"))
            candidate = next(
                (
                    item
                    for item in snapshot.object_candidates
                    if str(item.get("id")) == chosen
                ),
                None,
            )
            if candidate is None:
                raise ValueError("selected object is not an available candidate")
            selected_object = deepcopy(candidate)

        supplied = {**snapshot.inputs, **values}
        sources = {
            **snapshot.input_sources,
            **{
                name: ParameterSource(kind="user_input", reference=name)
                for name in values
            },
        }
        snapshot = self._transition(
            snapshot,
            "collecting_input",
            selected_skill_id=selected_skill_id,
            selected_skill_version=selected_skill_version,
            selected_object=selected_object,
            inputs=supplied,
            input_sources=sources,
            plan=None,
            plan_hash=None,
            confirmation_token_hash=None,
            confirmation_consumed=False,
            next_interaction=QuestionInteraction(
                prompt="正在校验输入", field_names=["_pending"]
            ),
        )
        return _snapshot_to_view(self._advance(snapshot))

    def confirm(
        self, session_id: UUID, request: TaskSessionConfirmationRequest
    ) -> TaskSessionView:
        snapshot = self._load_at_version(session_id, request.version)
        if snapshot.state != "awaiting_confirmation":
            raise ValueError("task session is not awaiting confirmation")
        validate_confirmation(
            supplied_token=request.confirmation_token,
            stored_token_hash=snapshot.confirmation_token_hash,
            supplied_revision=request.plan_revision,
            stored_revision=snapshot.plan_revision,
            supplied_plan_hash=request.plan_hash,
            stored_plan_hash=snapshot.plan_hash,
            consumed=snapshot.confirmation_consumed,
        )
        if not request.approved:
            return _snapshot_to_view(
                self._transition(
                    snapshot,
                    "failed",
                    confirmation_consumed=True,
                    next_interaction=ResultInteraction(
                        status="failed",
                        code="user_declined",
                        summary="用户取消了写操作",
                    ),
                )
            )
        snapshot = self._transition(
            snapshot,
            "executing",
            confirmation_consumed=True,
            next_interaction=MessageInteraction(message="正在执行已确认计划"),
        )
        return _snapshot_to_view(self._advance(snapshot))

    def get(self, session_id: UUID) -> TaskSessionView:
        return _snapshot_to_view(self.repository.get_task_session(session_id))

    def resume_pending(self) -> list[UUID]:
        resumed: list[UUID] = []
        for snapshot in self.repository.list_task_sessions_by_state(
            {"executing", "verifying"}
        ):
            try:
                self._advance(snapshot)
                resumed.append(snapshot.session_id)
            except TaskSessionConflictError:
                continue
        return resumed

    def _advance(self, snapshot: TaskSessionSnapshot) -> TaskSessionSnapshot:
        for _ in range(12):
            if snapshot.state in {
                "succeeded",
                "failed",
                "awaiting_confirmation",
            }:
                return snapshot
            if snapshot.state == "understanding":
                snapshot = self._understand(snapshot)
                continue
            if snapshot.state == "resolving_context":
                snapshot = self._resolve_context(snapshot)
                continue
            if snapshot.state == "collecting_input":
                advanced = self._collect_or_plan(snapshot)
                if advanced.state == "collecting_input":
                    return advanced
                snapshot = advanced
                continue
            if snapshot.state == "executing":
                snapshot = self._execute(snapshot)
                continue
            if snapshot.state == "verifying":
                snapshot = self._verify(snapshot)
                continue
        return self._transition(
            snapshot,
            "failed",
            next_interaction=ResultInteraction(
                status="failed",
                code="transition_limit_exceeded",
                summary="任务状态推进超过安全限制",
            ),
        )

    def _understand(self, snapshot: TaskSessionSnapshot) -> TaskSessionSnapshot:
        skills = self.skills()
        selected = _find_skill(
            skills, snapshot.selected_skill_id, snapshot.selected_skill_version
        )
        if selected is None and snapshot.selected_skill_id is not None:
            return self._fail_no_skill(snapshot)
        if selected is None:
            resolution = self.agents.resolve_task_intent(
                goal=snapshot.goal,
                skills=skills,
                object_candidates=snapshot.object_candidates,
            )
            if resolution.status == "not_applicable":
                return self._fail_no_skill(snapshot)
            if resolution.status == "needs_skill_selection":
                candidates = [
                    {
                        "skill_id": str(skill.skill_id),
                        "version": skill.version,
                        "name": skill.name,
                    }
                    for skill in skills
                    if skill.skill_id in set(resolution.candidate_skill_ids)
                ]
                return self._persist_same_state(
                    snapshot,
                    skill_candidates=candidates,
                    next_interaction=SelectionInteraction(
                        prompt="请选择要使用的能力",
                        field_name="_skill_id",
                        options=[
                            SelectionOption(
                                value=item["skill_id"], label=item["name"]
                            )
                            for item in candidates
                        ],
                    ),
                )
            selected = _find_skill(
                skills, resolution.skill_id, resolution.skill_version
            )
            if selected is None:
                return self._fail_no_skill(snapshot)
            extracted: dict[str, Any] = {}
            sources = dict(snapshot.input_sources)
            definitions = {item.name: item for item in selected.inputs}
            for name, value in resolution.extracted_inputs.items():
                extracted[name] = validate_input_value(definitions[name], value)
                sources[name] = ParameterSource(
                    kind="user_input", reference="goal"
                )
            snapshot = snapshot.model_copy(
                update={
                    "selected_skill_id": selected.skill_id,
                    "selected_skill_version": selected.version,
                    "inputs": {**snapshot.inputs, **extracted},
                    "input_sources": sources,
                }
            )
        return self._transition(
            snapshot,
            "resolving_context",
            selected_skill_id=selected.skill_id,
            selected_skill_version=selected.version,
            next_interaction=MessageInteraction(message="正在读取允许的业务上下文"),
        )

    def _resolve_context(
        self, snapshot: TaskSessionSnapshot
    ) -> TaskSessionSnapshot:
        skill = self._selected_skill(snapshot)
        evidence = self.context_resolver.resolve(
            goal=snapshot.goal, selected_object=snapshot.selected_object
        )
        candidates: list[dict[str, Any]] = []
        if evidence:
            interpretation = self.agents.interpret_task_context(
                goal=snapshot.goal, skill=skill, evidence=evidence
            )
            evidence_by_id = {item.evidence_id: item for item in evidence}
            for candidate in interpretation.candidates:
                record = _resolve_path(
                    evidence_by_id[candidate.evidence_id].output,
                    candidate.record_path,
                )
                candidates.append(deepcopy(record))
        if snapshot.selected_object is None and len(candidates) > 1:
            return self._transition(
                snapshot,
                "collecting_input",
                context_evidence=evidence,
                object_candidates=candidates,
                next_interaction=SelectionInteraction(
                    prompt="请选择本次任务的业务对象",
                    field_name="_object_id",
                    options=[
                        SelectionOption(
                            value=str(item["id"]),
                            label=str(item.get("title") or item.get("name") or item["id"]),
                        )
                        for item in candidates
                    ],
                ),
            )
        selected_object = snapshot.selected_object
        if selected_object is None and len(candidates) == 1:
            selected_object = candidates[0]
        return self._transition(
            snapshot,
            "collecting_input",
            context_evidence=evidence,
            object_candidates=candidates,
            selected_object=selected_object,
            next_interaction=QuestionInteraction(
                prompt="正在检查任务输入", field_names=["_pending"]
            ),
        )

    def _collect_or_plan(
        self, snapshot: TaskSessionSnapshot
    ) -> TaskSessionSnapshot:
        skill = self._selected_skill(snapshot)
        trusted_context = _trusted_context(snapshot)
        collection = collect_skill_inputs(
            skill,
            supplied=snapshot.inputs,
            trusted_context=trusted_context,
        )
        if not collection.complete:
            return self._persist_same_state(
                snapshot,
                inputs=collection.values,
                input_sources=collection.sources,
                next_interaction=collection.interaction,
            )
        proposal = self.agents.propose_task_plan(
            goal=snapshot.goal,
            skill=skill,
            selected_object=snapshot.selected_object,
            inputs=collection.values,
            input_sources=collection.sources,
            evidence=snapshot.context_evidence,
        )
        target_objects = proposal.target_object_ids or ["user-goal"]
        steps: list[PlannedStep] = []
        for declared in skill.steps:
            arguments: dict[str, dict[str, Any]] = {}
            sources: dict[str, ParameterSource] = {}
            for target, expression in declared.input_bindings.items():
                location, _, name = target.partition(".")
                arguments.setdefault(location, {})[name] = _resolve_binding(
                    expression,
                    inputs=collection.values,
                    selected_object=snapshot.selected_object,
                )
                source_key = f"{declared.step_id}.{target}"
                if source_key not in proposal.argument_sources:
                    raise ValueError("agent plan omitted a Skill binding source")
                sources[target] = proposal.argument_sources[source_key]
            key = None
            if declared.side_effect == "write":
                key = _stable_write_key(
                    tenant_id=snapshot.principal.tenant_id,
                    skill=skill,
                    targets=target_objects,
                    step_id=declared.step_id,
                    arguments=arguments,
                )
            steps.append(
                PlannedStep(
                    step_id=declared.step_id,
                    name=declared.name,
                    tool_id=declared.tool_id,
                    side_effect=declared.side_effect,
                    arguments=arguments,
                    argument_sources=sources,
                    idempotency_key=key,
                )
            )
        raw_plan = ExecutionPlan(
            skill_id=skill.skill_id,
            skill_version=skill.version,
            summary=proposal.summary,
            target_objects=target_objects,
            selected_object=snapshot.selected_object,
            inputs=collection.values,
            steps=steps,
            verification_condition_ids=[
                item.condition_id for item in skill.success_conditions
            ],
            compensation_step_ids=[
                item.step.step_id for item in skill.compensations
            ],
        )
        validated = self.validator.validate(
            raw_plan, skill, principal=snapshot.principal
        )
        revision = snapshot.plan_revision + 1
        if any(step.side_effect == "write" for step in validated.plan.steps):
            token = issue_confirmation_token()
            return self._transition(
                snapshot,
                "awaiting_confirmation",
                inputs=collection.values,
                input_sources=collection.sources,
                plan_revision=revision,
                plan=validated.plan,
                plan_hash=validated.plan_hash,
                confirmation_token_hash=confirmation_token_hash(token),
                confirmation_consumed=False,
                next_interaction=_confirmation_interaction(
                    validated.plan, revision, validated.plan_hash, token
                ),
            )
        return self._transition(
            snapshot,
            "executing",
            inputs=collection.values,
            input_sources=collection.sources,
            plan_revision=revision,
            plan=validated.plan,
            plan_hash=validated.plan_hash,
            next_interaction=MessageInteraction(message="正在执行只读计划"),
        )

    def _execute(self, snapshot: TaskSessionSnapshot) -> TaskSessionSnapshot:
        if snapshot.plan is None:
            raise ValueError("executing task session has no plan")
        skill = self._selected_skill(snapshot)
        current = snapshot

        def checkpoint(result: Any) -> None:
            nonlocal current
            current = self._persist_same_state(
                current,
                step_results=[*current.step_results, result],
                next_interaction=MessageInteraction(message="正在执行计划步骤"),
            )

        outcome = self.executor.execute(
            plan=snapshot.plan,
            skill=skill,
            prior_results=snapshot.step_results,
            checkpoint=checkpoint,
        )
        if outcome.status != "succeeded":
            return self._transition(
                current,
                "failed",
                next_interaction=ResultInteraction(
                    status=outcome.status,
                    summary="任务执行未完整完成",
                    steps=_step_views(current.step_results),
                ),
            )
        return self._transition(
            current,
            "verifying",
            next_interaction=MessageInteraction(message="正在验证业务结果"),
        )

    def _verify(self, snapshot: TaskSessionSnapshot) -> TaskSessionSnapshot:
        skill = self._selected_skill(snapshot)
        verification = self.verifier.verify_result(
            skill,
            snapshot.step_results,
            {"selected_object": snapshot.selected_object},
        )
        if verification.status == "passed":
            return self._transition(
                snapshot,
                "succeeded",
                verification=verification,
                next_interaction=ResultInteraction(
                    status="succeeded",
                    summary=verification.summary,
                    steps=_step_views(snapshot.step_results),
                ),
            )
        status = (
            "verification_incomplete"
            if verification.status == "inconclusive"
            else "failed"
        )
        return self._transition(
            snapshot,
            "failed",
            verification=verification,
            next_interaction=ResultInteraction(
                status=status,
                summary=verification.summary,
                steps=_step_views(snapshot.step_results),
            ),
        )

    def _selected_skill(self, snapshot: TaskSessionSnapshot) -> SkillDefinition:
        skill = _find_skill(
            self.skills(),
            snapshot.selected_skill_id,
            snapshot.selected_skill_version,
        )
        if skill is None:
            raise KeyError("selected published Skill is unavailable")
        return skill

    def _fail_no_skill(self, snapshot: TaskSessionSnapshot) -> TaskSessionSnapshot:
        return self._transition(
            snapshot,
            "failed",
            next_interaction=ResultInteraction(
                status="failed",
                code="no_matching_published_skill",
                summary="没有找到可执行的已发布 Skill",
            ),
        )

    def _load_at_version(
        self, session_id: UUID, version: int
    ) -> TaskSessionSnapshot:
        snapshot = self.repository.get_task_session(session_id)
        if snapshot.version != version:
            raise TaskSessionConflictError("task session version conflict")
        return snapshot

    def _transition(
        self,
        snapshot: TaskSessionSnapshot,
        state: TaskSessionState,
        *,
        allow_reset: bool = False,
        **updates: Any,
    ) -> TaskSessionSnapshot:
        if not allow_reset and state not in ALLOWED_TRANSITIONS[snapshot.state]:
            raise ValueError(
                f"illegal task session transition: {snapshot.state} -> {state}"
            )
        return self._save(snapshot, state=state, **updates)

    def _persist_same_state(
        self, snapshot: TaskSessionSnapshot, **updates: Any
    ) -> TaskSessionSnapshot:
        return self._save(snapshot, state=snapshot.state, **updates)

    def _save(
        self, snapshot: TaskSessionSnapshot, *, state: TaskSessionState, **updates: Any
    ) -> TaskSessionSnapshot:
        payload = snapshot.model_dump(mode="python", by_alias=True)
        payload.update(updates)
        payload["state"] = state
        payload["version"] = snapshot.version + 1
        updated = TaskSessionSnapshot.model_validate(payload)
        return self.repository.update_task_session(
            updated, expected_version=snapshot.version
        )


def _find_skill(
    skills: list[SkillDefinition],
    skill_id: UUID | None,
    version: int | None,
) -> SkillDefinition | None:
    if skill_id is None or version is None:
        return None
    return next(
        (
            item
            for item in skills
            if item.skill_id == skill_id and item.version == version
        ),
        None,
    )


def _snapshot_to_view(snapshot: TaskSessionSnapshot) -> TaskSessionView:
    return TaskSessionView(
        session_id=snapshot.session_id,
        state=snapshot.state,
        version=snapshot.version,
        goal=snapshot.goal,
        plan_revision=snapshot.plan_revision,
        plan_hash=snapshot.plan_hash,
        next_interaction=snapshot.next_interaction,
    )


def _trusted_context(snapshot: TaskSessionSnapshot) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if snapshot.selected_object:
        result.update(deepcopy(snapshot.selected_object))
        result["selected_object"] = deepcopy(snapshot.selected_object)
    for evidence in snapshot.context_evidence:
        result[evidence.evidence_id] = deepcopy(evidence.output)
    return result


def _resolve_path(value: Any, path: str) -> Any:
    for part in path.split(".") if path else []:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError("trusted context path does not exist")
    return value


def _resolve_binding(
    expression: str,
    *,
    inputs: dict[str, Any],
    selected_object: dict[str, Any] | None,
) -> Any:
    if expression.startswith("literal."):
        return deepcopy(_resolve_path(inputs, expression.removeprefix("literal.")))
    if expression.startswith("task.content."):
        path = expression.removeprefix("task.content.")
        merged = {**(selected_object or {}), **inputs}
        return deepcopy(_resolve_path(merged, path))
    if expression.startswith("steps."):
        return {"$step_output": expression}
    raise ValueError("unsupported immutable Skill binding")


def _stable_write_key(
    *,
    tenant_id: str,
    skill: SkillDefinition,
    targets: list[str],
    step_id: str,
    arguments: dict[str, Any],
) -> str:
    payload = json.dumps(
        {
            "tenant_id": tenant_id,
            "skill_id": str(skill.skill_id),
            "skill_version": skill.version,
            "targets": sorted(targets),
            "step_id": step_id,
            "arguments": arguments,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _confirmation_interaction(
    plan: ExecutionPlan,
    revision: int,
    plan_hash: str,
    token: str,
) -> ConfirmationInteraction:
    writes = [step for step in plan.steps if step.side_effect == "write"]
    return ConfirmationInteraction(
        title="确认执行写操作",
        summary=plan.summary,
        plan_revision=revision,
        plan_hash=plan_hash,
        confirmation_token=token,
        systems=sorted({step.tool_id.partition(":")[0] for step in plan.steps}),
        target_objects=plan.target_objects,
        write_steps=[
            PlannedStepView(
                step_id=step.step_id,
                name=step.name,
                system=step.tool_id.partition(":")[0],
                arguments=step.arguments,
            )
            for step in writes
        ],
    )


def _step_views(results: list[Any]) -> list[StepResultView]:
    return [
        StepResultView(
            step_id=item.step_id,
            status=item.status,
            summary=(item.error.get("message") if item.error else None),
        )
        for item in results
    ]


def _find_record_by_identity(root: Any, identity: str) -> dict[str, Any] | None:
    queue: list[tuple[Any, int]] = [(root, 0)]
    visited = 0
    while queue and visited < 500:
        value, depth = queue.pop(0)
        visited += 1
        if isinstance(value, dict):
            if any(
                str(value.get(field)) == identity
                for field in ("id", "task_id", "record_id")
                if value.get(field) is not None
            ):
                return value
            if depth < 8:
                queue.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list) and depth < 8:
            queue.extend((child, depth + 1) for child in value[:200])
    return None
