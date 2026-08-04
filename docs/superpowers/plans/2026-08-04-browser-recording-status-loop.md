# Browser Recording Status Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a browser-extension MES demonstration reach a persisted terminal state and show its success or failure in the existing CommandCenter demonstration workbench.

**Architecture:** The extension continues to send already-redacted evidence. The FastAPI boundary validates the payload explicitly so it can safely terminate invalid sessions, persist `upload_failed`, and return validation locations without input values. A narrow recent-recordings projection feeds a minimal Vue status panel; no raw trace or credential crosses that read API.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, Vue 3, TypeScript, Vitest, Chromium Manifest V3, Node test runner.

## Global Constraints

- Intelligent agents retain responsibility for demonstration understanding, Tool alignment, Skill generation, and harmless-test judgment.
- Deterministic code handles only protocol validation, authorization, session cleanup, state persistence, bounded polling, and safe observability.
- Never persist or display Token, Cookie, request body, response body, form values, or validation input values.
- The real acceptance remains read-only on `http://yifeng.dtsum.com`.
- Do not touch unrelated untracked research or evidence files.

---

## File Map

- `app/command_center/extension_recorder.py`: authorize and terminate a failed extension session while clearing credentials.
- `app/command_center/service.py`: timestamp recording transitions, persist upload failure, and expose a safe recent-recording projection.
- `app/command_center/repository.py`: list persisted recording payloads for the service projection.
- `app/command_center/router.py`: validate extension payloads explicitly and expose `GET /recordings`.
- `browser_extension/background.mjs`: retain a terminal upload-failure result after stopping.
- `browser_extension/popup.mjs`: render upload failure clearly.
- `frontend/src/api/types.ts`: define extension recording statuses and safe summary type.
- `frontend/src/api/commandCenter.ts`: call the recent-recordings endpoint.
- `frontend/src/pages/DemonstrationWorkbenchPage.vue`: render and refresh the most recent extension result.
- Existing test files receive behavior-level regression coverage; no test-only production hooks are added.

### Task 1: Persist Safe Upload Failure as a Terminal State

**Files:**
- Modify: `app/command_center/extension_recorder.py`
- Modify: `app/command_center/service.py`
- Modify: `app/command_center/router.py`
- Test: `tests/test_extension_recorder.py`
- Test: `tests/test_command_center_service.py`
- Test: `tests/test_command_center_api.py`

**Interfaces:**
- Produces: `ExtensionRecorder.abort_authorized(recording_id: UUID, token: str) -> None`
- Produces: `CommandCenterService.fail_extension_recording(recording_id, token, issues) -> dict[str, Any]`
- The failure payload contains only `location` and `type` for each validation issue.

- [ ] **Step 1: Write failing authorization and cleanup tests**

Add tests proving an invalid token cannot abort a session and a valid token removes the session and credential-vault entry.

```python
with pytest.raises(PermissionError):
    recorder.abort_authorized(recording_id, "wrong-token")
assert recording_id in recorder.sessions

recorder.abort_authorized(recording_id, grant.token)
assert recording_id not in recorder.sessions
assert vault.headers_for(recording_id) == {}
```

- [ ] **Step 2: Run the recorder tests and observe the missing-method failure**

Run: `conda run -n langgraph python -m pytest tests/test_extension_recorder.py -q`

Expected: FAIL because `abort_authorized` does not exist.

- [ ] **Step 3: Implement authorized termination**

Use `_authorized_session(recording_id, token)` before removing the session and clearing the credential vault. Do not expose or compare credential values outside the vault.

- [ ] **Step 4: Write failing service and API tests**

Cover an invalid `ExtensionEventBatch` whose query parameter is `_t`. Assert:

```python
assert response.status_code == 422
assert response.json()["detail"] == {
    "code": "invalid_extension_evidence",
    "issues": [{"location": "events.0.RecordedNetworkExchange.query_parameter_names.0", "type": "string_pattern_mismatch"}],
}
recording = client.get(f"/recordings/{recording_id}").json()
assert recording["status"] == "upload_failed"
assert "_t" not in response.text
assert "input" not in response.text
```

Also assert a wrong recording token returns `401` and leaves the recording at `recording`.

- [ ] **Step 5: Run the focused API tests and observe the current automatic 422 behavior**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_api.py tests/test_command_center_service.py -q`

Expected: FAIL because FastAPI rejects the body before the service can persist a terminal state.

- [ ] **Step 6: Implement explicit safe validation**

Accept the route body as a JSON object, then call `ExtensionEventBatch.model_validate(payload)`. Convert `ValidationError.errors(include_url=False, include_context=False, include_input=False)` into this safe shape:

```python
{
    "location": ".".join(str(part) for part in error["loc"]),
    "type": error["type"],
}
```

On validation failure, call `fail_extension_recording`, return structured `422`, and never include `msg`, `ctx`, or `input`. On success, pass the validated model into the existing ingest path.

- [ ] **Step 7: Verify Task 1**

Run: `conda run -n langgraph python -m pytest tests/test_extension_recorder.py tests/test_command_center_service.py tests/test_command_center_api.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```powershell
git add app/command_center/extension_recorder.py app/command_center/service.py app/command_center/router.py tests/test_extension_recorder.py tests/test_command_center_service.py tests/test_command_center_api.py
git commit -m "fix: terminate invalid extension recordings safely"
```

### Task 2: Expose a Safe Recent Recording Summary

**Files:**
- Modify: `app/command_center/repository.py`
- Modify: `app/command_center/service.py`
- Modify: `app/command_center/router.py`
- Test: `tests/test_command_center_repository.py`
- Test: `tests/test_command_center_service.py`
- Test: `tests/test_command_center_api.py`

**Interfaces:**
- Produces: `CommandCenterRepository.list_recordings() -> list[dict[str, object]]`
- Produces: `CommandCenterService.list_recordings(capture_source: str | None, limit: int) -> list[dict[str, Any]]`
- Produces: `GET /recordings?capture_source=browser_extension&limit=10`

- [ ] **Step 1: Write failing timestamp and projection tests**

Assert new recordings contain UTC ISO-8601 `created_at` and `updated_at`; status transitions change `updated_at`; recent summaries contain only:

```python
{
    "recording_id", "status", "objective", "source_system",
    "capture_source", "created_at", "updated_at", "failure_reasons",
}
```

Insert a payload containing `trace`, `learning_result`, and a fake secret marker, then assert none appear in the list response.

- [ ] **Step 2: Run focused tests and observe missing list behavior**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_repository.py tests/test_command_center_service.py tests/test_command_center_api.py -q`

Expected: FAIL because recording list methods and timestamps do not exist.

- [ ] **Step 3: Implement timestamps and repository listing**

Use `datetime.now(UTC).isoformat()` at creation and state transitions. Repository listing parses stored payload JSON; the service filters by `capture_source`, sorts by `created_at` descending, bounds `limit` to `1..100`, and constructs a new allowlisted dictionary instead of removing sensitive keys from the stored payload.

- [ ] **Step 4: Implement the read endpoint**

Add `GET /recordings` alongside the existing POST route. Accept `capture_source` and `limit` query parameters, with a default limit of 10.

- [ ] **Step 5: Verify Task 2**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_repository.py tests/test_command_center_service.py tests/test_command_center_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add app/command_center/repository.py app/command_center/service.py app/command_center/router.py tests/test_command_center_repository.py tests/test_command_center_service.py tests/test_command_center_api.py
git commit -m "feat: expose recent recording status safely"
```

### Task 3: Retain Browser Extension Failure Feedback

**Files:**
- Modify: `browser_extension/background.mjs`
- Modify: `browser_extension/popup.mjs`
- Test: `browser_extension/tests/backend-lifecycle.test.mjs`

**Interfaces:**
- Produces popup status text `录制上传失败，请查看中控` when event upload or stop fails.
- Preserves existing `verified_candidate` rendering.

- [ ] **Step 1: Write a failing lifecycle test**

Simulate `/extension/events` returning 422 and assert the stopped capture status retains `learningStatus: "upload_failed"`. Assert popup rendering contains the explicit failure message rather than `只读模式：未录制`.

- [ ] **Step 2: Run the extension tests and observe failure**

Run: `node --test browser_extension/tests/backend-lifecycle.test.mjs`

Expected: FAIL because failed stop clears `capture` without retaining a learning result.

- [ ] **Step 3: Implement minimal failure retention**

In `stopCapture`, catch upload or stop errors, assign:

```javascript
lastLearningResult = {
  recording_id: expectedCapture.recordingId,
  status: 'upload_failed',
};
```

Then rethrow so the caller still receives an error. In the popup render function, map `upload_failed` to `录制上传失败，请查看中控`.

- [ ] **Step 4: Verify Task 3**

Run: `node --test browser_extension/tests/*.test.mjs`

Expected: all extension tests PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add browser_extension/background.mjs browser_extension/popup.mjs browser_extension/tests/backend-lifecycle.test.mjs
git commit -m "fix: retain extension upload failure status"
```

### Task 4: Show the Latest Extension Recording in the Workbench

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/commandCenter.ts`
- Modify: `frontend/src/pages/DemonstrationWorkbenchPage.vue`
- Modify: `frontend/src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts`

**Interfaces:**
- Consumes: `GET /recordings?capture_source=browser_extension&limit=1`
- Produces: one latest-recording status block and a manual refresh action.

- [ ] **Step 1: Write failing frontend tests**

Mock `listRecordings` and assert the page shows these mappings:

```typescript
recording   -> 正在录制
upload_failed -> 上传失败
analyzing   -> 智能体分析中
verified_candidate -> Skill 验证成功
rejected    -> Skill 验证失败
```

Assert failure reasons render, while `trace`, raw evidence, and credentials have no UI path.

- [ ] **Step 2: Run the page test and observe missing API/UI behavior**

Run: `npm run test -- --run src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts`

Working directory: `frontend`

Expected: FAIL because `listRecordings` and the status block do not exist.

- [ ] **Step 3: Implement API types and client**

Add `ExtensionRecordingStatus` and `RecordingSummary` types, then:

```typescript
export function listRecordings(limit = 1) {
  return request<RecordingSummary[]>(
    `/recordings?capture_source=browser_extension&limit=${limit}`,
  )
}
```

- [ ] **Step 4: Implement the minimal status block**

Load once on mount and provide a refresh button. Render only the latest summary's objective, status label, update time, and failure reasons. Avoid an always-on poll in V1; the extension records in an external browser, so an explicit refresh gives deterministic feedback without background traffic.

- [ ] **Step 5: Verify Task 4**

Run: `npm run test -- --run src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts`

Run: `npm run build`

Working directory: `frontend`

Expected: tests PASS and build exits 0.

- [ ] **Step 6: Commit Task 4**

```powershell
git add frontend/src/api/types.ts frontend/src/api/commandCenter.ts frontend/src/pages/DemonstrationWorkbenchPage.vue frontend/src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts
git commit -m "feat: show latest browser recording result"
```

### Task 5: Full Verification and Real Read-Only Acceptance

**Files:**
- Modify: `docs/testing/2026-08-03-yifeng-mes-readonly-acceptance.md`
- Modify if required by the observed result: `docs/superpowers/specs/2026-08-03-real-mes-readonly-observer-design.md`

**Interfaces:**
- Consumes the extension, backend, and frontend delivered by Tasks 1-4.
- Produces an append-only acceptance result with no credentials or raw business values.

- [ ] **Step 1: Run all automated verification**

```powershell
conda run -n langgraph python -m pytest -q
node --test browser_extension/tests/*.test.mjs
cd frontend
npm run test -- --run
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 2: Restart backend and frontend from the current working tree**

Verify `http://127.0.0.1:8000/skills` and `http://127.0.0.1:5173/` both return HTTP 200.

- [ ] **Step 3: Reload the unpacked browser extension**

The user reloads CommandCenter in the browser extension management page so its service worker uses the new source.

- [ ] **Step 4: Perform one controlled read-only demonstration**

On `http://yifeng.dtsum.com`, record only:

1. one purchase-application list query;
2. one existing purchase-application detail view.

Do not click any create, edit, save, submit, approve, complete, reverse, or delete action.

- [ ] **Step 5: Verify the terminal state through three signals**

Confirm:

1. extension popup reports `verified_candidate` or an explicit failure;
2. `GET /recordings?capture_source=browser_extension&limit=1` reports the same terminal state;
3. the workbench displays that state after refresh.

- [ ] **Step 6: Audit safety and append the acceptance result**

Record timestamps, a shortened recording identifier, observed Tool IDs, terminal state, and whether any MES mutation occurred. Do not copy credentials, request values, response values, or raw trace data into documentation.

- [ ] **Step 7: Commit acceptance documentation**

```powershell
git add docs/testing/2026-08-03-yifeng-mes-readonly-acceptance.md docs/superpowers/specs/2026-08-03-real-mes-readonly-observer-design.md
git commit -m "docs: record MES readonly extension acceptance"
```
