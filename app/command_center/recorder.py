from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from app.command_center.schemas import (
    APIExchange,
    OperationTrace,
    PageMutationEvidence,
    RedactionSummary,
    UIEvent,
)
from app.command_center.tool_catalog import ToolCatalog


class OperationTraceBuilder:
    def __init__(
        self,
        *,
        recording_id: UUID,
        objective: str,
        source_task: dict[str, Any],
        catalog: ToolCatalog,
        started_at: datetime,
        capture_source: str = "playwright",
    ):
        self.recording_id = recording_id
        self.objective = objective
        self.source_task = source_task
        self.catalog = catalog
        self.started_at = started_at
        self.capture_source = capture_source
        self.ui_events: list[UIEvent] = []
        self.api_exchanges: list[APIExchange] = []
        self.page_mutations: list[PageMutationEvidence] = []
        self.redaction_summary = RedactionSummary()
        self.evidence_refs: list[str] = []
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def add_ui_event(
        self,
        *,
        page_url: str,
        action_type: str,
        target: dict[str, Any],
        value_ref: str | None = None,
        screenshot_ref: str | None = None,
    ) -> None:
        self.ui_events.append(
            UIEvent(
                event_id=uuid4(),
                sequence=self._next_sequence(),
                timestamp=datetime.now(UTC),
                page_url=page_url,
                action_type=action_type,
                target=target,
                value_ref=value_ref,
                screenshot_ref=screenshot_ref,
            )
        )

    def add_api_exchange(
        self,
        *,
        system_code: str,
        method: str,
        path: str,
        request_body: dict[str, Any],
        response_status: int,
        response_body: dict[str, Any],
        started_at: datetime | None = None,
    ) -> None:
        matched = self.catalog.match_exchange(system_code, method, path)
        self.api_exchanges.append(
            APIExchange(
                exchange_id=uuid4(),
                sequence=self._next_sequence(),
                started_at=started_at or datetime.now(UTC),
                completed_at=datetime.now(UTC),
                system_code=system_code,
                method=method,
                path=path,
                request_body=request_body,
                response_status=response_status,
                response_body=response_body,
                matched_tool_id=matched.tool_id if matched else None,
                match_status="matched" if matched else "not_allowed",
            )
        )

    def finalize(self) -> OperationTrace:
        return OperationTrace(
            trace_id=uuid4(),
            recording_id=self.recording_id,
            objective=self.objective,
            source_task=self.source_task,
            started_at=self.started_at,
            ended_at=datetime.now(UTC),
            ui_events=self.ui_events,
            api_exchanges=self.api_exchanges,
            evidence_refs=self.evidence_refs,
            capture_source=self.capture_source,
            page_mutations=self.page_mutations,
            redaction_summary=self.redaction_summary,
        )


@dataclass
class _LiveSession:
    builder: OperationTraceBuilder
    playwright: Any
    browser: Any
    context: Any
    pending: set[asyncio.Task[Any]] = field(default_factory=set)
    trace_path: Path | None = None


class RecorderService:
    SYSTEM_PORTS = {8101: "connected_system", 8102: "onboarding_system"}

    def __init__(self, catalog: ToolCatalog, evidence_dir: Path):
        self.catalog = catalog
        self.evidence_dir = evidence_dir
        self.sessions: dict[UUID, _LiveSession] = {}

    async def start(
        self,
        recording_id: UUID,
        objective: str,
        source_task: dict[str, Any],
        start_url: str,
    ) -> None:
        from playwright.async_api import async_playwright

        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        trace_path = self.evidence_dir / f"{recording_id}.zip"
        builder = OperationTraceBuilder(
            recording_id=recording_id,
            objective=objective,
            source_task=source_task,
            catalog=self.catalog,
            started_at=datetime.now(UTC),
        )
        session = _LiveSession(builder, playwright, browser, context, trace_path=trace_path)
        self.sessions[recording_id] = session

        async def record_ui(source: Any, payload: dict[str, Any]) -> None:
            builder.add_ui_event(
                page_url=source["page"].url,
                action_type=payload["action_type"],
                target=payload.get("target", {}),
                value_ref=payload.get("value_ref"),
            )

        await context.expose_binding("__ccRecordEvent", record_ui)
        await context.add_init_script(_CAPTURE_SCRIPT)
        await context.tracing.start(screenshots=True, snapshots=True, sources=False)

        def on_response(response: Any) -> None:
            task = asyncio.create_task(self._record_response(builder, response))
            session.pending.add(task)
            task.add_done_callback(session.pending.discard)

        context.on("response", on_response)
        page = await context.new_page()
        await page.goto(start_url)
        await context.new_page()
        await context.pages[-1].goto("http://127.0.0.1:8101")

    async def stop(self, recording_id: UUID) -> OperationTrace:
        session = self.sessions.pop(recording_id)
        if session.pending:
            await asyncio.gather(*session.pending, return_exceptions=True)
        await session.context.tracing.stop(path=session.trace_path)
        session.builder.evidence_refs.append(str(session.trace_path))
        await session.context.close()
        await session.browser.close()
        await session.playwright.stop()
        return session.builder.finalize()

    async def _record_response(self, builder: OperationTraceBuilder, response: Any) -> None:
        request = response.request
        parsed = urlparse(request.url)
        system_code = self.SYSTEM_PORTS.get(parsed.port or 0)
        if system_code is None or not parsed.path.startswith("/api/"):
            return
        try:
            request_body = request.post_data_json or {}
        except Exception:
            request_body = {"form": request.post_data or ""}
        try:
            response_body = await response.json()
        except Exception:
            response_body = {}
        builder.add_api_exchange(
            system_code=system_code,
            method=request.method,
            path=parsed.path,
            request_body=request_body if isinstance(request_body, dict) else {"value": request_body},
            response_status=response.status,
            response_body=response_body if isinstance(response_body, dict) else {"value": response_body},
        )


_CAPTURE_SCRIPT = """
(() => {
  const describe = (target) => ({
    tag: target.tagName?.toLowerCase() || '',
    role: target.getAttribute?.('role'),
    accessible_name: target.getAttribute?.('aria-label') || target.innerText?.trim().slice(0, 120),
    label: target.labels?.[0]?.innerText?.trim() || null,
    test_id: target.getAttribute?.('data-testid'),
  });
  for (const type of ['click', 'input', 'change', 'submit']) {
    document.addEventListener(type, (event) => {
      const target = event.target;
      window.__ccRecordEvent({
        action_type: type === 'change' ? 'select' : type,
        target: describe(target),
        value_ref: target?.type === 'password' ? null : target?.value,
      });
    }, true);
  }
})();
"""
