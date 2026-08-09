from pydantic import SecretStr
import pytest

from app.command_center.system_connections import (
    ConnectionHandshakeStore,
    KeyringSystemCredentialStore,
)
from app.command_center.system_profiles import (
    ProfileLimits,
    SystemProfile,
    ToolPermission,
)


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, account, secret):
        self.values[(service, account)] = secret

    def get_password(self, service, account):
        return self.values.get((service, account))

    def delete_password(self, service, account):
        if (service, account) not in self.values:
            raise RuntimeError('credential not found')
        del self.values[(service, account)]


def mes_profile():
    return SystemProfile(
        system_code='yifeng_mes',
        display_name='益丰 MES',
        allowed_hosts={'yifeng.dtsum.com'},
        openapi_url='http://yifeng.dtsum.com/jeecg-boot/v2/api-docs',
        base_url='http://yifeng.dtsum.com',
        api_path_prefix='/jeecg-boot/',
        credential_header='X-Access-Token',
        limits=ProfileLimits(
            request_timeout_seconds=10,
            max_response_bytes=1024,
            max_requests_per_minute=30,
        ),
        value_capture_policy='fingerprint_by_default',
        sensitive_field_patterns=[],
        tool_permissions=[
            ToolPermission(
                method='GET',
                path='/jeecg-boot/purchase/apply/list',
                side_effect='read',
            )
        ],
    )


def test_keyring_store_round_trips_overwrites_and_deletes_without_repr_leak():
    backend = FakeKeyring()
    store = KeyringSystemCredentialStore({'yifeng_mes': mes_profile()}, backend)

    store.put('yifeng_mes', 'X-Access-Token', SecretStr('first-private-value'))
    store.put('yifeng_mes', 'x-access-token', SecretStr('second-private-value'))

    assert store.headers_for('yifeng_mes') == {
        'X-Access-Token': 'second-private-value'
    }
    assert store.has('yifeng_mes') is True
    assert 'second-private-value' not in repr(store)

    store.delete('yifeng_mes')
    assert store.headers_for('yifeng_mes') == {}
    assert store.has('yifeng_mes') is False


def test_keyring_store_rejects_unknown_system_and_wrong_header():
    store = KeyringSystemCredentialStore({'yifeng_mes': mes_profile()}, FakeKeyring())

    with pytest.raises(KeyError):
        store.put('unknown', 'X-Access-Token', SecretStr('private'))
    with pytest.raises(ValueError, match='credential header'):
        store.put('yifeng_mes', 'Authorization', SecretStr('private'))


def test_connection_handshake_requires_matching_random_token():
    handshakes = ConnectionHandshakeStore()
    token = handshakes.begin('yifeng_mes')

    assert handshakes.authorize('yifeng_mes', token) is True
    assert handshakes.authorize('yifeng_mes', 'wrong') is False
    assert token not in repr(handshakes)

    handshakes.clear('yifeng_mes')
    assert handshakes.authorize('yifeng_mes', token) is False
