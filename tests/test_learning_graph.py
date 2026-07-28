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


class FakeTester:
    def __init__(self, failing_category=None):
        self.failing_category = failing_category

    def run(self, skill, case):
        status = "failed" if case["category"] == self.failing_category else "passed"
        return {
            "category": case["category"],
            "status": status,
            "unknown_side_effect": False,
        }


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
    assert repository.list_published_skills() == []
