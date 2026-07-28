from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.command_center.database import Base, build_session_factory
from app.command_center.models import SkillTestRow, SkillVersionRow
from app.command_center.schemas import SkillDefinition


class ImmutableSkillError(RuntimeError):
    pass


class PublishGateError(RuntimeError):
    pass


class CommandCenterRepository:
    REQUIRED_TESTS = {"normal", "parameter_variation", "idempotency"}

    def __init__(self, database_url: str):
        self.session_factory = build_session_factory(database_url)
        engine = self.session_factory.kw["bind"]
        Base.metadata.create_all(engine)

    def save_candidate_skill(self, skill: SkillDefinition) -> SkillDefinition:
        with self.session_factory() as session:
            row = session.scalar(
                select(SkillVersionRow).where(
                    SkillVersionRow.skill_id == str(skill.skill_id),
                    SkillVersionRow.version == skill.version,
                )
            )
            if row and row.status == "published":
                raise ImmutableSkillError("published Skill versions are immutable")
            payload = skill.model_dump_json()
            if row:
                row.status = skill.status
                row.payload_json = payload
            else:
                session.add(
                    SkillVersionRow(
                        skill_id=str(skill.skill_id),
                        version=skill.version,
                        status=skill.status,
                        payload_json=payload,
                    )
                )
            session.commit()
        return skill

    def save_test_result(
        self,
        skill_id: UUID,
        version: int,
        category: str,
        status: str,
        payload: dict[str, object],
    ) -> None:
        with self.session_factory() as session:
            session.add(
                SkillTestRow(
                    skill_id=str(skill_id),
                    skill_version=version,
                    category=category,
                    status=status,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
            )
            session.commit()

    def publish_skill(self, skill_id: UUID, version: int) -> SkillDefinition:
        with self.session_factory() as session:
            row = session.scalar(
                select(SkillVersionRow).where(
                    SkillVersionRow.skill_id == str(skill_id),
                    SkillVersionRow.version == version,
                )
            )
            if row is None:
                raise KeyError(f"Skill not found: {skill_id}:{version}")
            results = session.scalars(
                select(SkillTestRow).where(
                    SkillTestRow.skill_id == str(skill_id),
                    SkillTestRow.skill_version == version,
                )
            ).all()
            passed = {result.category for result in results if result.status == "passed"}
            if passed != self.REQUIRED_TESTS:
                raise PublishGateError("all three required test categories must pass")
            published_at = datetime.now(UTC)
            skill = SkillDefinition.model_validate_json(row.payload_json).model_copy(
                update={"status": "published", "published_at": published_at}
            )
            row.status = "published"
            row.published_at = published_at
            row.payload_json = skill.model_dump_json()
            session.commit()
            return skill

    def list_published_skills(self) -> list[SkillDefinition]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(SkillVersionRow).where(SkillVersionRow.status == "published")
            ).all()
            return [SkillDefinition.model_validate_json(row.payload_json) for row in rows]
