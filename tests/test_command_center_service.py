from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.command_center.repository import CommandCenterRepository
from app.command_center.router import CreateRecordingRequest, CreateTaskRunRequest
from app.command_center.schemas import OperationTrace, SkillDefinition
from app.command_center.service import CommandCenterService, _safe_prior_analysis_reasons
from app.command_center.extension_recorder import ExtensionRecorder
from app.command_center.schemas import ExtensionEventBatch
from app.command_center.system_profiles import ProfileLimits, SystemProfile, ToolPermission
from app.command_center.tool_catalog import ToolCatalog, ToolDefinition
from tests.test_command_center_schemas import valid_skill_payload


class Recorder:
    async def start(self, recording_id, objective, source_task, start_url):
        self.started = (recording_id, start_url)

    async def stop(self, recording_id):
        return OperationTrace(
            trace_id=uuid4(),
            recording_id=recording_id,
            objective="演示采购回写",
            source_task={"object_id": "OFFICE-1"},
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )


class Graph:
    def __init__(self, result):
        self.result = result

    def invoke(self, state):
        self.state = state
        return self.result


class SequenceGraph:
    def __init__(self, *results):
        self.results = list(results)
        self.states = []

    def invoke(self, state):
        self.states.append(state)
        return self.results.pop(0)


def action_skill() -> SkillDefinition:
    payload = valid_skill_payload()
    payload["status"] = "verified_candidate"
    payload["action"] = {
        "action_id": "create-follow-up",
        "label": "创建跟进任务",
        "instruction": "为所选业务对象创建跟进任务",
        "object_id_field": "id",
        "required_record_fields": ["id", "applyNo"],
        "context_request": "读取所选业务对象及其全部明细，仅使用只读 Tool",
        "requires_context_records": True,
        "source_reference_field": "applyNo",
        "confirmation": "required",
    }
    return SkillDefinition.model_validate(payload)


class FailingGraph:
    def invoke(self, state):
        raise RuntimeError("secret provider detail")


class AbortableExtension:
    def __init__(self):
        self.aborted = None

    def abort_authorized(self, recording_id, token):
        if token != "valid-token":
            raise PermissionError("extension recording authorization failed")
        self.aborted = recording_id


def test_prior_analysis_reasons_are_bounded_and_filter_sensitive_text():
    reasons = _safe_prior_analysis_reasons(
        {
            "api_learning_result": {
                "failure_reasons": [
                    "字段对应关系证据不足",
                    "Authorization token leaked",
                    "x" * 400,
                    "原因四",
                    "原因五",
                    "原因六",
                    "原因七",
                ]
            }
        }
    )

    assert reasons[0] == "字段对应关系证据不足"
    assert all("token" not in reason.lower() for reason in reasons)
    assert len(reasons) == 5
    assert max(map(len, reasons)) == 300


def test_service_connects_recording_stop_to_learning_graph(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    recorder = Recorder()
    learning = Graph({"final_status": "published", "test_results": []})
    service = CommandCenterService(
        repository=repository,
        recorder=recorder,
        learning_graph=learning,
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )

    import asyncio

    asyncio.run(service.start_recording(created["recording_id"]))
    stopped = asyncio.run(service.stop_recording(created["recording_id"]))

    assert recorder.started[1] == "http://127.0.0.1:8101"
    assert stopped["status"] == "published"
    assert learning.state["trace"]["objective"] == "演示采购回写"
    assert repository.get_recording(created["recording_id"])["status"] == "published"


def test_service_persists_ordered_multi_system_recording_scope(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    profiles = {
        "yifeng_mes": object(),
        "connected_system": object(),
    }
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        system_profiles=profiles,
    )

    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询 MES 采购申请并创建本地后续处理单",
            source_system="yifeng_mes",
            source_systems=["yifeng_mes", "connected_system"],
            recording_mode="multi_system",
            source_task_id="joint-demo",
            capture_source="browser_extension",
        )
    )

    assert created["recording_mode"] == "multi_system"
    assert created["source_systems"] == ["yifeng_mes", "connected_system"]
    assert repository.get_recording(created["recording_id"])["source_systems"] == [
        "yifeng_mes",
        "connected_system",
    ]


def test_service_rejects_unknown_system_in_multi_system_scope(tmp_path):
    service = CommandCenterService(
        repository=CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}"),
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        system_profiles={"yifeng_mes": object()},
    )

    with pytest.raises(ValueError, match="not configured"):
        service.create_recording(
            CreateRecordingRequest(
                objective="联合演示",
                source_system="yifeng_mes",
                source_systems=["yifeng_mes", "missing_system"],
                recording_mode="multi_system",
                source_task_id="joint-demo",
                capture_source="browser_extension",
            )
        )


def test_service_persists_learning_rejection_feedback(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph(
            {
                "final_status": "rejected",
                "failure_stage": "analysis",
                "failure_reasons": ["未观察到创建采购申请接口"],
            }
        ),
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )

    import asyncio

    asyncio.run(service.start_recording(created["recording_id"]))
    stopped = asyncio.run(service.stop_recording(created["recording_id"]))

    assert stopped["status"] == "needs_reteach"
    assert stopped["failure_stage"] == "analysis"
    assert stopped["failure_reasons"] == ["未观察到创建采购申请接口"]
    persisted = repository.get_recording(created["recording_id"])
    assert persisted["failure_stage"] == "analysis"
    assert persisted["failure_reasons"] == ["未观察到创建采购申请接口"]


def test_service_sanitizes_learning_system_failure(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=FailingGraph(),
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )

    import asyncio

    asyncio.run(service.start_recording(created["recording_id"]))
    stopped = asyncio.run(service.stop_recording(created["recording_id"]))

    assert stopped["status"] == "needs_reteach"
    assert stopped["failure_stage"] == "system"
    assert stopped["failure_reasons"] == [
        "系统处理演示时发生错误，请检查模型配置和服务日志后重试。"
    ]
    assert "secret provider detail" not in str(stopped)
    assert repository.get_recording(created["recording_id"]) == stopped


def test_service_persists_natural_language_task_run(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    execution = Graph(
        {
            "status": "succeeded",
            "final_response": {"summary": "采购创建并回写完成"},
        }
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )

    run = service.create_task_run(
        CreateTaskRunRequest(user_request="处理签字笔库存不足任务")
    )

    assert run["status"] == "succeeded"
    assert repository.get_task_run(run["run_id"])["final_response"]["summary"] == (
        "采购创建并回写完成"
    )


def test_service_projects_skill_actions_onto_matching_result_rows(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = action_skill()
    repository.save_candidate_skill(skill)
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph(
            {
                "status": "succeeded",
                "execution_mode": "tool",
                "final_response": {
                    "summary": "查询完成",
                    "outputs": {
                        "query": {
                            "result": {
                                "records": [
                                    {"id": "row-1", "applyNo": "CGSQ01"},
                                    {"id": "row-2"},
                                ]
                            }
                        }
                    },
                },
            }
        ),
    )

    run = service.create_task_run(CreateTaskRunRequest(user_request="查询业务记录"))

    assert run["available_actions"] == [
        {
            "action_id": "create-follow-up",
            "label": "创建跟进任务",
            "record_id": "row-1",
            "skill_id": str(skill.skill_id),
            "skill_version": 1,
            "confirmation": "required",
        }
    ]


def test_service_executes_server_issued_action_with_generic_context(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = action_skill()
    repository.save_candidate_skill(skill)
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "status": "succeeded",
            "final_response": {
                "outputs": {
                    "query": {
                        "result": {
                            "records": [{"id": "row-1", "applyNo": "CGSQ01"}]
                        }
                    }
                }
            },
        },
    )
    execution = SequenceGraph(
        {
            "status": "succeeded",
            "execution_mode": "tool",
            "final_response": {
                "summary": "明细读取完成",
                "outputs": {"detail": {"result": {"records": [{"code": "M1"}]}}},
                "tool_evidence": [],
            },
        },
        {
            "status": "succeeded",
            "execution_mode": "skill",
            "final_response": {"summary": "动作完成", "outputs": {}},
        },
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )

    result = service.execute_task_action(parent_run_id, "create-follow-up", "row-1")

    assert result["status"] == "succeeded"
    assert result["action_id"] == "create-follow-up"
    assert execution.states[0]["task_context"]["selected_record"]["id"] == "row-1"
    action_context = execution.states[1]["task_context"]
    assert action_context["required_skill_id"] == str(skill.skill_id)
    assert action_context["source_reference"] == "CGSQ01"
    assert action_context["action_context_outputs"]["detail"]["result"]["records"]


def test_service_creates_persisted_detail_run_from_saved_list_record(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
                "run_id": str(parent_run_id),
                "status": "succeeded",
            "user_request": "查询采购申请列表",
            "status": "succeeded",
            "final_response": {
                "outputs": {
                    "query": {
                        "result": {
                            "records": [
                                {
                                    "id": "2037430718812770305",
                                    "applyNo": "10",
                                    "applyBy": "孟明佳",
                                }
                            ]
                        }
                    }
                }
            },
        },
    )
    execution = Graph(
        {
            "status": "succeeded",
            "execution_mode": "tool",
            "final_response": {"summary": "采购申请详情查询完成"},
        }
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )

    detail = service.create_task_detail_run(
        parent_run_id,
        "2037430718812770305",
    )

    assert detail["run_id"] != str(parent_run_id)
    assert detail["parent_run_id"] == str(parent_run_id)
    assert detail["status"] == "succeeded"
    assert execution.state == {
        "user_request": "查看所选采购申请详情",
        "task_context": {
            "selected_record": {
                "id": "2037430718812770305",
                "applyNo": "10",
                "applyBy": "孟明佳",
            }
        },
    }
    assert repository.get_task_run(detail["run_id"])["parent_run_id"] == str(
        parent_run_id
    )


def test_service_rejects_detail_record_not_present_in_saved_result(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "user_request": "查询采购申请列表",
            "status": "succeeded",
            "final_response": {
                "outputs": {"query": {"result": {"records": [{"id": "row-1"}]}}}
            },
        },
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
    )

    with pytest.raises(KeyError, match="record"):
        service.create_task_detail_run(parent_run_id, "row-other")


def test_service_creates_purchase_progress_run_from_saved_record(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    parent_run_id = uuid4()
    selected_record = {
        "id": "application-1",
        "applyNo": "CGSQ01",
        "applyBy": "孟明佳",
    }
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "user_request": "查询孟明佳的采购申请",
            "status": "succeeded",
            "final_response": {
                "outputs": {"query": {"result": {"records": [selected_record]}}}
            },
        },
    )
    tracking = Graph(
        {
            "status": "succeeded",
            "final_response": {
                "summary": "采购链路已追踪",
                "progress": {"status": "complete", "stages": []},
            },
        }
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        purchase_tracking_graph_factory=lambda: tracking,
    )

    progress = service.create_purchase_progress_run(
        parent_run_id,
        "application-1",
    )

    assert tracking.state == {"selected_application": selected_record}
    assert progress["parent_run_id"] == str(parent_run_id)
    assert progress["run_id"] != str(parent_run_id)
    assert repository.get_task_run(progress["run_id"])["status"] == "succeeded"


def test_service_creates_purchase_follow_up_from_trusted_saved_record(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    execution = SequenceGraph(
        {
            "status": "succeeded",
            "execution_mode": "tool",
            "final_response": {
                "summary": "已读取详情",
                "outputs": {
                    "detail": {
                        "result": {
                            "records": [
                                {
                                    "articleNo": "M-1",
                                    "purchaseNumber": 2,
                                    "unit": "PCS",
                                }
                            ]
                        }
                    }
                },
                "tool_evidence": [{"tool_id": "mes:detail"}],
            },
        },
        {"status": "succeeded", "final_response": {"summary": "已创建跟进任务"}},
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "status": "succeeded",
            "user_request": "查询采购申请",
            "final_response": {"outputs": {"query": {"records": [{"id": "row-1", "applyNo": "CGSQ01"}]}}},
        },
    )

    result = service.create_purchase_follow_up_run(
        parent_run_id, "row-1", "为这条申请创建采购跟进任务"
    )

    assert result["status"] == "succeeded"
    assert result["selected_record_id"] == "row-1"
    assert execution.states[0]["task_context"]["selected_record"]["applyNo"] == "CGSQ01"
    follow_up_context = execution.states[1]["task_context"]
    assert follow_up_context["selected_record"]["applyNo"] == "CGSQ01"
    assert follow_up_context["mes_detail_outputs"]["detail"]["result"]["records"][0][
        "articleNo"
    ] == "M-1"
    assert follow_up_context["record_purpose"] == "formal"
    assert follow_up_context["source_reference"] == "CGSQ01"
    assert result["preparation"]["tool_evidence"] == [{"tool_id": "mes:detail"}]


def test_service_stops_follow_up_when_readonly_mes_detail_preparation_fails(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    execution = SequenceGraph(
        {"status": "failed", "execution_mode": "tool", "errors": ["detail failed"]}
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "status": "succeeded",
            "final_response": {
                "outputs": {"query": {"records": [{"id": "row-1"}]}}
            },
        },
    )

    result = service.create_purchase_follow_up_run(
        parent_run_id, "row-1", "create follow-up"
    )

    assert result["status"] == "failed"
    assert result["errors"] == ["无法读取所选采购申请的详情和物料明细"]
    assert len(execution.states) == 1


def test_service_retries_empty_detail_with_agent_feedback_before_follow_up(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    execution = SequenceGraph(
        {
            "status": "succeeded",
            "execution_mode": "tool",
            "final_response": {
                "summary": "empty detail",
                "outputs": {"detail": {"result": {"records": []}}},
            },
        },
        {
            "status": "succeeded",
            "execution_mode": "tool",
            "final_response": {
                "summary": "detail found",
                "outputs": {
                    "detail": {
                        "result": {
                            "records": [
                                {
                                    "articleNo": "M-1",
                                    "purchaseNumber": 2,
                                    "unit": "PCS",
                                }
                            ]
                        }
                    }
                },
            },
        },
        {"status": "succeeded", "final_response": {"summary": "created"}},
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "status": "succeeded",
            "final_response": {
                "outputs": {
                    "query": {
                        "records": [{"id": "row-1", "applyNo": "CGSQ01"}]
                    }
                }
            },
        },
    )

    result = service.create_purchase_follow_up_run(
        parent_run_id, "row-1", "create follow-up"
    )

    assert result["status"] == "succeeded"
    assert len(execution.states) == 3
    retry_context = execution.states[1]["task_context"]
    assert retry_context["selected_record"]["id"] == "row-1"
    assert retry_context["prior_detail_attempt"]["outputs"]["detail"]["result"][
        "records"
    ] == []


def test_service_rejects_purchase_follow_up_record_not_in_parent_output(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository, recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
    )
    parent_run_id = uuid4()
    repository.save_task_run(parent_run_id, {"run_id": str(parent_run_id), "status": "succeeded", "final_response": {"outputs": []}})

    with pytest.raises(KeyError, match="saved task result"):
        service.create_purchase_follow_up_run(parent_run_id, "forged", "创建跟进任务")


def test_service_rejects_progress_record_not_present_in_saved_result(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    parent_run_id = uuid4()
    repository.save_task_run(
        parent_run_id,
        {
            "run_id": str(parent_run_id),
            "user_request": "查询采购申请",
            "status": "succeeded",
            "final_response": {
                "outputs": {"query": {"result": {"records": [{"id": "row-1"}]}}}
            },
        },
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        purchase_tracking_graph_factory=lambda: Graph({"status": "succeeded"}),
    )

    with pytest.raises(KeyError, match="record"):
        service.create_purchase_progress_run(parent_run_id, "row-other")


def test_direct_tool_and_detail_runs_do_not_persist_skills(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    execution = Graph(
        {
            "status": "succeeded",
            "execution_mode": "tool",
            "final_response": {
                "summary": "只读查询完成",
                "outputs": {
                    "query": {"result": {"records": [{"id": "row-1"}]}}
                },
            },
        }
    )
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=execution,
    )
    before = (
        repository.list_published_skills(),
        repository.list_verified_candidates(),
    )

    parent = service.create_task_run(CreateTaskRunRequest(user_request="查询采购申请"))
    service.create_task_detail_run(parent["run_id"], "row-1")

    assert (
        repository.list_published_skills(),
        repository.list_verified_candidates(),
    ) == before


def test_service_persists_safe_extension_upload_failure(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    extension = AbortableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording["status"] = "recording"
    repository.save_recording(created["recording_id"], recording)
    issues = [{"location": "events.0.query_parameter_names.0", "type": "string_pattern_mismatch"}]

    failed = service.fail_extension_recording(
        created["recording_id"], "valid-token", issues
    )

    assert failed["status"] == "upload_failed"
    assert failed["failure_stage"] == "upload"
    assert failed["validation_issues"] == issues
    assert extension.aborted is not None
    assert repository.get_recording(created["recording_id"]) == failed


def test_service_aborts_extension_capture_with_fixed_safe_reason(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    extension = AbortableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording["status"] = "recording"
    repository.save_recording(created["recording_id"], recording)

    failed = service.abort_extension_recording(
        created["recording_id"], "valid-token", "no_uploadable_evidence"
    )

    assert failed["status"] == "upload_failed"
    assert failed["failure_stage"] == "upload"
    assert failed["failure_reasons"] == ["浏览器未采集到可用证据，请重新录制。"]
    assert extension.aborted is not None


def test_service_rejects_unauthorized_extension_abort_without_state_change(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=AbortableExtension(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording["status"] = "recording"
    repository.save_recording(created["recording_id"], recording)

    with pytest.raises(PermissionError):
        service.abort_extension_recording(
            created["recording_id"], "wrong-token", "upload_failed"
        )

    assert repository.get_recording(created["recording_id"])["status"] == "recording"


def test_service_lists_only_safe_recent_recording_fields(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    assert created["created_at"]
    assert created["updated_at"]
    stored = repository.get_recording(created["recording_id"])
    stored["trace"] = {"secret_marker": "must-not-leak"}
    stored["learning_result"] = {"private": "must-not-leak"}
    repository.save_recording(created["recording_id"], stored)

    listed = service.list_recordings(capture_source="browser_extension", limit=1)

    assert len(listed) == 1
    assert set(listed[0]) == {
        "recording_id",
        "status",
        "objective",
        "source_system",
        "source_systems",
        "recording_mode",
        "capture_source",
        "created_at",
        "updated_at",
            "failure_reasons",
            "analysis_stage",
        }
    assert "must-not-leak" not in str(listed)


def test_service_extension_recording_never_persists_token_or_credential(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    profile = SystemProfile(
        system_code="mes",
        display_name="MES",
        allowed_hosts={"mes.example.test"},
        openapi_url="https://mes.example.test/api-docs",
        base_url="https://mes.example.test",
        api_path_prefix="/api",
        credential_header="X-Access-Token",
        limits=ProfileLimits(
            request_timeout_seconds=10,
            max_response_bytes=1000,
            max_requests_per_minute=10,
        ),
        value_capture_policy="fingerprint_by_default",
        sensitive_field_patterns=["(?i)token"],
        tool_permissions=[
            ToolPermission(method="GET", path="/api/orders", side_effect="read")
        ],
    )
    catalog = ToolCatalog(
        [
            ToolDefinition(
                tool_id="mes:listOrders",
                system_code="mes",
                operation_id="listOrders",
                method="GET",
                base_url="https://mes.example.test",
                path_template="/api/orders",
                content_type=None,
                side_effect="read",
            )
        ]
    )
    extension = ExtensionRecorder(catalog)
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        system_profiles={"mes": profile},
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    started = service.start_extension_recording(created["recording_id"])
    recording_id = created["recording_id"]
    token = started["recording_token"]
    fingerprint = "hmac-sha256:" + "a" * 64
    service.ingest_extension_events(
        recording_id,
        ExtensionEventBatch.model_validate(
            {
                "batch_id": str(uuid4()),
                "recording_id": recording_id,
                "events": [
                    {
                        "event_id": str(uuid4()),
                        "client_sequence": 1,
                        "occurred_at": datetime.now(UTC),
                        "event_type": "click",
                        "page": {
                            "origin": "https://mes.example.test",
                            "path": "/orders",
                            "fingerprint": fingerprint,
                        },
                    }
                ],
            }
        ),
        token,
    )
    service.put_extension_credential(
        recording_id,
        "X-Access-Token",
        SecretStr("raw-private-token"),
        token,
    )
    stopped = service.stop_extension_recording(recording_id, token)
    persisted = repository.get_recording(recording_id)

    assert stopped["status"] == "recorded"
    assert persisted["trace"]["capture_source"] == "browser_extension"
    assert "raw-private-token" not in str(persisted)
    assert token not in str(persisted)


def test_extension_analysis_queue_returns_before_learning_finishes(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    started = Event()
    release = Event()

    class BlockingGraph:
        def invoke(self, state):
            started.set()
            assert release.wait(timeout=5)
            return {"final_status": "verified_candidate"}

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            self.cleared = recording_id

    extension = ClearableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        learning_graph_factory=lambda _system_code, _recording_id: BlockingGraph(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update({"status": "recorded", "trace": {"ui_events": []}})
    repository.save_recording(created["recording_id"], recording)

    queued = service.enqueue_extension_analysis(created["recording_id"])

    assert queued["status"] == "analyzing"
    assert started.wait(timeout=2)
    assert repository.get_recording(created["recording_id"])["status"] == "analyzing"
    release.set()
    deadline = monotonic() + 3
    while monotonic() < deadline:
        current = repository.get_recording(created["recording_id"])
        if current["status"] == "verified_candidate":
            break
        sleep(0.01)
    assert current["analysis_stage"] == "completed"
    assert extension.cleared is not None


def test_ui_only_trace_becomes_browser_candidate_without_api_verification(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class BrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            self.origins = allowed_origins
            return {
                "name": "查询订单",
                "execution_mode": "browser",
                "status": "candidate",
                "source_recording_id": trace["recording_id"],
                "steps": [{"action": "click"}],
            }

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            self.cleared = recording_id

    distiller = BrowserDistiller()
    extension = ClearableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        learning_graph_factory=lambda _system_code, _recording_id: FailingGraph(),
        browser_skill_distiller=distiller,
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "failure_stage": "system",
            "failure_reasons": ["旧的系统失败"],
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/orders",
                    }
                ],
                "api_exchanges": [],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "browser_candidate"
    assert result["analysis_stage"] == "awaiting_browser_verification"
    assert "failure_stage" not in result
    assert "failure_reasons" not in result
    assert result["learning_result"]["execution_mode"] == "browser"
    assert result["learning_result"]["verification_status"] == "pending_isolated_browser"
    assert distiller.origins == ["https://mes.example.test"]
    assert extension.cleared is not None


def test_api_candidate_does_not_fall_back_to_browser_execution(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class BrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            raise AssertionError("API candidate must not enter the browser path")

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            self.cleared = recording_id

    api_candidate = {
        "final_status": "api_candidate",
        "execution_verification": "pending_system_connection",
        "candidate_skill": {
            "name": "查询采购申请",
            "execution_mode": "api",
            "status": "candidate",
            "steps": [{"tool_id": "mes:query_purchase_requests"}],
        },
    }
    extension = ClearableExtension()
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=extension,
        learning_graph_factory=lambda _system_code, _recording_id: Graph(
            api_candidate
        ),
        browser_skill_distiller=BrowserDistiller(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询采购申请",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/purchase",
                    }
                ],
                "api_exchanges": [{"exchange_id": str(uuid4())}],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "api_candidate"
    assert result["analysis_stage"] == "completed"
    assert result["learning_result"] == api_candidate
    assert "api_learning_result" not in result
    assert extension.cleared is not None


def test_api_rejection_with_matched_exchanges_stays_on_the_api_learning_path(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class BrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            raise AssertionError("matched API evidence must not enter the browser path")

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            pass

    api_rejection = {
        "final_status": "rejected",
        "failure_stage": "analysis",
        "failure_reasons": ["无法确认主业务 API。"],
    }
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=ClearableExtension(),
        learning_graph_factory=lambda _system_code, _recording_id: Graph(api_rejection),
        browser_skill_distiller=BrowserDistiller(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/orders",
                    }
                ],
                "api_exchanges": [{"exchange_id": str(uuid4())}],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "rejected"
    assert result["analysis_stage"] == "completed"
    assert result["learning_result"] == api_rejection
    assert result["failure_reasons"] == ["无法确认主业务 API。"]
    assert "api_learning_result" not in result


def test_api_rejection_reason_is_returned_without_browser_fallback(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")

    class CrashingBrowserDistiller:
        def compile_browser_skill(self, trace, allowed_origins):
            raise RuntimeError("private model provider response")

    class ClearableExtension:
        def clear_credentials(self, recording_id):
            pass

    api_rejection = {
        "final_status": "rejected",
        "failure_stage": "analysis",
        "failure_reasons": ["字段对应关系证据不足"],
    }
    service = CommandCenterService(
        repository=repository,
        recorder=Recorder(),
        learning_graph=Graph({"final_status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        extension_recorder=ClearableExtension(),
        learning_graph_factory=lambda _system_code, _recording_id: Graph(api_rejection),
        browser_skill_distiller=CrashingBrowserDistiller(),
    )
    created = service.create_recording(
        CreateRecordingRequest(
            objective="查询订单",
            source_system="mes",
            source_task_id="manual-demo",
            capture_source="browser_extension",
        )
    )
    recording = repository.get_recording(created["recording_id"])
    recording.update(
        {
            "status": "recorded",
            "trace": {
                "recording_id": created["recording_id"],
                "ui_events": [
                    {
                        "event_id": str(uuid4()),
                        "action_type": "click",
                        "page_url": "https://mes.example.test/orders",
                    }
                ],
                "api_exchanges": [{"exchange_id": str(uuid4())}],
            },
        }
    )
    repository.save_recording(created["recording_id"], recording)

    result = service.analyze_extension_recording(created["recording_id"])

    assert result["status"] == "rejected"
    assert result["analysis_stage"] == "completed"
    assert result["failure_reasons"] == ["字段对应关系证据不足"]
    assert "private model provider response" not in str(result)


def test_command_center_service_delegates_task_session_operations(tmp_path):
    class TaskSessions:
        def create(self, request):
            self.created = request
            return "created"

        def get(self, session_id):
            self.got = session_id
            return "loaded"

        def resume_pending(self):
            return [uuid4()]

    task_sessions = TaskSessions()
    service = CommandCenterService(
        repository=CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}"),
        recorder=Recorder(),
        learning_graph=Graph({"status": "published"}),
        execution_graph=Graph({"status": "succeeded"}),
        task_session_service=task_sessions,
    )
    request = object()
    session_id = uuid4()

    assert service.create_task_session(request) == "created"
    assert service.get_task_session(session_id) == "loaded"
    assert service.resume_pending_task_sessions()
    assert task_sessions.created is request
    assert task_sessions.got == session_id
