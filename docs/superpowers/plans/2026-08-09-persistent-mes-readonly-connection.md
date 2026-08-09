# Persistent MES Read-Only Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the browser extension securely synchronize the active MES credential, persist it in Windows Credential Manager, verify the generated read-only API Skill, and execute it from natural language in CommandCenter.

**Architecture:** A profile-driven connection service separates extension authorization, OS credential persistence, and Tool execution. The extension captures only the configured credential header after explicit persistent consent. The backend reuses the saved candidate Skill and test plan, then exposes verified read-only Skills to a multi-system execution graph whose semantic decisions remain agent-owned.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, LangGraph, Python keyring 25.7.0, Vue 3, TypeScript, WXT Manifest V3, Vitest, pytest

## Global Constraints

- Work directly on `main`; do not create a feature branch or use subagents.
- Use conda environment `langgraph` for Python commands.
- Pin `keyring==25.7.0`; it officially supports Windows Credential Locker and Python 3.9+.
- Never persist MES credentials in SQLite, JSON, `.env`, Skill payloads, recording evidence, logs, errors, tests, or frontend state.
- Never return a credential value from any API.
- Extension capture requires explicit user consent, exact profile origin, exact configured credential header, and a valid CommandCenter connection handshake.
- Only existing `side_effect=read` Tool permissions may be verified or executed for the MES connection.
- Agent owns Skill matching, parameter extraction, and result interpretation; code owns protocol, credentials, allowlists, limits, and deterministic safety boundaries.
- A 401 or 403 deletes the stored MES credential; other network errors do not.
- No browser replay, write Skill, username/password login, account system, tenant system, or production Vault integration.

---

### Task 1: OS-backed credential store and connection protocol

**Files:**
- Create: `app/command_center/system_connections.py`
- Modify: `app/command_center/schemas.py`
- Modify: `app/command_center/service.py`
- Modify: `app/command_center/router.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`
- Test: `tests/test_system_connections.py`
- Test: `tests/test_command_center_api.py`

**Interfaces:**
- Produces `SystemCredentialStore` protocol and `KeyringSystemCredentialStore`.
- Produces `ConnectionHandshakeStore.begin(system_code)`, `authorize(system_code, token)`, and `clear(system_code)`.
- Produces service methods `begin_system_connection`, `put_system_credential`, `get_system_connection`, and `disconnect_system`.

- [ ] Write failing tests proving store round-trip, overwrite, delete, no secret representation, handshake rejection, exact profile header enforcement, and secret-free API responses.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_system_connections.py tests/test_command_center_api.py -q` and verify failures are caused by missing connection code.
- [ ] Add `keyring==25.7.0` to `requirements.txt` and install it in `langgraph`.
- [ ] Implement `KeyringSystemCredentialStore` with service name `CommandCenter` and account key `<system_code>:<header.casefold()>`; inject a fake keyring backend in tests.
- [ ] Implement an in-memory random handshake token store. Store only SHA-256 token digests and expire tokens after their bounded connection window.
- [ ] Add profile-validated begin, credential, status, and delete routes. `GET` returns only `system_code`, `display_name`, `status`, and `credential_source='windows_keyring'`.
- [ ] Re-run focused tests and verify PASS.
- [ ] Commit with `feat: add persistent system connection store`.

### Task 2: Explicit extension consent and automatic credential synchronization

**Files:**
- Modify: `browser_extension/src/command-center/config.ts`
- Modify: `browser_extension/src/command-center/client.ts`
- Create: `browser_extension/src/command-center/connection.ts`
- Modify: `browser_extension/src/entrypoints/background.ts`
- Modify: `browser_extension/src/entrypoints/popup/App.tsx`
- Modify: `browser_extension/src/styles.css`
- Test: `browser_extension/tests/command-center-config.test.ts`
- Test: `browser_extension/tests/command-center-client.test.ts`
- Create: `browser_extension/tests/command-center-connection.test.ts`
- Modify: `browser_extension/tests/command-center-popup.test.tsx`

**Interfaces:**
- Extends `CommandCenterProfile` with `credentialHeader?: string`.
- Produces `SystemConnectionCoordinator` that persists only consent, begins a handshake, filters request headers, uploads the allowed credential, and disconnects.
- Adds runtime messages `get-system-connection`, `enable-system-connection`, and `disable-system-connection`.

- [ ] Write failing tests for exact origin/header capture, ignored unapproved requests, consent persistence without secret persistence, client request headers, and popup enable/disable behavior.
- [ ] Run `pnpm test` focused on the new connection tests and verify RED.
- [ ] Add `credentialHeader: 'X-Access-Token'` only to the MES profile; local purchase remains credential-free.
- [ ] Implement client methods for begin, upload, status, verify, and disconnect.
- [ ] Register `webRequest.onBeforeSendHeaders` with `['requestHeaders', 'extraHeaders']`. Pass only normalized metadata to the coordinator and never record captured headers.
- [ ] After a successful credential upload, automatically request latest Skill verification and refresh popup status.
- [ ] Add popup control “允许此 MES 登录会话连接中控” plus connected/disconnected states. Never render or store the secret.
- [ ] Run extension tests, typecheck, and build; verify PASS.
- [ ] Commit with `feat: connect browser session credentials to CommandCenter`.

### Task 3: Re-verify saved API candidates without model regeneration

**Files:**
- Modify: `app/command_center/repository.py`
- Modify: `app/command_center/service.py`
- Modify: `app/main.py`
- Modify: `app/command_center/router.py`
- Test: `tests/test_command_center_repository.py`
- Create: `tests/test_system_connection_verification.py`

**Interfaces:**
- Produces `repository.list_candidate_skills()` and `service.verify_latest_system_skill(system_code)`.
- Consumes the selected recording's persisted `candidate_skill` and `test_plan`.
- Produces recording state `verified_candidate` only after all three required read-only tests pass.

- [ ] Write failing tests proving the latest system candidate is selected, no model agent is called, stored tests run with system credentials, all-read enforcement occurs before requests, failed tests preserve the candidate, and passed tests mark the Skill verified.
- [ ] Run the focused backend tests and verify RED.
- [ ] Refactor the read-only tester factory to use `SystemCredentialStore.headers_for(system_code)` instead of recording-scoped credentials.
- [ ] Implement direct structured test-plan execution and persist replacement test results using the existing unique test identity.
- [ ] Update recording `learning_result`, `status`, `analysis_stage`, and verification metadata without changing the learned Skill definition.
- [ ] Re-run focused tests and verify PASS.
- [ ] Commit with `feat: verify API candidates through saved system connections`.

### Task 4: Multi-system agent execution for verified read-only Skills

**Files:**
- Modify: `app/command_center/tool_catalog.py`
- Modify: `app/command_center/tool_executor.py`
- Modify: `app/command_center/execution_graph.py`
- Modify: `app/command_center/agents.py`
- Modify: `app/main.py`
- Test: `tests/test_tool_executor.py`
- Test: `tests/test_execution_graph.py`
- Create: `tests/test_connected_mes_execution.py`

**Interfaces:**
- Produces a merged Tool catalog from all configured profiles.
- Execution Skill provider returns published Skills plus verified candidates whose every step resolves to an allowed read Tool.
- Generic request context creates one agent-selectable request object and merges agent-extracted Skill inputs into `task.content`.

- [ ] Write failing tests for agent-selected verified Skill execution, catalog routing by Tool ID, extracted parameter binding, missing required input failure, write Skill exclusion, response-size enforcement, and 401/403 credential deletion.
- [ ] Run focused execution tests and verify RED.
- [ ] Add a read-only merged catalog API without exposing mutable internal collections.
- [ ] Replace `LocalBusinessReader` as the default CommandCenter execution reader with a generic user-request reader; keep local form infrastructure outside this graph unchanged.
- [ ] Generalize the matching prompt to use each Skill's input schema and require all declared required inputs. Remove procurement-specific prompt text.
- [ ] Build `SkillRunner` with the merged catalog and system credential provider. Enforce read-only Skills again immediately before execution.
- [ ] Return bounded, normalized outputs in the existing task-run response.
- [ ] Re-run focused and full backend tests; verify PASS.
- [ ] Commit with `feat: execute verified system Skills from natural language`.

### Task 5: Connection state in the minimal test console

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/commandCenter.ts`
- Create: `frontend/src/components/SystemConnectionStatus.vue`
- Create: `frontend/src/components/__tests__/SystemConnectionStatus.spec.ts`
- Modify: `frontend/src/pages/TestConsolePage.vue`
- Modify: `frontend/src/pages/__tests__/TestConsolePage.spec.ts`
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`
- Modify: `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

**Interfaces:**
- Consumes `GET /system-connections/yifeng_mes`, verify, and disconnect endpoints.
- Produces a secret-free connection card and structured task output view.

- [ ] Write failing component/page tests for disconnected, connected, re-login-required, verification-running, verification-success, disconnect, and structured query output states.
- [ ] Run focused frontend tests and verify RED.
- [ ] Add the compact connection card above the two-column work area. The frontend may request verification or disconnect but never accept or display a Token.
- [ ] Render task-run outputs as bounded JSON data beneath the agent summary.
- [ ] Run full frontend tests and production build; verify PASS.
- [ ] Commit with `feat: show MES connection and Skill execution state`.

### Task 6: End-to-end safety and real MES acceptance

**Files:**
- Create: `docs/testing/2026-08-09-persistent-mes-readonly-connection-acceptance.md`
- Modify implementation files only when a failing acceptance test proves a defect.

**Interfaces:**
- Consumes the built extension, running backend/frontend, saved API candidate, and real MES logged-in browser session.
- Produces a verified read-only natural-language execution result and evidence that credentials were not persisted outside Windows Credential Manager.

- [ ] Run full backend, extension, and frontend test suites plus builds.
- [ ] Test the connection protocol against a local fake API first, including 401 deletion and no-write assertions.
- [ ] Install/reload `browser_extension/dist/chrome-mv3` and enable the MES connection once.
- [ ] Perform one normal MES list query so the extension synchronizes the credential.
- [ ] Verify the latest API candidate without model regeneration and confirm it becomes `verified_candidate`.
- [ ] Submit “查询采购申请列表” through the test console and verify the selected Tool is the MES allowlisted GET list endpoint.
- [ ] Compare MES state before/after and confirm no write occurred.
- [ ] Search SQLite, JSON evidence, logs, frontend state payloads, and extension IndexedDB serialization for credential values without printing the credential itself.
- [ ] Write the acceptance note with exact test counts, connection state, Skill ID/version, Tool ID, response status, and remaining limitations.
- [ ] Run `git diff --check`, confirm a clean test run, commit with `docs: verify persistent MES read-only execution`, and leave changes on `main` without pushing unless requested.
