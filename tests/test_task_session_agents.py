from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.command_center.agents import AgentSuite
from app.command_center.schemas import SkillDefinition
from app.command_center.task_session_schemas import (
    ContextEvidence,
    ParameterSource,
)


SKILL_ID = UUID("33333333-3333-4333-8333-333333333333")


def _skill() -> SkillDefinition:
    return SkillDefinition.model_validate(
        {
            "skill_id": str(SKILL_ID),
            "version": 3,
            "name": "创建报销记录",
            "description": "为员工创建报销记录",
            "status": "published",
            "trigger_examples": ["提交报销"],
            "source_recording_id": str(uuid4()),
            "inputs": [
                {"name": "amount", "type": "number", "description": "金额"}
            ],
            "outputs": [],
            "steps": [
                {
                    "step_id": "create",
                    "name": "创建",
                    "tool_id": "finance:create",
                    "input_bindings": {"body.amount": "literal.amount"},
                    "side_effect": "write",
                    "idempotency_key_template": "{skill_id}:{step_id}",
                }
            ],
            "success_conditions": [],
        }
    )


class CapturingModel:
    def __init__(self, response):
        self.response = response
        self.payload = None
        self.prompt = None

    def generate(self, schema, system_prompt, payload):
        self.prompt = system_prompt
        self.payload = payload
        return schema.model_validate(self.response)


def test_intent_agent_receives_business_context_and_exact_skill_versions():
    model = CapturingModel(
        {
            "status": "matched",
            "skill_id": str(SKILL_ID),
            "skill_version": 3,
            "candidate_object_ids": ["expense-42"],
            "summary": "使用报销能力处理所选单据",
        }
    )

    result = AgentSuite(model).resolve_task_intent(
        goal="提交这张报销单",
        skills=[_skill()],
        object_candidates=[{"id": "expense-42", "title": "差旅报销"}],
    )

    assert result.skill_version == 3
    assert result.extracted_inputs == {}
    assert model.payload["object_candidates"][0]["id"] == "expense-42"
    assert model.payload["skills"][0]["version"] == 3


def test_intent_agent_cannot_select_unknown_skill():
    model = CapturingModel(
        {
            "status": "matched",
            "skill_id": str(uuid4()),
            "skill_version": 3,
            "summary": "invented",
        }
    )

    with pytest.raises(ValueError, match="available Skill"):
        AgentSuite(model).resolve_task_intent(
            goal="提交报销", skills=[_skill()], object_candidates=[]
        )


def test_plan_agent_must_cite_parameter_sources():
    model = CapturingModel(
        {
            "summary": "创建报销记录",
            "target_object_ids": ["expense-42"],
            "argument_sources": {
                "create.body.amount": {
                    "kind": "user_input",
                    "reference": "amount",
                }
            },
        }
    )

    proposal = AgentSuite(model).propose_task_plan(
        goal="创建报销记录",
        skill=_skill(),
        selected_object={"id": "expense-42"},
        inputs={"amount": 88},
        input_sources={
            "amount": ParameterSource(kind="user_input", reference="amount")
        },
        evidence=[],
    )

    assert proposal.argument_sources["create.body.amount"].reference == "amount"


def test_context_interpretation_rejects_invented_record_path():
    model = CapturingModel(
        {
            "candidates": [
                {
                    "object_id": "E-9",
                    "label": "员工 E-9",
                    "evidence_id": "context:employee",
                    "record_path": "records.9",
                }
            ],
            "summary": "找到员工",
        }
    )
    evidence = ContextEvidence(
        evidence_id="context:employee",
        tool_id="hr:list",
        arguments={},
        output={"records": [{"id": "E-9", "department": "研发"}]},
        observed_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="record path"):
        AgentSuite(model).interpret_task_context(
            goal="读取员工资料", skill=_skill(), evidence=[evidence]
        )
