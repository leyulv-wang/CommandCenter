# Local Purchase Browser Extension E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable local browser test that loads the real CommandCenter extension, records a read-only operation in the existing purchase system, uploads evidence, and verifies lifecycle and popup-state correctness before MES testing.

**Architecture:** Reuse the purchase service at `127.0.0.1:8101` and the CommandCenter API at `127.0.0.1:8000`. The extension keeps one recording implementation; popup UI and Playwright drive the same background protocol. Deterministic code handles injection, lifecycle cleanup, isolation, and assertions while agents retain evidence interpretation and Skill generation.

**Tech Stack:** FastAPI, Pydantic, Vue-independent purchase demo UI, WXT MV3 extension, TypeScript, React, Dexie, Vitest, Playwright, Chromium.

## Global Constraints

- Work on the existing `main` branch because the user explicitly approved direct main-branch development for this single-user project.
- Do not use subagents.
- Use `conda run -n langgraph` for Python commands.
- Reuse `external_systems.connected_system`; do not create a third demo system.
- The E2E business operation is read-only and must not create, submit, approve, or delete purchase data.
- The browser uses an isolated temporary profile and must not reuse MES credentials or cookies.
- The test must load `browser_extension/dist/chrome-mv3`; simulated runtime messages alone do not satisfy E2E acceptance.
- Tests assert safe metadata and status only; they must not print credentials, tokens, cookies, request bodies, or original business values.

---

### Task 1: Add the local purchase recording profile

**Files:**
- Modify: `browser_extension/src/command-center/config.ts`
- Modify: `browser_extension/tests/command-center-config.test.ts`
- Modify: `browser_extension/tests/command-center-popup.test.tsx`

**Interfaces:**
- Produces: `LOCAL_PURCHASE_COMMAND_CENTER_PROFILE: CommandCenterProfile`
- Produces: `DEFAULT_COMMAND_CENTER_PROFILES` containing both local purchase and MES profiles.
- Consumes: existing exact-origin matching in `profileForUrl()` and `originAllowed()`.

- [ ] **Step 1: Write failing profile and popup tests**

Add literal assertions that `http://127.0.0.1:8101/` resolves to `systemCode === 'connected_system'`, while `http://127.0.0.1:81010/` does not match. Update the popup fixture to use the local URL and assert the visible name is `采购业务系统`.

- [ ] **Step 2: Verify the tests fail for the missing local profile**

Run:

```powershell
cd browser_extension
npm test -- tests/command-center-config.test.ts tests/command-center-popup.test.tsx
```

Expected: the local URL returns `null` and the popup reports no matching system.

- [ ] **Step 3: Add the minimal local profile**

Add:

```ts
export const LOCAL_PURCHASE_COMMAND_CENTER_PROFILE: CommandCenterProfile = {
  id: 'local-purchase',
  displayName: '采购业务系统',
  origins: ['http://127.0.0.1:8101'],
  systemCode: 'connected_system',
  commandCenterUrl: 'http://127.0.0.1:8000',
  captureNetworkBodies: true,
};
```

Place it before the MES profile in `DEFAULT_COMMAND_CENTER_PROFILES`.

- [ ] **Step 4: Verify profile and popup tests pass**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/command-center/config.ts browser_extension/tests/command-center-config.test.ts browser_extension/tests/command-center-popup.test.tsx
git commit -m "feat: add local purchase recording profile"
```

---

### Task 2: Connect already-open allowed pages to a new recording

**Files:**
- Modify: `browser_extension/src/entrypoints/background.ts`
- Create: `browser_extension/src/recording/tab-connection.ts`
- Create: `browser_extension/tests/tab-connection.test.ts`

**Interfaces:**
- Produces: `connectRecordingTab(input): Promise<'messaged' | 'injected' | 'skipped'>`.
- Consumes: `originAllowed(url, allowedOrigins)` and `chrome.scripting.executeScript`.
- Invariant: injection occurs only when an allowed HTTP(S) tab has no content-script receiver.

- [ ] **Step 1: Write failing tab-connection tests**

Cover these observable cases with browser doubles that mirror `tabs.sendMessage` and `scripting.executeScript`:

1. an installed receiver returns `messaged` and does not inject;
2. a missing receiver on `http://127.0.0.1:8101` injects `content-scripts/content.js` into all frames and returns `injected`;
3. a missing receiver on any non-allowed origin returns `skipped` and never injects;
4. stopping a recording never injects.

- [ ] **Step 2: Verify the new tests fail because the module is absent**

Run:

```powershell
cd browser_extension
npm test -- tests/tab-connection.test.ts
```

Expected: module resolution or export failure for `tab-connection`.

- [ ] **Step 3: Implement the focused connector**

Implement a function with this input shape:

```ts
type ConnectRecordingTabInput = {
  tabId: number;
  url: string;
  message: RecordingStateMessage;
  allowedOrigins: readonly string[];
  sendMessage: (tabId: number, message: RecordingStateMessage) => Promise<unknown>;
  inject: (tabId: number) => Promise<unknown>;
};
```

First try `sendMessage`. On rejection, inject only when `message.active` is true and the URL passes `originAllowed`; otherwise return `skipped`. Do not reload the page because that could discard unsaved user input.

- [ ] **Step 4: Use the connector from `broadcastRecordingState`**

Query HTTP(S) tabs as today, pass each tab's actual URL, and inject the packaged content script through:

```ts
chrome.scripting.executeScript({
  target: { tabId, allFrames: true },
  files: ['content-scripts/content.js'],
});
```

Keep `Promise.allSettled` so one inaccessible tab cannot break recording startup.

- [ ] **Step 5: Verify tab-connection and existing extension tests**

Run:

```powershell
cd browser_extension
npm test -- tests/tab-connection.test.ts tests/command-center-session.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add browser_extension/src/entrypoints/background.ts browser_extension/src/recording/tab-connection.ts browser_extension/tests/tab-connection.test.ts
git commit -m "fix: connect active recording to open tabs"
```

---

### Task 3: End failed local uploads without leaving remote recordings active

**Files:**
- Modify: `app/command_center/router.py`
- Modify: `app/command_center/service.py`
- Modify: `tests/test_command_center_api.py`
- Modify: `tests/test_command_center_service.py`
- Modify: `browser_extension/src/command-center/client.ts`
- Modify: `browser_extension/src/command-center/upload.ts`
- Modify: `browser_extension/tests/command-center-client.test.ts`
- Modify: `browser_extension/tests/command-center-upload.test.ts`

**Interfaces:**
- Produces backend route: `POST /recordings/{recording_id}/extension/abort` with `X-CommandCenter-Recording-Token`.
- Produces client method: `abort(recordingId: string, token: string, reason: string): Promise<{status: string}>`.
- Stable invariant: once local capture has stopped, a failed upload must not leave the remote session in `recording`.

- [ ] **Step 1: Write failing backend abort tests**

Assert that an authorized abort moves a browser-extension recording to `upload_failed`, clears the extension session and credentials, and exposes only the literal safe public message. Assert that a bad token returns `401` and does not change the recording.

- [ ] **Step 2: Verify backend tests fail for the missing route**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_api.py tests/test_command_center_service.py -q
```

Expected: `404` for the abort route or a missing service method.

- [ ] **Step 3: Implement the backend lifecycle abort**

Reuse the existing authorized extension abort and safe failure persistence path. Accept a constrained request containing a machine reason code such as `no_uploadable_evidence` or `upload_failed`; do not persist arbitrary exception text from the browser.

- [ ] **Step 4: Verify backend abort tests pass**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Write failing extension client/upload tests**

Assert:

1. `client.abort()` sends the authorized POST request with a safe reason code;
2. when evidence conversion returns zero events, upload calls abort once and stores local `status: 'failed'` with the local diagnostic;
3. if the abort request also fails, the original local error remains the visible error and evidence remains in IndexedDB.

- [ ] **Step 6: Verify extension tests fail for the missing client method**

Run:

```powershell
cd browser_extension
npm test -- tests/command-center-client.test.ts tests/command-center-upload.test.ts
```

Expected: missing `abort` method or missing abort call.

- [ ] **Step 7: Implement client abort and best-effort remote cleanup**

Map browser-local errors to fixed reason codes. Call `client.abort()` inside the upload catch path before persisting local failure. Catch abort errors separately so remote cleanup failure never deletes or overwrites local evidence and the original diagnostic.

- [ ] **Step 8: Verify extension client/upload tests pass**

Run the command from Step 6. Expected: all selected tests pass.

- [ ] **Step 9: Commit**

```powershell
git add app/command_center/router.py app/command_center/service.py tests/test_command_center_api.py tests/test_command_center_service.py browser_extension/src/command-center/client.ts browser_extension/src/command-center/upload.ts browser_extension/tests/command-center-client.test.ts browser_extension/tests/command-center-upload.test.ts
git commit -m "fix: abort remote recording after upload failure"
```

---

### Task 4: Restore the latest extension result when the popup reopens

**Files:**
- Modify: `browser_extension/src/entrypoints/background.ts`
- Modify: `browser_extension/src/entrypoints/popup/App.tsx`
- Modify: `browser_extension/tests/command-center-popup.test.tsx`
- Create: `browser_extension/tests/background-recording-state.test.ts`

**Interfaces:**
- Produces background response: `{ active, traceId, row }`, where `row` is the active row or the most recently updated CommandCenter row.
- Popup rule: active `recording` rows open the recording view; inactive `failed`, `uploaded`, or resumable rows open the processing/result view.

- [ ] **Step 1: Write failing background and popup recovery tests**

Assert that no active recording plus a latest failed row returns `active: false` with that row. Mount the popup with that response and assert the visible message is `处理失败，证据仍保存在本地。`, not the idle recording form.

Add the same popup assertion for an uploaded row whose remote status is `learning`.

- [ ] **Step 2: Verify recovery tests fail**

Run:

```powershell
cd browser_extension
npm test -- tests/background-recording-state.test.ts tests/command-center-popup.test.tsx
```

Expected: the popup shows the idle form because inactive rows are ignored.

- [ ] **Step 3: Implement latest-row lookup and popup hydration**

Read only rows with a `command_center` connection, sort by `updated_at` descending, and return the newest row. In the popup initialization, hydrate `activeRow`, objective, and `remoteStatus` from an inactive row and select `processing`.

- [ ] **Step 4: Verify recovery tests pass**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/entrypoints/background.ts browser_extension/src/entrypoints/popup/App.tsx browser_extension/tests/background-recording-state.test.ts browser_extension/tests/command-center-popup.test.tsx
git commit -m "fix: restore latest browser recording result"
```

---

### Task 5: Add a real-extension Playwright E2E against the purchase system

**Files:**
- Modify: `browser_extension/package.json`
- Modify: `browser_extension/package-lock.json`
- Create: `browser_extension/playwright.config.ts`
- Create: `browser_extension/e2e/local-purchase-recording.spec.ts`
- Create: `browser_extension/e2e/extension-harness.ts`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces npm command: `npm run test:e2e:local`.
- Produces harness functions `launchExtensionContext()`, `extensionPopup()`, and `readRecordingEvidenceSummary()`.
- Consumes the built extension at `dist/chrome-mv3` and live services on ports `8000` and `8101`.

- [ ] **Step 1: Add Playwright and write the failing E2E**

Install `@playwright/test` as a development dependency. Write a test that:

1. snapshots `/api/submissions` before the run;
2. launches a persistent Chromium context with `--disable-extensions-except` and `--load-extension` pointing at the real build;
3. discovers the MV3 extension ID from its service-worker URL;
4. opens the purchase page before starting the recording;
5. opens `chrome-extension://<id>/popup.html`, selects the local profile by active tab, enters `查询采购申请`, and starts recording;
6. clicks the purchase page's `刷新数据` button and waits for `GET /api/tasks`;
7. stops recording through the actual popup;
8. reads IndexedDB in the service-worker origin and asserts at least one `action` plus one network request/response event exists;
9. polls the CommandCenter recording until it leaves `recording` and reaches a documented terminal or queued-learning state within a bounded timeout;
10. reloads the popup and asserts the recent result remains visible;
11. compares `/api/submissions` after the run with the before snapshot.

- [ ] **Step 2: Run the E2E and verify it fails before the required behavior is complete**

Run:

```powershell
cd browser_extension
npm run build
npm run test:e2e:local
```

Expected before all preceding fixes: failure on missing evidence, stuck `recording`, or lost popup state. If it fails only because Chromium is absent, install the Playwright Chromium runtime and rerun until the behavioral failure is observed.

- [ ] **Step 3: Implement the isolated extension harness and service configuration**

Use Playwright's temporary `userDataDir`, headless false only when extension support requires it, and delete the directory in `finally`. Configure the two existing FastAPI services as bounded Playwright web servers using the project's conda environment. Keep traces only on failure under `browser_extension/test-results/`.

- [ ] **Step 4: Run the real-extension E2E to green**

Run the command from Step 2. Expected: one passing E2E; action and network evidence are non-empty; popup state survives reload; submissions are byte-for-byte equivalent before and after.

- [ ] **Step 5: Document the command and ignore generated artifacts**

Add `browser_extension/test-results/` and `browser_extension/playwright-report/` to `.gitignore`. Add the exact build and E2E command to the README, stating that MES testing begins only after this command passes.

- [ ] **Step 6: Commit**

```powershell
git add browser_extension/package.json browser_extension/package-lock.json browser_extension/playwright.config.ts browser_extension/e2e/extension-harness.ts browser_extension/e2e/local-purchase-recording.spec.ts .gitignore README.md
git commit -m "test: add local purchase extension e2e"
```

---

### Task 6: Full regression and acceptance evidence

**Files:**
- Modify: `docs/architecture/browser-recording-dual-path.md`
- Create: `docs/testing/2026-08-07-local-purchase-extension-e2e.md`

**Interfaces:**
- Produces a dated acceptance record containing commands, counts, outcome, and any remaining MES-only compatibility risk.

- [ ] **Step 1: Run the full backend suite**

```powershell
conda run -n langgraph python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run full extension verification**

```powershell
cd browser_extension
npm test
npm run typecheck
npm run build
npm run test:e2e:local
```

Expected: zero failures and successful production build.

- [ ] **Step 3: Run formal frontend verification**

```powershell
cd frontend
npm test
npm run build
```

Expected: zero failures and successful production build.

- [ ] **Step 4: Check repository and security invariants**

Run:

```powershell
git diff --check
rg -n "cookie|authorization|recording_token|api_key" browser_extension/test-results docs/testing/2026-08-07-local-purchase-extension-e2e.md
```

Expected: `git diff --check` is clean and generated evidence/documentation contains no credential values. Field names may appear only in source code, not captured test output.

- [ ] **Step 5: Record exact verification evidence and architecture status**

Document exact test counts, E2E duration, browser executable/version, recording terminal status, unchanged purchase record counts, and the remaining requirement for one MES read-only compatibility run.

- [ ] **Step 6: Commit**

```powershell
git add docs/architecture/browser-recording-dual-path.md docs/testing/2026-08-07-local-purchase-extension-e2e.md
git commit -m "docs: record local extension e2e acceptance"
```
