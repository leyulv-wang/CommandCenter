# Multi-System Skill Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record one MES-to-local-purchase demonstration across two authorized browser tabs, distill it into a reusable cross-system API Skill, verify it with removable test data, and execute it from a trusted MES selection.

**Architecture:** Keep one recorder and one evidence protocol. Extend a recording session from one system profile to an ordered set of profiles, annotate every event with its system identity, and use a routing Tool catalog during learning. The resulting Skill remains the existing system-neutral multi-step Skill format; MES steps are read-only and the local follow-up step is an idempotent write with test-only cleanup.

**Tech Stack:** FastAPI, Pydantic, SQLite/SQLAlchemy, LangGraph agent workflow, Vue 3, WXT/React browser extension, TypeScript, Vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-13-multi-system-skill-recording-design.md`

## Global Constraints

- Run Python through `D:\anaconda3\envs\langgraph\python.exe` or `conda run -n langgraph`.
- MES is read-only for recording, testing, and formal execution.
- Only local records marked `automated_test` and owned by the current verification run may be automatically deleted.
- Single-system recording remains backward compatible.
- Browser capture is restricted to exact origins selected before recording.
- Credentials, cookies, headers, and raw sensitive values never enter evidence or Skill payloads.
- Agent reasoning owns semantic segmentation, API attribution, field mapping, and incomplete-evidence judgment; code owns schemas, allowlists, idempotency, resource limits, and cleanup boundaries.

---

### Task 1: Local Purchase Follow-Up Resource

**Files:**
- Modify: `external_systems/common.py`
- Modify: `external_systems/ui/index.html`
- Modify: `external_systems/ui/app.js`
- Test: `tests/test_external_systems.py`
- Test: `tests/test_external_system_ui.py`

**Interfaces:**
- Produces: `POST /api/purchase-follow-ups`, `GET /api/purchase-follow-ups/{follow_up_id}`, and `DELETE /api/purchase-follow-ups/{follow_up_id}`.
- Produces: request fields `mes_apply_no`, `material`, `quantity`, `applicant`, `remark`, `record_purpose`, `verification_run_id`.
- Enforces: `Idempotency-Key` on create; delete accepts only `record_purpose=automated_test` and matching `X-Verification-Run-Id`.

- [ ] Write failing API tests for idempotent create, read-back, protected formal record, owned test cleanup, and rejected cleanup ownership.
- [ ] Run `D:\anaconda3\envs\langgraph\python.exe -m pytest tests/test_external_systems.py -q` and confirm failure because the routes do not exist.
- [ ] Add a dedicated `purchase_follow_ups` table and strict Pydantic request model without changing existing purchase-request behavior.
- [ ] Add a minimal local UI form and list so a human can demonstrate the operation.
- [ ] Run the two target test files and confirm they pass.
- [ ] Commit as `feat: add local purchase follow-up resource`.

### Task 2: Multi-System Recording Evidence Protocol

**Files:**
- Modify: `app/command_center/router.py`
- Modify: `app/command_center/schemas.py`
- Modify: `app/command_center/service.py`
- Test: `tests/test_command_center_schemas.py`
- Test: `tests/test_command_center_api.py`
- Test: `tests/test_command_center_service.py`

**Interfaces:**
- Extends `CreateRecordingRequest` with `recording_mode: Literal["single_system", "multi_system"] = "single_system"` and `source_systems: list[str]`.
- Extends browser evidence objects with `system_code` and `tab_id` while accepting historical single-system batches.
- Persists `recording_mode` and the ordered `source_systems` on recording rows.

- [ ] Write failing schema and API tests for valid two-system sessions, duplicate/unknown systems, and legacy single-system requests.
- [ ] Run the three target files and confirm the new assertions fail.
- [ ] Implement strict normalization: single mode resolves exactly one source system; multi mode requires at least two unique configured systems.
- [ ] Include mode and systems in recording status responses without exposing credentials.
- [ ] Run target tests and confirm pass.
- [ ] Commit as `feat: define multi-system recording sessions`.

### Task 3: Routing Extension Recorder

**Files:**
- Modify: `app/command_center/extension_recorder.py`
- Modify: `app/command_center/recorder.py`
- Modify: `app/main.py`
- Test: `tests/test_extension_recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- `ExtensionRecorder.start(..., profiles: list[SystemProfile])` builds one trace using a routing catalog.
- Each event is validated against its declared profile and exact allowed origin.
- Each API exchange is added with its own `system_code`; UI event targets retain safe `system_code` and `tab_id` metadata.

- [ ] Write failing tests that ingest ordered MES and local events into one trace and reject a third origin or mismatched system identity.
- [ ] Confirm the tests fail against the single-profile recorder.
- [ ] Replace `_ExtensionSession.profile` with an immutable map of authorized profiles and catalogs.
- [ ] Match each event to exactly one configured system and route API matching through that system catalog.
- [ ] Finalize one `OperationTrace` containing both systems in original client sequence order.
- [ ] Run recorder tests and commit as `feat: ingest multi-system browser evidence`.

### Task 4: Browser Extension Multi-Tab Session

**Files:**
- Modify: `browser_extension/src/shared/types.ts`
- Modify: `browser_extension/src/command-center/client.ts`
- Modify: `browser_extension/src/command-center/session.ts`
- Modify: `browser_extension/src/entrypoints/background.ts`
- Modify: `browser_extension/src/command-center/evidence.ts`
- Test: `browser_extension/tests/command-center-session.test.ts`
- Test: `browser_extension/tests/background-recording-state.test.ts`
- Test: `browser_extension/tests/command-center-evidence.test.ts`

**Interfaces:**
- Adds `recording_kind: 'single_system' | 'multi_system'` to local recording connection metadata.
- Adds `system_codes`, `allowed_origins`, and an origin-to-system mapping to the session.
- Runtime `start-recording` accepts `profileIds: string[]`; every uploaded event carries resolved `system_code` and tab identity.

- [ ] Write failing tests for two profiles in one start request, automatic connection of both allowed tabs, and rejection of an unrelated tab.
- [ ] Run the three Vitest files and confirm failure.
- [ ] Update client/session payloads while retaining the existing one-profile call shape.
- [ ] Update background recording scope to connect all currently open matching tabs and later matching activated/updated tabs.
- [ ] Resolve system identity only from exact origin configuration, never from page labels or keywords.
- [ ] Run target tests and commit as `feat: record authorized tabs across systems`.

### Task 5: Explicit Single vs Joint Recording UI

**Files:**
- Modify: `browser_extension/src/entrypoints/popup/App.tsx`
- Modify: `browser_extension/src/styles.css`
- Test: `browser_extension/tests/command-center-popup.test.tsx`

**Interfaces:**
- Popup exposes `单系统录制` and `联合录制` modes.
- Joint mode lists MES and local purchase systems, requires both for the MVP, and displays joined systems during recording.

- [ ] Write failing UI tests for mode selection, disabled start with insufficient systems, and active joint-session display.
- [ ] Run the popup test and confirm failure.
- [ ] Implement the smallest accessible mode selector and system checklist using existing primitives.
- [ ] Pass `profileIds` and recording mode through the existing runtime message.
- [ ] Run popup tests, extension typecheck, and build.
- [ ] Commit as `feat: add joint recording mode to extension`.

### Task 6: Cross-System Skill Distillation

**Files:**
- Modify: `app/command_center/agents.py`
- Modify: `app/command_center/learning_graph.py`
- Modify: `app/command_center/schemas.py`
- Test: `tests/test_structured_agents.py`
- Test: `tests/test_learning_graph.py`

**Interfaces:**
- Learning input exposes ordered system-aware UI/API evidence and all authorized Tool schemas.
- Existing `SkillDefinition.steps` represents multiple `system_code` Tool IDs and cross-step bindings such as `steps.read_mes.output...`.
- Candidate result includes a safe field-mapping evidence summary and rejects a cross-system claim when only one system has core evidence.

- [ ] Write failing agent-contract tests for a two-step MES-read/local-write Skill and missing-second-system evidence.
- [ ] Confirm failure with the current single-system prompts/validation.
- [ ] Expand agent context and role prompts to reason over system boundaries without hard-coded MES parameter names.
- [ ] Validate that every compiled step references an observed/allowlisted Tool and that write bindings originate from trusted task data or prior Step outputs.
- [ ] Preserve `needs_reteach` with explicit missing-system or ambiguous-mapping reasons.
- [ ] Run target tests and commit as `feat: distill cross-system API skills`.

### Task 7: Harmless Cross-System Verification and Cleanup

**Files:**
- Create: `app/command_center/cross_system_testing.py`
- Modify: `app/command_center/service.py`
- Modify: `app/main.py`
- Test: `tests/test_cross_system_testing.py`
- Test: `tests/test_command_center_service.py`

**Interfaces:**
- Produces `CrossSystemSkillTestService.run(skill, mes_record, verification_run_id) -> dict[str, Any]`.
- Executes MES steps only when `side_effect == "read"`.
- Adds `record_purpose=automated_test` and `verification_run_id` to local create input, reads it back, asks the verifier agent to judge mapping evidence, then deletes with ownership proof.
- Returns independent `execution_status`, `verification_status`, and `cleanup_status`.

- [ ] Write failing tests for successful create/read/delete, MES write rejection, local formal-record deletion rejection, and cleanup failure reporting.
- [ ] Confirm tests fail because the service does not exist.
- [ ] Implement a focused service using existing ToolExecutor and agent verification interfaces.
- [ ] Ensure a successful business assertion cannot hide failed cleanup; persist residual test task ID when cleanup fails.
- [ ] Wire the service into asynchronous recording analysis for multi-system candidates.
- [ ] Run target tests and commit as `feat: verify and clean cross-system skills`.

### Task 8: Trusted Formal Execution and Minimal Result Display

**Files:**
- Modify: `app/command_center/router.py`
- Modify: `app/command_center/service.py`
- Modify: `frontend/src/api/commandCenter.ts`
- Modify: `frontend/src/components/TaskResultTable.vue`
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`
- Test: `tests/test_command_center_api.py`
- Test: `tests/test_command_center_service.py`
- Test: `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

**Interfaces:**
- Adds `POST /task-runs/{run_id}/purchase-follow-up` with body `{record_id, instruction}`.
- Resolves `record_id` only from the saved parent MES output and supplies the trusted record to Skill execution.
- Returns local follow-up ID, MES application number, per-system step status, and evidence summaries.

- [ ] Write failing backend tests for trusted selection, unknown record, idempotent duplicate instruction, and multi-system result persistence.
- [ ] Write failing frontend test for the row action and result card.
- [ ] Implement the endpoint and service orchestration using the published/verified cross-system Skill.
- [ ] Add a minimal “创建采购跟进任务” row action and readable execution result.
- [ ] Run backend and frontend target tests.
- [ ] Commit as `feat: execute purchase follow-up skill from trusted selection`.

### Task 9: End-to-End Acceptance and Documentation

**Files:**
- Modify: `browser_extension/e2e/extension-harness.ts`
- Create: `browser_extension/e2e/multi-system-recording.spec.ts`
- Create: `docs/testing/2026-08-13-multi-system-skill-acceptance.md`
- Modify: `docs/architecture/browser-recording-dual-path.md`

**Interfaces:**
- Automated E2E uses a safe MES fixture or intercepted read-only response plus the real local purchase system.
- Manual acceptance uses real MES read-only browsing and local test writes only.

- [ ] Add E2E coverage for starting joint recording, using two tabs, stopping, generating a candidate, creating a marked test task, and confirming cleanup.
- [ ] Add regression coverage proving an unrelated third tab is absent from uploaded evidence.
- [ ] Run backend full suite, frontend tests/build, extension tests/typecheck/build, and local extension E2E.
- [ ] Perform one real manual joint recording only after automated E2E is green.
- [ ] Document sanitized evidence, timings, cleanup result, and remaining limitations.
- [ ] Commit as `test: accept multi-system skill recording loop`.
