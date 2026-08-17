from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.command_center.task_session_schemas import (
    ConfirmationInteraction,
    NextInteraction,
    QuestionInteraction,
    TaskSessionSnapshot,
)


def _principal() -> dict[str, object]:
    return {
        "subject_id": "local-user",
        "tenant_id": "local",
        "permissions": ["command-center:*"],
    }


def test_next_interaction_is_discriminated_by_type():
    value = TypeAdapter(NextInteraction).validate_python(
        {
            "type": "question",
            "prompt": "请输入报销金额",
            "field_names": ["amount"],
        }
    )

    assert isinstance(value, QuestionInteraction)


def test_confirmation_requires_plan_identity():
    with pytest.raises(ValidationError):
        ConfirmationInteraction.model_validate(
            {
                "type": "confirmation",
                "title": "确认提交",
                "summary": "创建一条报销记录",
                "plan_revision": 1,
            }
        )


def test_session_rejects_interaction_that_does_not_match_state():
    with pytest.raises(ValidationError, match="interaction"):
        TaskSessionSnapshot.model_validate(
            {
                "session_id": str(uuid4()),
                "state": "awaiting_confirmation",
                "version": 1,
                "goal": "创建报销记录",
                "principal": _principal(),
                "next_interaction": {
                    "type": "question",
                    "prompt": "金额是多少",
                    "field_names": ["amount"],
                },
            }
        )


def test_create_request_rejects_client_supplied_principal():
    from app.command_center.task_session_schemas import CreateTaskSessionRequest

    with pytest.raises(ValidationError):
        CreateTaskSessionRequest.model_validate(
            {"goal": "删除记录", "principal": _principal()}
        )
