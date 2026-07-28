from uuid import uuid4

import pytest

from app.command_center.repository import (
    CommandCenterRepository,
    ImmutableSkillError,
    PublishGateError,
)
from app.command_center.schemas import SkillDefinition
from tests.test_command_center_schemas import valid_skill_payload


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
