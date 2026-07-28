from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import SkillDefinition, TestPlan


class LearningAgents(Protocol):
    def analyze_demonstration(self, trace: Any, catalog: Any) -> Any: ...
    def compile_skill(self, analysis: Any, trace: Any, catalog: Any) -> SkillDefinition: ...
    def design_tests(self, skill: SkillDefinition) -> TestPlan | list[dict[str, Any]]: ...


class SkillTester(Protocol):
    def run(self, skill: SkillDefinition, case: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class LearningDependencies:
    repository: CommandCenterRepository
    agents: LearningAgents
    tester: SkillTester
    catalog: Any


class LearningState(TypedDict, total=False):
    recording_id: str
    trace: Any
    analysis: Any
    candidate_skill: SkillDefinition
    test_plan: list[dict[str, Any]]
    test_results: list[dict[str, Any]]
    final_status: str
    errors: list[str]


def build_learning_graph(dependencies: LearningDependencies):
    def analyze(state: LearningState) -> LearningState:
        analysis = dependencies.agents.analyze_demonstration(
            state["trace"],
            dependencies.catalog,
        )
        compilable = (
            analysis.get("compilable", False)
            if isinstance(analysis, dict)
            else analysis.compilable
        )
        return {
            "analysis": analysis,
            "final_status": "analyzing" if compilable else "rejected",
        }

    def compile_skill(state: LearningState) -> LearningState:
        skill = dependencies.agents.compile_skill(
            state["analysis"],
            state["trace"],
            dependencies.catalog,
        ).model_copy(update={"status": "testing"})
        dependencies.repository.save_candidate_skill(skill)
        designed = dependencies.agents.design_tests(skill)
        cases = (
            [case.model_dump(mode="json") for case in designed.cases]
            if isinstance(designed, TestPlan)
            else designed
        )
        return {
            "candidate_skill": skill,
            "test_plan": cases,
            "final_status": "testing",
        }

    def execute_tests(state: LearningState) -> LearningState:
        skill = state["candidate_skill"]
        results: list[dict[str, Any]] = []
        for case in state["test_plan"]:
            result = dependencies.tester.run(skill, case)
            results.append(result)
            dependencies.repository.save_test_result(
                skill.skill_id,
                skill.version,
                result["category"],
                result["status"],
                result,
            )
        required = {"normal", "parameter_variation", "idempotency"}
        passed = {
            result["category"]
            for result in results
            if result["status"] == "passed"
            and not result.get("unknown_side_effect", False)
        }
        return {
            "test_results": results,
            "final_status": "ready_to_publish" if passed == required else "rejected",
        }

    def publish(state: LearningState) -> LearningState:
        skill = state["candidate_skill"]
        published = dependencies.repository.publish_skill(skill.skill_id, skill.version)
        return {"candidate_skill": published, "final_status": "published"}

    graph = StateGraph(LearningState)
    graph.add_node("analyze_demonstration", analyze)
    graph.add_node("compile_skill", compile_skill)
    graph.add_node("execute_tests", execute_tests)
    graph.add_node("publish_skill", publish)
    graph.add_edge(START, "analyze_demonstration")
    graph.add_conditional_edges(
        "analyze_demonstration",
        lambda state: state["final_status"],
        {"analyzing": "compile_skill", "rejected": END},
    )
    graph.add_edge("compile_skill", "execute_tests")
    graph.add_conditional_edges(
        "execute_tests",
        lambda state: state["final_status"],
        {"ready_to_publish": "publish_skill", "rejected": END},
    )
    graph.add_edge("publish_skill", END)
    return graph.compile()
