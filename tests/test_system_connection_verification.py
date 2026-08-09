from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.command_center.repository import CommandCenterRepository
from app.command_center.schemas import SkillDefinition
from app.command_center.service import CommandCenterService


REQUIRED_CATEGORIES = ("normal", "parameter_variation", "idempotency")


def readonly_skill(*, name: str = "查询采购申请", side_effect: str = "read"):
    return SkillDefinition.model_validate(
        {
            "skill_id": str(uuid4()),
            "version": 1,
            "name": name,
            "description": "通过 MES 只读接口查询采购申请",
            "status": "candidate",
            "trigger_examples": [name],
            "source_recording_id": str(uuid4()),
            "inputs": [],
            "outputs": [],
            "steps": [
                {
                    "step_id": "query",
                    "name": "查询",
                    "tool_id": "yifeng_mes:list_purchase_apply",
                    "input_bindings": {},
                    "side_effect": side_effect,
                    **(
                        {"idempotency_key_template": "{skill_id}:{source_object_id}:{step_id}"}
                        if side_effect == "write"
                        else {}
                    ),
                }
            ],
            "success_conditions": [],
        }
    )


class ConnectedStore:
    def has(self, system_code):
        return system_code == "yifeng_mes"


class CapturingTester:
    def __init__(self, statuses=None):
        self.statuses = statuses or {}
        self.calls = []

    def run(self, skill, case):
        self.calls.append((skill, case))
        category = case["category"]
        status = self.statuses.get(category, "passed")
        return {
            "category": category,
            "status": status,
            "verification": {
                "status": status,
                "summary": "live read-only verification",
            },
            "unknown_side_effect": False,
            "step_results": [],
        }


def service_for(repository, tester):
    return CommandCenterService(
        repository=repository,
        recorder=object(),
        learning_graph=object(),
        execution_graph=object(),
        system_profiles={
            "yifeng_mes": SimpleNamespace(display_name="益丰 MES")
        },
        system_credential_store=ConnectedStore(),
        system_skill_tester_factory=lambda system_code: tester,
    )


def save_candidate_recording(repository, skill, *, created_at):
    repository.save_candidate_skill(skill)
    recording_id = uuid4()
    repository.save_recording(
        recording_id,
        {
            "recording_id": str(recording_id),
            "status": "api_candidate",
            "source_system": "yifeng_mes",
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "analysis_stage": "completed",
            "learning_result": {
                "candidate_skill": skill.model_dump(mode="json"),
                "test_plan": [{"category": category} for category in REQUIRED_CATEGORIES],
                "test_results": [],
                "final_status": "api_candidate",
                "execution_verification": "pending_system_connection",
            },
        },
    )
    return recording_id


def test_verification_selects_latest_candidate_and_marks_it_verified(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    older = readonly_skill(name="较早的查询")
    latest = readonly_skill(name="最新的查询")
    now = datetime.now(UTC)
    save_candidate_recording(repository, older, created_at=now - timedelta(minutes=1))
    latest_recording_id = save_candidate_recording(repository, latest, created_at=now)
    tester = CapturingTester()

    result = service_for(repository, tester).verify_latest_system_skill("yifeng_mes")

    assert result["status"] == "verified_candidate"
    assert result["recording_id"] == str(latest_recording_id)
    assert {case[1]["category"] for case in tester.calls} == set(REQUIRED_CATEGORIES)
    assert {case[0].skill_id for case in tester.calls} == {latest.skill_id}
    assert repository.list_verified_candidates()[0].skill_id == latest.skill_id
    stored = repository.get_recording(latest_recording_id)
    assert stored["learning_result"]["execution_verification"] == "verified_live"


def test_failed_live_verification_preserves_candidate(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = readonly_skill()
    recording_id = save_candidate_recording(
        repository, skill, created_at=datetime.now(UTC)
    )
    tester = CapturingTester({"parameter_variation": "failed"})

    result = service_for(repository, tester).verify_latest_system_skill("yifeng_mes")

    assert result["status"] == "api_candidate"
    assert repository.list_verified_candidates() == []
    assert repository.list_candidate_skills()[0].skill_id == skill.skill_id
    stored = repository.get_recording(recording_id)
    assert stored["learning_result"]["execution_verification"] == "failed_live"


def test_write_candidate_is_rejected_before_any_live_request(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = readonly_skill(side_effect="write")
    save_candidate_recording(repository, skill, created_at=datetime.now(UTC))
    tester = CapturingTester()

    with pytest.raises(ValueError, match="read-only"):
        service_for(repository, tester).verify_latest_system_skill("yifeng_mes")

    assert tester.calls == []
