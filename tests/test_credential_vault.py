import json
import pickle
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.command_center.credential_vault import EphemeralCredentialVault


def test_ephemeral_credential_is_masked_and_cleared():
    vault = EphemeralCredentialVault()
    recording_id = uuid4()
    vault.put(recording_id, "X-Access-Token", SecretStr("secret"))

    assert vault.headers_for(recording_id) == {"X-Access-Token": "secret"}
    assert "secret" not in repr(vault)
    vault.clear(recording_id)
    assert vault.headers_for(recording_id) == {}


def test_headers_for_returns_a_fresh_dictionary():
    vault = EphemeralCredentialVault()
    recording_id = uuid4()
    vault.put(recording_id, "Authorization", SecretStr("Bearer secret"))

    first = vault.headers_for(recording_id)
    first["Authorization"] = "changed"

    assert vault.headers_for(recording_id) == {"Authorization": "Bearer secret"}


def test_vault_requires_secretstr_and_clears_recording_on_failed_put():
    vault = EphemeralCredentialVault()
    recording_id = uuid4()
    vault.put(recording_id, "Authorization", SecretStr("existing-secret"))

    with pytest.raises(TypeError) as error:
        vault.put(recording_id, "X-Access-Token", "new-secret")  # type: ignore[arg-type]

    assert "existing-secret" not in str(error.value)
    assert "new-secret" not in str(error.value)
    assert vault.headers_for(recording_id) == {}


def test_vault_repr_state_and_serialization_do_not_expose_secret():
    vault = EphemeralCredentialVault()
    recording_id = uuid4()
    vault.put(recording_id, "Cookie", SecretStr("private-cookie"))

    assert "private-cookie" not in repr(vault)
    assert "private-cookie" not in repr(vars(vault))
    with pytest.raises(TypeError) as pickle_error:
        pickle.dumps(vault)
    assert "private-cookie" not in str(pickle_error.value)
    with pytest.raises(TypeError) as json_error:
        json.dumps(vault)
    assert "private-cookie" not in str(json_error.value)
