from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypedDict
from uuid import uuid4

import httpx
from langgraph.graph import END, START, StateGraph

from app.command_center.schemas import (
    SkillDefinition,
    TaskMatchDecision,
    VerificationResult,
)
from app.command_center.testing import SkillRunResult


class ExecutionAgents(Protocol):
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
        response = self.client.get(
            f"{self.base_urls['onboarding_system']}/api/tasks",
            params={"operator_id": "u001", "status": "pending"},
        )
        response.raise_for_status()
        return [
            {**task, "system_code": "onboarding_system"}
            for task in response.json().get("items", [])
        ]

    def observe(self, task: dict[str, Any]) -> dict[str, Any]:
        task_response = self.client.get(
            f"{self.base_urls['onboarding_system']}/api/tasks/{task['task_id']}"
        )
        task_response.raise_for_status()
        purchase_response = self.client.get(
            f"{self.base_urls['connected_system']}/api/submissions"
        )
        purchase_response.raise_for_status()
        purchases = purchase_response.json().get("items", [])
        return {
            "task": task_response.json(),
            "purchase_requests": purchases,
            "purchase_count": len(purchases),
        }


class Runner(Protocol):
    def run(self, skill, task, *, run_id, literals=None) -> SkillRunResult: ...


@dataclass
class ExecutionDependencies:
    skills: Callable[[], list[SkillDefinition]]
    business_reader: BusinessReader
    agents: ExecutionAgents
    runner: Runner


class ExecutionState(TypedDict, total=False):
    user_request: str
    selected_object_id: str
    tasks: list[dict[str, Any]]
    skills: list[SkillDefinition]
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
        return {
            "tasks": dependencies.business_reader.search_tasks(state["user_request"]),
            "skills": dependencies.skills(),
            "status": "matching",
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
        return {
            "match": decision,
            "candidate_objects": candidates,
            "selected_object": candidates[0],
            "selected_skill": skill,
            "status": "ready",
        }

    def execute_skill(state: ExecutionState) -> ExecutionState:
        result = dependencies.runner.run(
            state["selected_skill"],
            state["selected_object"],
            run_id=uuid4(),
            literals=state["match"].literals,
        )
        return {
            "run_result": result,
            "status": "verifying" if result.status == "succeeded" else "failed",
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
            "status": status,
            "final_response": {
                "summary": verification.summary,
                "outputs": state["run_result"].outputs,
                "observed_state": observed,
            },
        }

    graph = StateGraph(ExecutionState)
    graph.add_node("load_context", load_context)
    graph.add_node("match_request", match_request)
    graph.add_node("execute_skill", execute_skill)
    graph.add_node("verify_result", verify)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "match_request")
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
