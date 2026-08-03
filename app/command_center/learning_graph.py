from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import SkillDefinition, TestPlan


class LearningAgents(Protocol):
    def segment_trace(self, trace: Any) -> Any: ...
    def attribute_apis(self, segmentation: Any, trace: Any, catalog: Any) -> Any: ...
    def map_fields(self, attribution: Any, trace: Any, catalog: Any) -> Any: ...
    def analyze_demonstration(self, trace: Any, catalog: Any) -> Any: ...
    def compile_skill(self, mapping: Any, attribution: Any, trace: Any, catalog: Any) -> SkillDefinition: ...
    def design_tests(self, skill: SkillDefinition) -> TestPlan | list[dict[str, Any]]: ...


class SkillTester(Protocol):
    def run(self, skill: SkillDefinition, case: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class LearningDependencies:
    repository: CommandCenterRepository
    agents: LearningAgents
    tester: SkillTester
    catalog: Any
    publish_policy: Literal["auto_publish", "verified_candidate"] = "auto_publish"


class LearningState(TypedDict, total=False):
    recording_id: str
    trace: Any
    analysis: Any
    segmentation: Any
    attribution: Any
    mapping: Any
    candidate_skill: SkillDefinition
    test_plan: list[dict[str, Any]]
    test_results: list[dict[str, Any]]
    final_status: str
    errors: list[str]
    failure_stage: Literal["analysis", "testing"]
    failure_reasons: list[str]


def build_learning_graph(dependencies: LearningDependencies):
    staged = all(
        hasattr(dependencies.agents, name)
        for name in ("segment_trace", "attribute_apis", "map_fields")
    )

    def reject(stage_result: Any, fallback: str) -> LearningState:
        payload = (
            stage_result
            if isinstance(stage_result, dict)
            else stage_result.model_dump(mode="json")
        )
        reasons = [
            str(item.get("description", "")).strip()
            for item in payload.get("uncertainties", [])
            if isinstance(item, dict) and str(item.get("description", "")).strip()
        ]
        if not reasons and str(payload.get("summary", "")).strip():
            reasons.append(str(payload["summary"]).strip())
        return {
            "final_status": "rejected",
            "failure_stage": "analysis",
            "failure_reasons": reasons or [fallback],
        }

    def segment_trace(state: LearningState) -> LearningState:
        if staged:
            segmentation = dependencies.agents.segment_trace(state["trace"])
            conclusive = (
                segmentation.get("conclusive", False)
                if isinstance(segmentation, dict)
                else segmentation.conclusive
            )
            if not conclusive:
                return {
                    "segmentation": segmentation,
                    **reject(segmentation, "演示时序无法可靠分段。"),
                }
            return {"segmentation": segmentation, "final_status": "analyzing"}

        analysis = dependencies.agents.analyze_demonstration(
            state["trace"], dependencies.catalog
        )
        compilable = analysis.get("compilable", False) if isinstance(analysis, dict) else analysis.compilable
        if not compilable:
            return {"analysis": analysis, **reject(analysis, "演示内容不足，无法生成可复用 Skill。")}
        return {"analysis": analysis, "segmentation": analysis, "final_status": "analyzing"}

    def attribute_apis(state: LearningState) -> LearningState:
        if not staged:
            return {"attribution": state["analysis"], "final_status": "analyzing"}
        attribution = dependencies.agents.attribute_apis(
            state["segmentation"], state["trace"], dependencies.catalog
        )
        attributable = attribution.get("attributable", False) if isinstance(attribution, dict) else attribution.attributable
        if not attributable:
            return {"attribution": attribution, **reject(attribution, "无法把演示证据归因到允许的 API Tool。")}
        return {"attribution": attribution, "final_status": "analyzing"}

    def map_fields(state: LearningState) -> LearningState:
        if not staged:
            return {"mapping": state["analysis"], "final_status": "analyzing"}
        mapping = dependencies.agents.map_fields(
            state["attribution"], state["trace"], dependencies.catalog
        )
        compilable = mapping.get("compilable", False) if isinstance(mapping, dict) else mapping.compilable
        if not compilable:
            return {"mapping": mapping, **reject(mapping, "字段证据不足，无法编译可复用 Skill。")}
        return {"mapping": mapping, "final_status": "analyzing"}

    def compile_skill(state: LearningState) -> LearningState:
        if staged:
            compiled = dependencies.agents.compile_skill(
                state["mapping"], state["attribution"], state["trace"], dependencies.catalog
            )
        else:
            compiled = dependencies.agents.compile_skill(
                state["analysis"], state["trace"], dependencies.catalog
            )
        skill = compiled.model_copy(update={"status": "testing"})
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

    def retain_verified_candidate(state: LearningState) -> LearningState:
        skill = state["candidate_skill"]
        verified = dependencies.repository.mark_verified_candidate(
            skill.skill_id, skill.version
        )
        return {
            "candidate_skill": verified,
            "final_status": "verified_candidate",
        }

    graph = StateGraph(LearningState)
    graph.add_node("segment_trace", segment_trace)
    graph.add_node("attribute_apis", attribute_apis)
    graph.add_node("map_fields", map_fields)
    graph.add_node("compile_skill", compile_skill)
    graph.add_node("execute_tests", execute_tests)
    graph.add_node("publish_skill", publish)
    graph.add_node("retain_verified_candidate", retain_verified_candidate)
    graph.add_edge(START, "segment_trace")
    graph.add_conditional_edges(
        "segment_trace",
        lambda state: state["final_status"],
        {"analyzing": "attribute_apis", "rejected": END},
    )
    graph.add_conditional_edges(
        "attribute_apis",
        lambda state: state["final_status"],
        {"analyzing": "map_fields", "rejected": END},
    )
    graph.add_conditional_edges(
        "map_fields",
        lambda state: state["final_status"],
        {"analyzing": "compile_skill", "rejected": END},
    )
    graph.add_edge("compile_skill", "execute_tests")
    graph.add_conditional_edges(
        "execute_tests",
        lambda state: (
            "rejected"
            if state["final_status"] == "rejected"
            else dependencies.publish_policy
        ),
        {
            "auto_publish": "publish_skill",
            "verified_candidate": "retain_verified_candidate",
            "rejected": END,
        },
    )
    graph.add_edge("publish_skill", END)
    graph.add_edge("retain_verified_candidate", END)
    return graph.compile()
