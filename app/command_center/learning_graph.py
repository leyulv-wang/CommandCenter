from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

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
    failure_stage: Literal["analysis", "testing"]
    failure_reasons: list[str]


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
        if compilable:
            return {
                "analysis": analysis,
                "final_status": "analyzing",
            }
        uncertainties = (
            analysis.get("uncertainties", [])
            if isinstance(analysis, dict)
            else analysis.uncertainties
        )
        reasons = [
            str(item.get("description", "")).strip()
            for item in uncertainties
            if isinstance(item, dict) and str(item.get("description", "")).strip()
        ]
        summary = (
            analysis.get("summary", "")
            if isinstance(analysis, dict)
            else analysis.summary
        )
        if not reasons and str(summary).strip():
            reasons.append(str(summary).strip())
        return {
            "analysis": analysis,
            "final_status": "rejected",
            "failure_stage": "analysis",
            "failure_reasons": reasons or ["演示内容不足，无法生成可复用 Skill。"],
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
        rejected = passed != required
        failure_reasons: list[str] = []
        if rejected:
            for result in results:
                if (
                    result["status"] == "passed"
                    and not result.get("unknown_side_effect", False)
                ):
                    continue
                verification = result.get("verification", {})
                summary = (
                    verification.get("summary", "")
                    if isinstance(verification, dict)
                    else ""
                )
                failure_reasons.append(
                    str(summary).strip()
                    or f"{result['category']} 测试未通过。"
                )
        return {
            "test_results": results,
            "final_status": "rejected" if rejected else "ready_to_publish",
            **(
                {
                    "failure_stage": "testing",
                    "failure_reasons": failure_reasons,
                }
                if rejected
                else {}
            ),
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
