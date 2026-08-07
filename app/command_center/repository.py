from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.command_center.database import Base, build_session_factory
from app.command_center.models import (
    RecordingRow,
    SkillTestRow,
    SkillVersionRow,
    TaskRunRow,
)
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
            row = session.scalar(
                select(SkillTestRow).where(
                    SkillTestRow.skill_id == str(skill_id),
                    SkillTestRow.skill_version == version,
                    SkillTestRow.category == category,
                )
            )
            payload_json = json.dumps(payload, ensure_ascii=False)
            if row:
                row.status = status
                row.payload_json = payload_json
            else:
                session.add(
                    SkillTestRow(
                        skill_id=str(skill_id),
                        skill_version=version,
                        category=category,
                        status=status,
                        payload_json=payload_json,
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

    def mark_verified_candidate(
        self, skill_id: UUID, version: int
    ) -> SkillDefinition:
        with self.session_factory() as session:
            row = session.scalar(
                select(SkillVersionRow).where(
                    SkillVersionRow.skill_id == str(skill_id),
                    SkillVersionRow.version == version,
                )
            )
            if row is None:
                raise KeyError(f"Skill not found: {skill_id}:{version}")
            if row.status == "published":
                raise ImmutableSkillError("published Skill versions are immutable")
            results = session.scalars(
                select(SkillTestRow).where(
                    SkillTestRow.skill_id == str(skill_id),
                    SkillTestRow.skill_version == version,
                )
            ).all()
            passed = {result.category for result in results if result.status == "passed"}
            if passed != self.REQUIRED_TESTS:
                raise PublishGateError("all three required test categories must pass")
            skill = SkillDefinition.model_validate_json(row.payload_json).model_copy(
                update={"status": "verified_candidate", "published_at": None}
            )
            row.status = "verified_candidate"
            row.published_at = None
            row.payload_json = skill.model_dump_json()
            session.commit()
            return skill

    def list_verified_candidates(self) -> list[SkillDefinition]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(SkillVersionRow).where(
                    SkillVersionRow.status == "verified_candidate"
                )
            ).all()
            return [SkillDefinition.model_validate_json(row.payload_json) for row in rows]

    def get_skill(self, skill_id: UUID) -> SkillDefinition:
        with self.session_factory() as session:
            row = session.scalar(
                select(SkillVersionRow)
                .where(SkillVersionRow.skill_id == str(skill_id))
                .order_by(SkillVersionRow.version.desc())
            )
            if row is None:
                raise KeyError(f"Skill not found: {skill_id}")
            return SkillDefinition.model_validate_json(row.payload_json)

    def save_recording(
        self,
        recording_id: UUID,
        payload: dict[str, object],
    ) -> None:
        self._save_runtime_row(
            RecordingRow,
            "recording_id",
            str(recording_id),
            payload,
        )

    def get_recording(self, recording_id: UUID) -> dict[str, object]:
        return self._get_runtime_row(
            RecordingRow,
            RecordingRow.recording_id,
            str(recording_id),
        )

    def list_recordings(self) -> list[dict[str, object]]:
        with self.session_factory() as session:
            rows = session.scalars(select(RecordingRow)).all()
            return [json.loads(row.payload_json) for row in rows]

    def save_task_run(self, run_id: UUID, payload: dict[str, object]) -> None:
        self._save_runtime_row(TaskRunRow, "run_id", str(run_id), payload)

    def get_task_run(self, run_id: UUID) -> dict[str, object]:
        return self._get_runtime_row(TaskRunRow, TaskRunRow.run_id, str(run_id))

    def _save_runtime_row(
        self,
        row_type,
        id_name: str,
        identifier: str,
        payload: dict[str, object],
    ) -> None:
        with self.session_factory() as session:
            row = session.get(row_type, identifier)
            serialized = json.dumps(payload, ensure_ascii=False)
            if row is None:
                row = row_type(
                    **{
                        id_name: identifier,
                        "status": str(payload["status"]),
                        "payload_json": serialized,
                    }
                )
                session.add(row)
            else:
                row.status = str(payload["status"])
                row.payload_json = serialized
            session.commit()

    def _get_runtime_row(self, row_type, id_column, identifier: str) -> dict[str, object]:
        with self.session_factory() as session:
            row = session.scalar(select(row_type).where(id_column == identifier))
            if row is None:
                raise KeyError(identifier)
            return json.loads(row.payload_json)
