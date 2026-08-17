from uuid import uuid4

import pytest

from app.command_center.repository import (
    CommandCenterRepository,
    ImmutableSkillError,
    PublishGateError,
    TaskSessionConflictError,
)
from app.command_center.schemas import SkillDefinition
from app.command_center.task_session_schemas import TaskSessionSnapshot
from tests.test_command_center_schemas import valid_skill_payload


def task_session_snapshot(*, state="executing", version=1):
    interaction = (
        {
            "type": "result",
            "status": "succeeded",
            "summary": "完成",
            "steps": [],
        }
        if state == "succeeded"
        else {"type": "message", "message": "处理中"}
    )
    return TaskSessionSnapshot.model_validate(
        {
            "session_id": str(uuid4()),
            "state": state,
            "version": version,
            "goal": "处理任务",
            "principal": {
                "subject_id": "local-user",
                "tenant_id": "local",
                "permissions": ["command-center:*"],
            },
            "next_interaction": interaction,
        }
    )


def test_repository_publishes_only_after_all_required_tests_pass(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = SkillDefinition.model_validate(valid_skill_payload())
    repository.save_candidate_skill(skill)

    with pytest.raises(PublishGateError):
        repository.publish_skill(skill.skill_id, skill.version)

    for category in ("normal", "parameter_variation", "idempotency"):
        repository.save_test_result(skill.skill_id, skill.version, category, "passed", {})

    published = repository.publish_skill(skill.skill_id, skill.version)
    assert published.status == "published"
    assert repository.list_published_skills()[0].skill_id == skill.skill_id


def test_repository_replaces_test_result_when_skill_is_reanalyzed(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = SkillDefinition.model_validate(valid_skill_payload())
    repository.save_candidate_skill(skill)

    repository.save_test_result(
        skill.skill_id,
        skill.version,
        "normal",
        "failed",
        {"summary": "first analysis"},
    )
    repository.save_test_result(
        skill.skill_id,
        skill.version,
        "normal",
        "passed",
        {"summary": "reanalyzed"},
    )

    for category in ("parameter_variation", "idempotency"):
        repository.save_test_result(skill.skill_id, skill.version, category, "passed", {})

    assert repository.publish_skill(skill.skill_id, skill.version).status == "published"


def test_published_skill_version_is_immutable(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = SkillDefinition.model_validate(valid_skill_payload())
    repository.save_candidate_skill(skill)
    for category in ("normal", "parameter_variation", "idempotency"):
        repository.save_test_result(skill.skill_id, skill.version, category, "passed", {})
    repository.publish_skill(skill.skill_id, skill.version)

    changed = skill.model_copy(update={"name": f"changed-{uuid4()}"})
    with pytest.raises(ImmutableSkillError):
        repository.save_candidate_skill(changed)


def test_repository_retains_verified_candidate_outside_published_registry(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    skill = SkillDefinition.model_validate(valid_skill_payload())
    repository.save_candidate_skill(skill)
    for category in ("normal", "parameter_variation", "idempotency"):
        repository.save_test_result(skill.skill_id, skill.version, category, "passed", {})

    verified = repository.mark_verified_candidate(skill.skill_id, skill.version)

    assert verified.status == "verified_candidate"
    assert repository.list_published_skills() == []
    assert repository.list_verified_candidates()[0].skill_id == skill.skill_id


def test_repository_lists_unverified_candidates_only(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    candidate = SkillDefinition.model_validate(valid_skill_payload())
    repository.save_candidate_skill(candidate)

    verified_payload = valid_skill_payload()
    verified = SkillDefinition.model_validate(verified_payload)
    repository.save_candidate_skill(verified)
    for category in ("normal", "parameter_variation", "idempotency"):
        repository.save_test_result(
            verified.skill_id, verified.version, category, "passed", {}
        )
    repository.mark_verified_candidate(verified.skill_id, verified.version)

    assert [skill.skill_id for skill in repository.list_candidate_skills()] == [
        candidate.skill_id
    ]


def test_repository_persists_recording_and_task_run_lifecycle(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    recording_id = uuid4()
    run_id = uuid4()

    repository.save_recording(
        recording_id,
        {
            "recording_id": str(recording_id),
            "status": "created",
            "objective": "演示采购回写",
        },
    )
    repository.save_recording(
        recording_id,
        {
            "recording_id": str(recording_id),
            "status": "published",
            "objective": "演示采购回写",
        },
    )
    repository.save_task_run(
        run_id,
        {
            "run_id": str(run_id),
            "status": "needs_object_selection",
            "user_request": "处理库存不足任务",
        },
    )

    assert repository.get_recording(recording_id)["status"] == "published"
    assert repository.get_task_run(run_id)["status"] == "needs_object_selection"


def test_repository_lists_recording_payloads(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    first = uuid4()
    second = uuid4()
    for recording_id, status in ((first, "recording"), (second, "upload_failed")):
        repository.save_recording(
            recording_id,
            {
                "recording_id": str(recording_id),
                "status": status,
                "objective": "查询订单",
            },
        )

    listed = repository.list_recordings()

    assert {item["recording_id"] for item in listed} == {str(first), str(second)}


def test_repository_compare_and_swaps_task_session(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    snapshot = task_session_snapshot(version=1)
    repository.create_task_session(snapshot)

    updated = snapshot.model_copy(update={"version": 2, "goal": "更新后的目标"})
    repository.update_task_session(updated, expected_version=1)

    assert repository.get_task_session(snapshot.session_id).version == 2
    with pytest.raises(TaskSessionConflictError):
        repository.update_task_session(
            updated.model_copy(update={"version": 3}),
            expected_version=1,
        )


def test_repository_rejects_duplicate_task_session(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    snapshot = task_session_snapshot()
    repository.create_task_session(snapshot)

    with pytest.raises(TaskSessionConflictError):
        repository.create_task_session(snapshot)


def test_repository_lists_only_requested_task_session_states(tmp_path):
    repository = CommandCenterRepository(f"sqlite:///{tmp_path / 'center.sqlite3'}")
    executing = task_session_snapshot(state="executing")
    repository.create_task_session(executing)
    repository.create_task_session(task_session_snapshot(state="succeeded"))

    rows = repository.list_task_sessions_by_state({"executing", "verifying"})

    assert [row.session_id for row in rows] == [executing.session_id]
