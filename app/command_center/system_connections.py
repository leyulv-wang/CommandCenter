from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from threading import RLock
from time import monotonic
from typing import Protocol

import keyring
from pydantic import SecretStr

from app.command_center.system_profiles import SystemProfile


class KeyringBackend(Protocol):
    def set_password(self, service: str, account: str, password: str) -> None: ...
    def get_password(self, service: str, account: str) -> str | None: ...
    def delete_password(self, service: str, account: str) -> None: ...


class SystemCredentialStore(Protocol):
    def put(self, system_code: str, header: str, secret: SecretStr) -> None: ...
    def headers_for(self, system_code: str) -> dict[str, str]: ...
    def delete(self, system_code: str) -> None: ...
    def has(self, system_code: str) -> bool: ...


class KeyringSystemCredentialStore:
    SERVICE_NAME = "CommandCenter"

    def __init__(
        self,
        profiles: Mapping[str, SystemProfile],
        backend: KeyringBackend = keyring,
    ) -> None:
        self._profiles = profiles
        self._backend = backend

    def put(self, system_code: str, header: str, secret: SecretStr) -> None:
        profile = self._profile(system_code)
        expected = profile.credential_header
        if expected is None or header.casefold() != expected.casefold():
            raise ValueError("credential header is not allowed for this profile")
        value = secret.get_secret_value()
        if not value or "\r" in value or "\n" in value:
            raise ValueError("credential must be a non-empty single-line value")
        self._backend.set_password(
            self.SERVICE_NAME,
            self._account(system_code, expected),
            value,
        )

    def headers_for(self, system_code: str) -> dict[str, str]:
        profile = self._profile(system_code)
        header = profile.credential_header
        if header is None:
            return {}
        value = self._backend.get_password(
            self.SERVICE_NAME,
            self._account(system_code, header),
        )
        return {header: value} if value else {}

    def delete(self, system_code: str) -> None:
        profile = self._profile(system_code)
        header = profile.credential_header
        if header is None:
            return
        account = self._account(system_code, header)
        if self._backend.get_password(self.SERVICE_NAME, account) is not None:
            self._backend.delete_password(self.SERVICE_NAME, account)

    def has(self, system_code: str) -> bool:
        return bool(self.headers_for(system_code))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(profiles={len(self._profiles)})"

    def _profile(self, system_code: str) -> SystemProfile:
        try:
            return self._profiles[system_code]
        except KeyError as exc:
            raise KeyError(f"unknown system profile: {system_code}") from exc

    @staticmethod
    def _account(system_code: str, header: str) -> str:
        return f"{system_code}:{header.casefold()}"


class ConnectionHandshakeStore:
    def __init__(self, *, lifetime_seconds: int = 300) -> None:
        if lifetime_seconds <= 0:
            raise ValueError("handshake lifetime must be positive")
        self._lifetime_seconds = lifetime_seconds
        self._digests: dict[str, tuple[str, float]] = {}
        self._lock = RLock()

    def begin(self, system_code: str) -> str:
        token = secrets.token_urlsafe(32)
        digest = self._digest(token)
        with self._lock:
            self._digests[system_code] = (
                digest,
                monotonic() + self._lifetime_seconds,
            )
        return token

    def authorize(self, system_code: str, token: str) -> bool:
        with self._lock:
            stored = self._digests.get(system_code)
            if stored is None:
                return False
            digest, expires_at = stored
            if monotonic() > expires_at:
                self._digests.pop(system_code, None)
                return False
        return hmac.compare_digest(digest, self._digest(token))

    def clear(self, system_code: str) -> None:
        with self._lock:
            self._digests.pop(system_code, None)

    def __repr__(self) -> str:
        with self._lock:
            count = len(self._digests)
        return f"{type(self).__name__}(handshakes={count})"

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
