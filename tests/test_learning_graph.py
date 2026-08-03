from uuid import uuid4

from app.command_center.learning_graph import LearningDependencies, build_learning_graph
from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import SkillDefinition
from tests.test_command_center_schemas import valid_skill_payload


class FakeAgents:
    def analyze_demonstration(self, trace, catalog):
        return {"compilable": True, "summary": "创建采购并回写"}

    def compile_skill(self, analysis, trace, catalog):
        return SkillDefinition.model_validate(valid_skill_payload())

    def design_tests(self, skill):
        return [
            {"category": "normal"},
            {"category": "parameter_variation"},
            {"category": "idempotency"},
        ]


class RejectingAgents(FakeAgents):
    def analyze_demonstration(self, trace, catalog):
        return {
            "compilable": False,
            "summary": "实际调用了任务派发接口",
            "uncertainties": [
                {"description": "未观察到允许的创建采购申请接口"},
            ],
        }


class FakeTester:
    def __init__(self, failing_category=None):
        self.failing_category = failing_category

    def run(self, skill, case):
        status = "failed" if case["category"] == self.failing_category else "passed"
        return {
            "category": case["category"],
            "status": status,
            "verification": {
                "summary": (
                    "参数变化测试未通过"
                    if status == "failed"
                    else "测试通过"
                )
            },
            "unknown_side_effect": False,
        }


class StagedAgents:
    def __init__(self, *, mapping_compilable=True):
        self.calls = []
        self.mapping_compilable = mapping_compilable

    def segment_trace(self, trace):
        self.calls.append("segment_trace")
        return {"segments": [], "uncertainties": [], "conclusive": True}

    def attribute_apis(self, segmentation, trace, catalog):
        self.calls.append("attribute_apis")
        return {"segments": [], "uncertainties": [], "attributable": True}

    def map_fields(self, attribution, trace, catalog):
        self.calls.append("map_fields")
        return {
            "mappings": [],
            "uncertainties": (
                []
                if self.mapping_compilable
                else [{"description": "字段对应关系证据不足"}]
            ),
            "compilable": self.mapping_compilable,
        }

    def compile_skill(self, mapping, attribution, trace, catalog):
        self.calls.append("compile_skill")
        return SkillDefinition.model_validate(valid_skill_payload())

    def design_tests(self, skill):
        return [
            {"category": "normal"},
            {"category": "parameter_variation"},
            {"category": "idempotency"},
        ]


def test_learning_graph_auto_publishes_after_three_tests_pass(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    dependencies = LearningDependencies(
        repository=repository,
        agents=FakeAgents(),
        tester=FakeTester(),
        catalog={"version": "test"},
    )

    result = build_learning_graph(dependencies).invoke(
        {"recording_id": str(uuid4()), "trace": {"api_exchanges": []}}
    )

    assert result["final_status"] == "published"
    assert [item["category"] for item in result["test_results"]] == [
        "normal",
        "parameter_variation",
        "idempotency",
    ]
    assert len(repository.list_published_skills()) == 1


def test_learning_graph_rejects_failed_test_without_publishing(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    dependencies = LearningDependencies(
        repository=repository,
        agents=FakeAgents(),
        tester=FakeTester(failing_category="parameter_variation"),
        catalog={"version": "test"},
    )

    result = build_learning_graph(dependencies).invoke(
        {"recording_id": str(uuid4()), "trace": {"api_exchanges": []}}
    )

    assert result["final_status"] == "rejected"
    assert result["failure_stage"] == "testing"
    assert result["failure_reasons"] == ["参数变化测试未通过"]
    assert repository.list_published_skills() == []


def test_learning_graph_reports_analysis_rejection_before_testing(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    dependencies = LearningDependencies(
        repository=repository,
        agents=RejectingAgents(),
        tester=FakeTester(),
        catalog={"version": "test"},
    )

    result = build_learning_graph(dependencies).invoke(
        {"recording_id": str(uuid4()), "trace": {"api_exchanges": []}}
    )

    assert result["final_status"] == "rejected"
    assert result["failure_stage"] == "analysis"
    assert result["failure_reasons"] == ["未观察到允许的创建采购申请接口"]
    assert "candidate_skill" not in result
    assert "test_results" not in result


def test_learning_graph_runs_staged_agent_judgments_in_order(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    agents = StagedAgents()
    graph = build_learning_graph(
        LearningDependencies(repository, agents, FakeTester(), {"tools": []})
    )

    graph.invoke({"recording_id": str(uuid4()), "trace": {"api_exchanges": []}})

    assert agents.calls == [
        "segment_trace",
        "attribute_apis",
        "map_fields",
        "compile_skill",
    ]


def test_learning_graph_stops_on_inconclusive_field_mapping(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    agents = StagedAgents(mapping_compilable=False)
    graph = build_learning_graph(
        LearningDependencies(repository, agents, FakeTester(), {"tools": []})
    )

    result = graph.invoke(
        {"recording_id": str(uuid4()), "trace": {"api_exchanges": []}}
    )

    assert result["final_status"] == "rejected"
    assert result["failure_reasons"] == ["字段对应关系证据不足"]
    assert agents.calls == ["segment_trace", "attribute_apis", "map_fields"]
