from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import SecretStr

from app.command_center.credential_vault import EphemeralCredentialVault
from app.command_center.recorder import OperationTraceBuilder
from app.command_center.schemas import (
    ExtensionEventBatch,
    OperationTrace,
    PageMutationEvidence,
    RecordedBrowserEvent,
    RecordedNetworkExchange,
    RedactionSummary,
)
from app.command_center.system_profiles import SystemProfile
from app.command_center.tool_catalog import ToolCatalog


@dataclass(frozen=True, repr=False)
class IngestGrant:
    recording_id: UUID
    token: str


@dataclass
class _ExtensionSession:
    builder: OperationTraceBuilder
    profile: SystemProfile
    token_digest: bytes
    batch_ids: set[UUID] = field(default_factory=set)
    last_client_sequence: int = 0


class ExtensionRecorder:
    """In-memory adapter for already-redacted browser-extension evidence."""

    def __init__(
        self,
        catalog: ToolCatalog | None = None,
        *,
        catalog_provider: Callable[[SystemProfile], ToolCatalog] | None = None,
        credential_vault: EphemeralCredentialVault | None = None,
    ) -> None:
        if catalog is None and catalog_provider is None:
            raise ValueError("a Tool catalog or catalog provider is required")
        self.catalog = catalog
        self.catalog_provider = catalog_provider
        self.credential_vault = credential_vault or EphemeralCredentialVault()
        self.sessions: dict[UUID, _ExtensionSession] = {}

    def start(
        self,
        recording_id: UUID,
        objective: str,
        source_task: dict[str, Any],
        profile: SystemProfile,
    ) -> IngestGrant:
        if recording_id in self.sessions:
            raise ValueError("extension recording is already active")
        try:
            catalog = (
                self.catalog_provider(profile)
                if self.catalog_provider is not None
                else self.catalog
            )
        except Exception as error:
            raise ValueError("system API catalog is temporarily unavailable") from error
        if catalog is None:
            raise ValueError("system API catalog is temporarily unavailable")
        token = secrets.token_urlsafe(32)
        self.sessions[recording_id] = _ExtensionSession(
            builder=OperationTraceBuilder(
                recording_id=recording_id,
                objective=objective,
                source_task=source_task,
                catalog=catalog,
                started_at=datetime.now(UTC),
                capture_source="browser_extension",
            ),
            profile=profile,
            token_digest=self._digest(token),
        )
        return IngestGrant(recording_id=recording_id, token=token)

    def ingest(
        self,
        recording_id: UUID,
        batch: ExtensionEventBatch,
        token: str,
    ) -> None:
        try:
            session = self._authorized_session(recording_id, token)
            batch = ExtensionEventBatch.model_validate(batch.model_dump(mode="python"))
            if batch.recording_id != recording_id:
                raise ValueError("recording batch does not match session")
            if batch.batch_id in session.batch_ids:
                raise ValueError("recording batch was already ingested")

            ordered: list[
                RecordedBrowserEvent | RecordedNetworkExchange | PageMutationEvidence
            ]
            ordered = sorted(
                [*batch.events, *batch.page_mutations],
                key=lambda item: item.client_sequence,
            )
            if ordered and ordered[0].client_sequence <= session.last_client_sequence:
                raise ValueError("recording client sequence conflicts with prior batch")
            self._validate_origins(session.profile, ordered)

            for item in ordered:
                if isinstance(item, RecordedBrowserEvent):
                    page_url = f"{item.page.origin}{item.page.path}"
                    target = item.control.model_dump(mode="json") if item.control else {}
                    target["page_fingerprint"] = item.page.fingerprint
                    session.builder.add_ui_event(
                        page_url=page_url,
                        action_type=item.event_type,
                        target=target,
                        value_ref=item.value_fingerprint,
                    )
                elif isinstance(item, RecordedNetworkExchange):
                    session.builder.add_api_exchange(
                        system_code=session.profile.system_code,
                        method=item.method,
                        path=item.path_template,
                        request_body={
                            "query_parameter_names": item.query_parameter_names,
                            "query_parameter_fingerprints": (
                                item.query_parameter_fingerprints
                            ),
                            "request_fingerprint": item.request_fingerprint,
                            "endpoint_fingerprint": item.endpoint_fingerprint,
                        },
                        response_status=item.response_status,
                        response_body={"response_fingerprint": item.response_fingerprint},
                        started_at=item.started_at,
                    )
                else:
                    session.builder.page_mutations.append(item)

            session.builder.redaction_summary = RedactionSummary(
                redacted_field_count=(
                    session.builder.redaction_summary.redacted_field_count
                    + batch.redaction_summary.redacted_field_count
                ),
                fingerprinted_value_count=(
                    session.builder.redaction_summary.fingerprinted_value_count
                    + batch.redaction_summary.fingerprinted_value_count
                ),
                dropped_evidence_count=(
                    session.builder.redaction_summary.dropped_evidence_count
                    + batch.redaction_summary.dropped_evidence_count
                ),
            )
            session.batch_ids.add(batch.batch_id)
            if ordered:
                session.last_client_sequence = ordered[-1].client_sequence
        except Exception:
            self.credential_vault.clear(recording_id)
            raise

    def put_credential(
        self,
        recording_id: UUID,
        name: str,
        secret: SecretStr,
        token: str,
    ) -> None:
        session = self._authorized_session(recording_id, token)
        credential_header = session.profile.credential_header
        if credential_header is None or name.casefold() != credential_header.casefold():
            self.credential_vault.clear(recording_id)
            raise ValueError("credential header is not allowed for this profile")
        self.credential_vault.put(recording_id, credential_header, secret)

    def stop(
        self,
        recording_id: UUID,
        token: str,
        *,
        retain_credentials: bool = False,
    ) -> OperationTrace:
        session = self._authorized_session(recording_id, token)
        try:
            trace = session.builder.finalize()
            if not retain_credentials:
                self.credential_vault.clear(recording_id)
            return trace
        except Exception:
            self.credential_vault.clear(recording_id)
            raise
        finally:
            self.sessions.pop(recording_id, None)

    def clear_credentials(self, recording_id: UUID) -> None:
        self.credential_vault.clear(recording_id)

    def abort(self, recording_id: UUID) -> None:
        self.sessions.pop(recording_id, None)
        self.credential_vault.clear(recording_id)

    def abort_authorized(self, recording_id: UUID, token: str) -> None:
        self._authorized_session(recording_id, token)
        self.sessions.pop(recording_id, None)
        self.credential_vault.clear(recording_id)

    def _authorized_session(self, recording_id: UUID, token: str) -> _ExtensionSession:
        session = self.sessions.get(recording_id)
        if session is None or not isinstance(token, str) or not hmac.compare_digest(
            session.token_digest,
            self._digest(token),
        ):
            self.credential_vault.clear(recording_id)
            raise PermissionError("extension recording authorization failed")
        return session

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    @staticmethod
    def _validate_origins(
        profile: SystemProfile,
        items: list[RecordedBrowserEvent | RecordedNetworkExchange | PageMutationEvidence],
    ) -> None:
        allowed = {host.casefold() for host in profile.allowed_hosts}
        for item in items:
            page = getattr(item, "page", None)
            if page is None:
                continue
            hostname = urlsplit(page.origin).hostname
            if hostname is None or hostname.casefold() not in allowed:
                raise ValueError("extension evidence origin is not allowed")
