from datetime import UTC, datetime

from app.command_center.langchain_purchase_agents import PurchaseAgentRun
from app.command_center.purchase_tracking_graph import (
    PurchaseTrackingDependencies,
    build_purchase_tracking_graph,
)
from app.command_center.schemas import (
    PurchaseProgressResult,
    PurchaseTrackingDraft,
    PurchaseTrackingScope,
    StepResult,
)


def application_record():
    return {
        "id": "application-1",
        "applyNo": "CGSQ01",
        "applyBy": "孟明佳",
    }


def scope_result():
    return PurchaseTrackingScope(
        goal="追踪采购申请进度",
        application=application_record(),
        application_id="application-1",
        application_number="CGSQ01",
    )


def progress_result(status="complete"):
    return PurchaseProgressResult(
        status=status,
        summary="采购链路已追踪",
        stages=[
            {
                "stage": "application",
                "status": "completed",
                "summary": "采购申请已找到",
                "record_count": 1,
                "records": [application_record()],
                "evidence_step_ids": [],
            }
        ],
    )


def step_result(*, status="succeeded"):
    now = datetime.now(UTC)
    return StepResult(
        run_id="552d703b-6a45-4ca7-829a-5f52d4b78755",
        step_id="tool_01",
        tool_id="yifeng_mes:purchase_orders",
        status=status,
        started_at=now,
        ended_at=now,
        normalized_output={"result": {"records": []}},
        error={"code": "Timeout"} if status == "failed" else {},
        side_effect={"occurred": False},
    )


class TrackingAgents:
    def __init__(self, *, progress_status="complete", failed_step=False):
        self.calls = []
        self.progress_status = progress_status
        self.failed_step = failed_step

    def scope(self, application):
        self.calls.append("scope")
        return PurchaseAgentRun(output=scope_result())

    def trace(self, scope):
        self.calls.append("trace")
        return PurchaseAgentRun(
            output=PurchaseTrackingDraft(
                status=self.progress_status,
                summary="追踪执行结束",
                evidence_step_ids=["tool_01"],
            ),
            step_results=[
                step_result(status="failed" if self.failed_step else "succeeded")
            ],
            events=[{"step_id": "tool_01", "status": "succeeded"}],
        )

    def verify(self, scope, draft, step_results):
        self.calls.append("verify")
        return PurchaseAgentRun(output=progress_result(self.progress_status))


def tracking_graph(agents):
    return build_purchase_tracking_graph(PurchaseTrackingDependencies(agents=agents))


def test_graph_runs_scope_trace_and_verify_in_order():
    agents = TrackingAgents()

    result = tracking_graph(agents).invoke(
        {"selected_application": application_record()}
    )

    assert agents.calls == ["scope", "trace", "verify"]
    assert result["status"] == "succeeded"
    assert result["final_response"]["progress"]["status"] == "complete"
    assert result["final_response"]["tool_evidence"] == [
        {"step_id": "tool_01", "status": "succeeded"}
    ]


def test_graph_preserves_business_pending_as_successful_result():
    agents = TrackingAgents(progress_status="business_pending")

    result = tracking_graph(agents).invoke(
        {"selected_application": application_record()}
    )

    assert result["status"] == "succeeded"
    assert result["final_response"]["progress"]["status"] == "business_pending"


def test_graph_marks_failed_tool_as_technical_failure_without_verification():
    agents = TrackingAgents(failed_step=True)

    result = tracking_graph(agents).invoke(
        {"selected_application": application_record()}
    )

    assert agents.calls == ["scope", "trace"]
    assert result["status"] == "failed"
    assert result["errors"] == ["采购进度追踪发生技术错误"]
    assert result["final_response"]["progress"]["status"] == "failed"


def test_graph_rejects_selected_application_without_trusted_identity():
    agents = TrackingAgents()

    result = tracking_graph(agents).invoke(
        {"selected_application": {"applyBy": "孟明佳"}}
    )

    assert agents.calls == []
    assert result["status"] == "failed"
    assert result["errors"] == ["所选采购申请缺少可信标识"]
