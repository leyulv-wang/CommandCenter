from __future__ import annotations

from threading import RLock
from uuid import UUID

from pydantic import SecretStr


class EphemeralCredentialVault:
    """Hold per-recording request credentials in memory until explicitly cleared."""

    def __init__(self) -> None:
        self._credentials: dict[UUID, dict[str, SecretStr]] = {}
        self._lock = RLock()

    def put(self, recording_id: UUID, header: str, secret: SecretStr) -> None:
        try:
            self._validate(recording_id, header, secret)
            with self._lock:
                credentials = self._credentials.setdefault(recording_id, {})
                for existing_header in tuple(credentials):
                    if existing_header.casefold() == header.casefold():
                        del credentials[existing_header]
                credentials[header] = secret
        except Exception:
            self.clear(recording_id)
            raise

    def headers_for(self, recording_id: UUID) -> dict[str, str]:
        try:
            with self._lock:
                credentials = self._credentials.get(recording_id, {})
                return {
                    header: secret.get_secret_value()
                    for header, secret in credentials.items()
                }
        except Exception:
            self.clear(recording_id)
            raise

    def clear(self, recording_id: UUID) -> None:
        with self._lock:
            self._credentials.pop(recording_id, None)

    def __repr__(self) -> str:
        with self._lock:
            recording_count = len(self._credentials)
        return f"{type(self).__name__}(recordings={recording_count})"

    def __getstate__(self) -> None:
        raise TypeError("EphemeralCredentialVault cannot be serialized")

    @staticmethod
    def _validate(recording_id: UUID, header: str, secret: SecretStr) -> None:
        if not isinstance(recording_id, UUID):
            raise TypeError("recording_id must be a UUID")
        if not isinstance(header, str) or not header or "\r" in header or "\n" in header:
            raise ValueError("header must be a non-empty HTTP header name")
        if type(secret) is not SecretStr:
            raise TypeError("secret must be a SecretStr")
