from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.command_center.langchain_purchase_agents import (
    PurchaseAgentRun,
    PurchaseTrackingLimitError,
    PurchaseTrackingProtocolError,
)
from app.command_center.schemas import (
    PurchaseProgressResult,
    PurchaseTrackingDraft,
    PurchaseTrackingScope,
    StepResult,
)


logger = logging.getLogger(__name__)


class PurchaseTrackingAgentSuite(Protocol):
    def scope(
        self, application: dict[str, Any]
    ) -> PurchaseAgentRun[PurchaseTrackingScope]: ...

    def trace(
        self, scope: PurchaseTrackingScope
    ) -> PurchaseAgentRun[PurchaseTrackingDraft]: ...

    def verify(
        self,
        scope: PurchaseTrackingScope,
        draft: PurchaseTrackingDraft,
        step_results: list[StepResult],
    ) -> PurchaseAgentRun[PurchaseProgressResult]: ...


@dataclass
class PurchaseTrackingDependencies:
    agents: PurchaseTrackingAgentSuite


class PurchaseTrackingState(TypedDict, total=False):
    selected_application: dict[str, Any]
    scope: PurchaseTrackingScope
    trace_draft: PurchaseTrackingDraft
    step_results: list[StepResult]
    events: list[dict[str, Any]]
    progress: PurchaseProgressResult
    status: str
    final_response: dict[str, Any]
    errors: list[str]


def build_purchase_tracking_graph(dependencies: PurchaseTrackingDependencies):
    def scope_application(state: PurchaseTrackingState) -> PurchaseTrackingState:
        application = state.get("selected_application") or {}
        if not str(application.get("id", "")).strip() or not str(
            application.get("applyNo", "")
        ).strip():
            return _failure_state(
                application,
                error="所选采购申请缺少可信标识",
                summary="无法确认所选采购申请的身份",
            )
        try:
            run = dependencies.agents.scope(application)
        except (ValueError, ValidationError, PurchaseTrackingProtocolError) as exc:
            logger.warning("Purchase tracking scope failed: %s", type(exc).__name__)
            return _failure_state(
                application,
                error="采购进度追踪发生技术错误",
                summary="系统无法建立采购追踪范围",
            )
        return {"scope": run.output, "events": run.events, "status": "tracing"}

    def trace_chain(state: PurchaseTrackingState) -> PurchaseTrackingState:
        try:
            run = dependencies.agents.trace(state["scope"])
        except (
            ValueError,
            ValidationError,
            PurchaseTrackingLimitError,
            PurchaseTrackingProtocolError,
        ) as exc:
            logger.warning("Purchase tracking execution failed: %s", type(exc).__name__)
            return _failure_state(
                state["scope"].application,
                error="采购进度追踪发生技术错误",
                summary="系统未能完成采购链路查询",
                events=state.get("events", []),
            )
        events = [*state.get("events", []), *run.events]
        if any(result.status != "succeeded" for result in run.step_results):
            return _failure_state(
                state["scope"].application,
                error="采购进度追踪发生技术错误",
                summary="采购链路中的只读查询执行失败",
                events=events,
                step_results=run.step_results,
            )
        return {
            "trace_draft": run.output,
            "step_results": run.step_results,
            "events": events,
            "status": "verifying",
        }

    def verify_and_summarize(state: PurchaseTrackingState) -> PurchaseTrackingState:
        try:
            run = dependencies.agents.verify(
                state["scope"],
                state["trace_draft"],
                state.get("step_results", []),
            )
        except (ValueError, ValidationError, PurchaseTrackingProtocolError) as exc:
            logger.warning("Purchase tracking verification failed: %s", type(exc).__name__)
            return _failure_state(
                state["scope"].application,
                error="采购进度追踪发生技术错误",
                summary="系统无法验证采购链路证据",
                events=state.get("events", []),
                step_results=state.get("step_results", []),
            )
        progress = run.output
        return {
            "progress": progress,
            "status": "succeeded" if progress.status != "failed" else "failed",
            "events": [*state.get("events", []), *run.events],
            "final_response": {
                "summary": progress.summary,
                "progress": progress.model_dump(mode="json"),
                "tool_evidence": state.get("events", []),
            },
            "errors": (
                []
                if progress.status != "failed"
                else ["采购进度追踪发生技术错误"]
            ),
        }

    graph = StateGraph(PurchaseTrackingState)
    graph.add_node("scope_application", scope_application)
    graph.add_node("trace_chain", trace_chain)
    graph.add_node("verify_and_summarize", verify_and_summarize)
    graph.add_edge(START, "scope_application")
    graph.add_conditional_edges(
        "scope_application",
        lambda state: state["status"],
        {"tracing": "trace_chain", "failed": END},
    )
    graph.add_conditional_edges(
        "trace_chain",
        lambda state: state["status"],
        {"verifying": "verify_and_summarize", "failed": END},
    )
    graph.add_edge("verify_and_summarize", END)
    return graph.compile()


def _failure_state(
    application: dict[str, Any],
    *,
    error: str,
    summary: str,
    events: list[dict[str, Any]] | None = None,
    step_results: list[StepResult] | None = None,
) -> PurchaseTrackingState:
    progress = PurchaseProgressResult(
        status="failed",
        summary=summary,
        stages=[
            {
                "stage": "application",
                "status": "failed",
                "summary": summary,
                "record_count": 1 if application else 0,
                "records": [application] if application else [],
                "evidence_step_ids": [],
            }
        ],
    )
    safe_events = list(events or [])
    return {
        "status": "failed",
        "errors": [error],
        "events": safe_events,
        "step_results": list(step_results or []),
        "progress": progress,
        "final_response": {
            "summary": summary,
            "progress": progress.model_dump(mode="json"),
            "tool_evidence": safe_events,
        },
    }
