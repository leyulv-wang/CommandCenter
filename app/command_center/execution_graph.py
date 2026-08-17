from __future__ import annotations

import re
from hashlib import sha256
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypedDict
from uuid import uuid4

import httpx
from langgraph.graph import END, START, StateGraph

from app.command_center.schemas import (
    DirectToolPlan,
    DirectToolVerification,
    SkillDefinition,
    SkillInput,
    StepResult,
    TaskMatchDecision,
    VerificationResult,
)
from app.command_center.direct_tool_runner import (
    DirectToolRunResult,
    DirectToolRunner,
)
from app.command_center.testing import SkillRunResult
from app.command_center.tool_catalog import ToolDefinition


class ExecutionAgents(Protocol):
    def plan_tool_request(
        self,
        user_request: str,
        task_context: dict[str, Any],
        tools: list[ToolDefinition],
    ) -> DirectToolPlan: ...

    def verify_tool_result(
        self,
        user_request: str,
        plan: DirectToolPlan,
        step_results: list[StepResult],
    ) -> DirectToolVerification: ...

    def match_request(
        self,
        user_request: str,
        tasks: list[dict[str, Any]],
        skills: list[SkillDefinition],
    ) -> TaskMatchDecision: ...

    def verify_result(
        self,
        skill: SkillDefinition,
        step_results: list[Any],
        observed_state: dict[str, Any],
    ) -> VerificationResult: ...


class BusinessReader(Protocol):
    def search_tasks(self, user_request: str) -> list[dict[str, Any]]: ...
    def observe(self, task: dict[str, Any]) -> dict[str, Any]: ...


class LocalBusinessReader:
    def __init__(self, client: httpx.Client, base_urls: dict[str, str]):
        self.client = client
        self.base_urls = {
            code: url.rstrip("/")
            for code, url in base_urls.items()
        }

    def search_tasks(self, user_request: str) -> list[dict[str, Any]]:
        request_key = sha256(user_request.strip().encode("utf-8")).hexdigest()[:16]
        return [
            {
                "system_code": "connected_system",
                "task_id": f"purchase-request-{request_key}",
                "content": {},
                "user_request": user_request,
            }
        ]

    def observe(self, task: dict[str, Any]) -> dict[str, Any]:
        purchase_response = self.client.get(
            f"{self.base_urls['connected_system']}/api/submissions"
        )
        purchase_response.raise_for_status()
        purchases = purchase_response.json().get("items", [])
        return {
            "purchase_requests": purchases,
            "purchase_count": len(purchases),
        }


class UserRequestReader:
    """Create one neutral execution object for an employee's direct request."""

    def search_tasks(self, user_request: str) -> list[dict[str, Any]]:
        return [
            {
                "system_code": "command_center",
                "task_id": "user-request",
                "content": {},
                "user_request": user_request,
            }
        ]

    def observe(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "request": task,
            "observation_source": "executed_tool_results",
        }


class Runner(Protocol):
    def run(self, skill, task, *, run_id, literals=None) -> SkillRunResult: ...


def executable_skill_set(
    published: list[SkillDefinition],
    verified_candidates: list[SkillDefinition],
    catalog: Any,
) -> list[SkillDefinition]:
    verified: list[SkillDefinition] = []
    for skill in verified_candidates:
        try:
            tools = [catalog.get(step.tool_id) for step in skill.steps]
        except (KeyError, ValueError, httpx.HTTPError):
            continue
        if all(
            step.side_effect == tool.side_effect
            for step, tool in zip(skill.steps, tools, strict=True)
        ):
            verified.append(_generalize_indexed_array_bindings(skill, catalog))
    return [*published, *verified]


_INDEXED_BODY_BINDING = re.compile(r"^body\.([^.]+)\.\d+\..+$")


def _generalize_indexed_array_bindings(
    skill: SkillDefinition,
    catalog: Any,
) -> SkillDefinition:
    """Collapse recorded fixed array rows into one runtime array input.

    A demonstration may contain two material rows, but that count is not a stable
    business invariant. The OpenAPI request schema is the deterministic boundary:
    only fields declared as arrays are generalized here. An agent still maps the
    current MES evidence into the array value at execution time.
    """

    result = skill.model_copy(deep=True)
    removed_expressions: set[str] = set()
    array_inputs: dict[str, tuple[dict[str, Any], bool]] = {}
    for step in result.steps:
        tool = catalog.get(step.tool_id)
        properties = tool.body_schema.get("properties", {})
        required_fields = tool.body_schema.get("required", [])
        if not isinstance(properties, dict):
            continue
        grouped: dict[str, list[str]] = {}
        for target in step.input_bindings:
            match = _INDEXED_BODY_BINDING.fullmatch(target)
            if match:
                grouped.setdefault(match.group(1), []).append(target)
        for field_name, targets in grouped.items():
            field_schema = properties.get(field_name, {})
            if not isinstance(field_schema, dict) or field_schema.get("type") != "array":
                continue
            for target in targets:
                removed_expressions.add(step.input_bindings.pop(target))
            step.input_bindings[f"body.{field_name}"] = f"task.content.{field_name}"
            array_inputs[field_name] = (
                field_schema,
                isinstance(required_fields, list) and field_name in required_fields,
            )

    if not array_inputs:
        return result

    remaining_expressions = {
        expression
        for step in result.steps
        for expression in step.input_bindings.values()
    }
    removed_names = {
        expression.removeprefix("task.content.").split(".", 1)[0]
        for expression in removed_expressions
        if expression.startswith("task.content.")
        and expression not in remaining_expressions
    }
    inputs = [item for item in result.inputs if item.name not in removed_names]
    existing_names = {item.name for item in inputs}
    for field_name, (field_schema, required) in array_inputs.items():
        if field_name in existing_names:
            continue
        item_schema = field_schema.get("items", {})
        item_properties = (
            item_schema.get("properties", {}) if isinstance(item_schema, dict) else {}
        )
        fields = ", ".join(str(name) for name in item_properties) or "object"
        inputs.append(
            SkillInput(
                name=field_name,
                type="array",
                description=f"对象数组；每项字段：{fields}",
                required=required,
                source_hint="由当前业务对象及只读 Tool 证据映射",
            )
        )
    result.inputs = inputs
    return result


@dataclass
class ExecutionDependencies:
    skills: Callable[[], list[SkillDefinition]]
    business_reader: BusinessReader
    agents: ExecutionAgents
    runner: Runner
    tools: Callable[[], list[ToolDefinition]] | None = None
    direct_runner: DirectToolRunner | None = None


class ExecutionState(TypedDict, total=False):
    user_request: str
    task_context: dict[str, Any]
    selected_object_id: str
    tasks: list[dict[str, Any]]
    skills: list[SkillDefinition]
    tools: list[ToolDefinition]
    tool_plan: DirectToolPlan
    direct_run_result: DirectToolRunResult
    tool_verification: DirectToolVerification
    execution_mode: str
    match: TaskMatchDecision
    candidate_objects: list[dict[str, Any]]
    selected_object: dict[str, Any]
    selected_skill: SkillDefinition
    run_result: SkillRunResult
    verification_result: VerificationResult
    status: str
    final_response: dict[str, Any]
    errors: list[str]


def build_execution_graph(dependencies: ExecutionDependencies):
    def load_context(state: ExecutionState) -> ExecutionState:
        tasks = dependencies.business_reader.search_tasks(state["user_request"])
        task_context = state.get("task_context")
        if task_context and tasks:
            first = dict(tasks[0])
            first["content"] = {
                **dict(first.get("content", {})),
                **task_context,
            }
            tasks = [first, *tasks[1:]]
        skills = dependencies.skills()
        required_skill_id = (
            task_context.get("required_skill_id")
            if isinstance(task_context, dict)
            else None
        )
        if required_skill_id:
            # A server-issued action pins execution to one executable Skill version.
            # This is a publication/security boundary; the agent still maps inputs.
            skills = [
                skill for skill in skills if str(skill.skill_id) == str(required_skill_id)
            ]
        return {
            "tasks": tasks,
            "skills": skills,
            "tools": dependencies.tools() if dependencies.tools is not None else [],
            "status": "matching",
        }

    def plan_direct_tool(state: ExecutionState) -> ExecutionState:
        task_content = (
            state["tasks"][0].get("content", {}) if state["tasks"] else {}
        )
        if task_content.get("required_skill_id") or task_content.get(
            "requested_capability"
        ) == "purchase_follow_up":
            # This trusted row action must use the verified, idempotent write Skill.
            # Read-only direct Tool planning is reserved for preparing its MES evidence.
            return {"status": "skill_matching"}
        if not state["tools"] or dependencies.direct_runner is None:
            return {"status": "skill_matching"}
        task_context = state["tasks"][0] if state["tasks"] else {}
        plan = dependencies.agents.plan_tool_request(
            state["user_request"],
            task_context,
            state["tools"],
        )
        if plan.status == "not_applicable":
            return {"tool_plan": plan, "status": "skill_matching"}
        if plan.status == "needs_input":
            return {
                "tool_plan": plan,
                "status": "needs_input",
                "errors": [
                    "完成任务还需要：" + "、".join(plan.missing_inputs)
                ],
            }
        return {
            "tool_plan": plan,
            "execution_mode": "tool",
            "status": "tool_ready",
        }

    def execute_direct_tool(state: ExecutionState) -> ExecutionState:
        if dependencies.direct_runner is None:
            return {"status": "failed", "errors": ["Tool 执行器不可用"]}
        result = dependencies.direct_runner.run(
            state["tool_plan"],
            run_id=uuid4(),
        )
        if result.status != "succeeded":
            return {
                "direct_run_result": result,
                "execution_mode": "tool",
                "status": "failed",
                "errors": ["Tool 执行失败"],
                "final_response": {
                    "summary": "Tool 执行失败",
                    "outputs": result.outputs,
                    "tool_evidence": result.evidence,
                },
            }
        return {
            "direct_run_result": result,
            "execution_mode": "tool",
            "status": "tool_verifying",
        }

    def verify_direct_tool(state: ExecutionState) -> ExecutionState:
        verification = dependencies.agents.verify_tool_result(
            state["user_request"],
            state["tool_plan"],
            state["direct_run_result"].step_results,
        )
        status = "succeeded" if verification.status == "passed" else "failed"
        return {
            "tool_verification": verification,
            "execution_mode": "tool",
            "status": status,
            "final_response": {
                "summary": verification.summary,
                "outputs": state["direct_run_result"].outputs,
                "tool_evidence": state["direct_run_result"].evidence,
                "verification": verification.model_dump(mode="json"),
            },
        }

    def match_request(state: ExecutionState) -> ExecutionState:
        if not state["skills"]:
            return {"status": "failed", "errors": ["没有已发布 Skill"]}
        decision = dependencies.agents.match_request(
            state["user_request"],
            state["tasks"],
            state["skills"],
        )
        task_by_id = {str(task["task_id"]): task for task in state["tasks"]}
        candidates = [
            task_by_id[task_id]
            for task_id in decision.candidate_task_ids
            if task_id in task_by_id
        ]
        selected_id = state.get("selected_object_id")
        if selected_id:
            candidates = [task for task in candidates if task["task_id"] == selected_id]
        if len(candidates) > 1:
            return {
                "match": decision,
                "candidate_objects": candidates,
                "status": "needs_object_selection",
            }
        if not candidates:
            return {
                "match": decision,
                "candidate_objects": [],
                "status": "failed",
                "errors": ["没有匹配的业务对象"],
            }
        skill = next(
            (
                item
                for item in state["skills"]
                if item.skill_id == decision.selected_skill_id
            ),
            None,
        )
        if skill is None:
            return {"status": "failed", "errors": ["智能体选择了未发布 Skill"]}
        selected = dict(candidates[0])
        selected["content"] = {
            **dict(selected.get("content", {})),
            **decision.literals,
        }
        return {
            "match": decision,
            "candidate_objects": candidates,
            "selected_object": selected,
            "selected_skill": skill,
            "execution_mode": "skill",
            "status": "ready",
        }

    def execute_skill(state: ExecutionState) -> ExecutionState:
        available = {
            *state["match"].literals,
            *dict(state["selected_object"].get("content", {})),
        }
        missing = [
            item.name
            for item in state["selected_skill"].inputs
            if item.required and item.name not in available
        ]
        if missing:
            return {
                "status": "failed",
                "errors": ["Skill 必填输入不完整"],
            }
        try:
            result = dependencies.runner.run(
                state["selected_skill"],
                state["selected_object"],
                run_id=uuid4(),
                literals=state["match"].literals,
            )
        except (KeyError, ValueError):
            return {
                "status": "failed",
                "errors": ["Skill 输入无法绑定到执行参数"],
            }
        return {
            "run_result": result,
            "execution_mode": "skill",
            "status": "verifying" if result.status == "succeeded" else "failed",
            "errors": (
                [] if result.status == "succeeded" else ["Skill 步骤执行失败"]
            ),
            "final_response": (
                {}
                if result.status == "succeeded"
                else {
                    "summary": "Skill 步骤执行失败，未完成业务操作",
                    "outputs": result.outputs,
                    "step_results": [
                        item.model_dump(mode="json") for item in result.step_results
                    ],
                }
            ),
        }

    def verify(state: ExecutionState) -> ExecutionState:
        observed = dependencies.business_reader.observe(state["selected_object"])
        verification = dependencies.agents.verify_result(
            state["selected_skill"],
            state["run_result"].step_results,
            observed,
        )
        status = "succeeded" if verification.status == "passed" else "failed"
        return {
            "verification_result": verification,
            "execution_mode": "skill",
            "status": status,
            "final_response": {
                "summary": verification.summary,
                "outputs": state["run_result"].outputs,
                "observed_state": observed,
            },
        }

    graph = StateGraph(ExecutionState)
    graph.add_node("load_context", load_context)
    graph.add_node("plan_direct_tool", plan_direct_tool)
    graph.add_node("execute_direct_tool", execute_direct_tool)
    graph.add_node("verify_direct_tool", verify_direct_tool)
    graph.add_node("match_request", match_request)
    graph.add_node("execute_skill", execute_skill)
    graph.add_node("verify_result", verify)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "plan_direct_tool")
    graph.add_conditional_edges(
        "plan_direct_tool",
        lambda state: state["status"],
        {
            "tool_ready": "execute_direct_tool",
            "skill_matching": "match_request",
            "needs_input": END,
        },
    )
    graph.add_conditional_edges(
        "execute_direct_tool",
        lambda state: state["status"],
        {"tool_verifying": "verify_direct_tool", "failed": END},
    )
    graph.add_edge("verify_direct_tool", END)
    graph.add_conditional_edges(
        "match_request",
        lambda state: state["status"],
        {
            "ready": "execute_skill",
            "needs_object_selection": END,
            "failed": END,
        },
    )
    graph.add_conditional_edges(
        "execute_skill",
        lambda state: state["status"],
        {"verifying": "verify_result", "failed": END},
    )
    graph.add_edge("verify_result", END)
    return graph.compile()
