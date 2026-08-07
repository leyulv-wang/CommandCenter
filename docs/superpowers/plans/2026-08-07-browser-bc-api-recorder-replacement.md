# Browser-BC API Recorder Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary CommandCenter browser extension with Browser-BC's recorder foundation and feed its redacted page and network evidence into the existing API Skill learning loop.

**Architecture:** Browser-BC remains responsible for capture, redaction, IndexedDB persistence, and retryable upload state. A focused CommandCenter adapter maps Journey events into the existing extension evidence API; FastAPI and LangGraph retain responsibility for API Tool alignment, Skill compilation, harmless verification, and publication.

**Tech Stack:** Chrome Manifest V3, WXT 0.19, TypeScript 5.7, React 18, Dexie 4, Vitest 2, FastAPI, Pydantic, LangGraph, pytest.

## Global Constraints

- Use Browser-BC commit `5afc6d4` as the recorded upstream source.
- Replace `browser_extension/`; do not run Browser-BC's Python server or install its Claude skills.
- Do not request or use `chrome.debugger`.
- Keep site profiles configurable; `yifeng.dtsum.com` is the first profile, not a business-specific branch.
- Do not upload passwords, cookies, authorization headers, tokens, file contents, raw clipboard text, or raw selected text.
- Protocol mapping may enforce schemas, limits, ordering, and allowlists but must not decide business intent or API relevance.
- Use `pnpm` for the extension and `conda run -n langgraph` for Python verification.
- Preserve upstream repository URL and commit attribution in `browser_extension/UPSTREAM.md`.

---

## File Structure

- `browser_extension/src/capture/`, `recording/`, `redaction/`, `storage/`: upstream capture foundation.
- `browser_extension/src/command-center/config.ts`: configurable CommandCenter and site profile settings.
- `browser_extension/src/command-center/client.ts`: existing FastAPI recording lifecycle client.
- `browser_extension/src/command-center/evidence.ts`: pure Journey-to-CommandCenter evidence conversion.
- `browser_extension/src/command-center/session.ts`: coordinates local recording, upload batches, stop, and status polling.
- `browser_extension/src/entrypoints/popup/App.tsx`: minimal objective, record/stop, and result UI.
- `browser_extension/tests/command-center-*.test.ts`: adapter contract tests.
- `tests/test_browser_bc_extension_contract.py`: backend acceptance contract using representative adapter output.
- `browser_extension/UPSTREAM.md`: provenance and local-difference boundary.

### Task 1: Replace the Extension Scaffold with the Browser-BC Foundation

**Files:**
- Replace: `browser_extension/**`
- Create: `browser_extension/UPSTREAM.md`
- Test: `browser_extension/tests/command-center-scaffold.test.ts`

**Interfaces:**
- Consumes: Browser-BC `extension/` at commit `5afc6d4`.
- Produces: a buildable WXT extension with no `debugger` permission and an explicit upstream record.

- [ ] **Step 1: Preserve the old extension outside the product tree for comparison**

Use Git history as the source of truth; do not create a second maintained extension directory. Confirm the current tree is committed:

```powershell
git status --short
git rev-parse HEAD
```

- [ ] **Step 2: Write a failing scaffold contract test**

Create `browser_extension/tests/command-center-scaffold.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('CommandCenter extension scaffold', () => {
  it('uses the Browser-BC WXT foundation without debugger permission', () => {
    const config = readFileSync(resolve('wxt.config.ts'), 'utf8');
    expect(config).toContain("modules: ['@wxt-dev/module-react']");
    expect(config).not.toContain("'debugger'");
  });

  it('records the exact upstream source', () => {
    const upstream = readFileSync(resolve('UPSTREAM.md'), 'utf8');
    expect(upstream).toContain('https://github.com/Einsia/Browser-BC');
    expect(upstream).toContain('5afc6d4');
  });
});
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```powershell
cd browser_extension
pnpm test -- command-center-scaffold.test.ts
```

Expected: FAIL because the old extension has no WXT scaffold or `UPSTREAM.md`.

- [ ] **Step 4: Replace the scaffold and record provenance**

Copy the contents of `D:\python\gui-agent-references\repos\Browser-BC\extension` into
`browser_extension/`, excluding `node_modules/` and `dist/`. Create `UPSTREAM.md` containing:

```markdown
# Upstream Source

- Repository: https://github.com/Einsia/Browser-BC
- Adopted commit: 5afc6d4
- Adopted component: extension/
- Local purpose: capture redacted browser and API evidence for CommandCenter.
- Excluded components: Browser-BC server, harness, panel, and Claude skill installer.

Local changes belong in `src/command-center/` or narrowly scoped integration edits so upstream
capture changes remain reviewable.
```

Change the WXT manifest name and description to CommandCenter, preserve required capture permissions,
and ensure no `debugger` permission exists.

- [ ] **Step 5: Install, test, type-check, and build**

Run:

```powershell
cd browser_extension
pnpm install --frozen-lockfile
pnpm test -- command-center-scaffold.test.ts
pnpm typecheck
pnpm build
```

Expected: all commands exit 0 and `dist/chrome-mv3/manifest.json` contains no `debugger` permission.

- [ ] **Step 6: Commit the scaffold replacement**

```powershell
git add browser_extension
git commit -m "refactor: adopt Browser-BC extension foundation"
```

### Task 2: Add Configurable CommandCenter Site Profiles

**Files:**
- Create: `browser_extension/src/command-center/config.ts`
- Test: `browser_extension/tests/command-center-config.test.ts`
- Modify: `browser_extension/src/storage/db.ts`

**Interfaces:**
- Produces: `CommandCenterProfile`, `DEFAULT_COMMAND_CENTER_PROFILE`, and `profileForUrl(url, profiles)`.
- Consumes: popup and session modules in later tasks.

- [ ] **Step 1: Write failing profile tests**

```ts
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_COMMAND_CENTER_PROFILE,
  profileForUrl,
  type CommandCenterProfile,
} from '@/command-center/config';

describe('CommandCenter profiles', () => {
  it('selects the configured MES profile by exact origin', () => {
    expect(profileForUrl('http://yifeng.dtsum.com/purchase/apply', [DEFAULT_COMMAND_CENTER_PROFILE])?.systemCode)
      .toBe('yifeng_mes');
  });

  it('does not match suffix or credential-confusion origins', () => {
    expect(profileForUrl('http://yifeng.dtsum.com.attacker.test/', [DEFAULT_COMMAND_CENTER_PROFILE]))
      .toBeNull();
  });

  it('supports another system without changing the recorder', () => {
    const profile: CommandCenterProfile = {
      id: 'test',
      displayName: '测试系统',
      origins: ['https://test.example'],
      systemCode: 'test_system',
      commandCenterUrl: 'http://127.0.0.1:8000',
      captureNetworkBodies: true,
    };
    expect(profileForUrl('https://test.example/form', [profile])).toEqual(profile);
  });
});
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
cd browser_extension
pnpm test -- command-center-config.test.ts
```

Expected: FAIL because `@/command-center/config` does not exist.

- [ ] **Step 3: Implement the profile boundary**

Define:

```ts
export type CommandCenterProfile = {
  id: string;
  displayName: string;
  origins: string[];
  systemCode: string;
  commandCenterUrl: string;
  captureNetworkBodies: boolean;
};

export const DEFAULT_COMMAND_CENTER_PROFILE: CommandCenterProfile = {
  id: 'yifeng-mes',
  displayName: '益丰 MES',
  origins: ['http://yifeng.dtsum.com'],
  systemCode: 'yifeng_mes',
  commandCenterUrl: 'http://127.0.0.1:8000',
  captureNetworkBodies: true,
};
```

`profileForUrl` must parse the input with `URL`, compare exact `origin`, and return `null` on parse failure.
Persist selected profile and user-edited profile list through the existing Dexie/config boundary rather than
adding domain-specific branches to capture modules.

- [ ] **Step 4: Run focused and full extension tests**

```powershell
cd browser_extension
pnpm test -- command-center-config.test.ts
pnpm test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/command-center/config.ts browser_extension/src/storage/db.ts browser_extension/tests/command-center-config.test.ts
git commit -m "feat: configure browser recording system profiles"
```

### Task 3: Convert Journey Events into CommandCenter Evidence

**Files:**
- Create: `browser_extension/src/command-center/evidence.ts`
- Test: `browser_extension/tests/command-center-evidence.test.ts`
- Test: `tests/test_browser_bc_extension_contract.py`

**Interfaces:**
- Produces: `createEvidenceConverter(options)` with `append(event)` and `flush(recordingId)`.
- Produces: `CommandCenterEvidenceBatch` matching `ExtensionEventBatch`.
- Consumes: Browser-BC `CapturedEvent` and exact profile origin.

- [ ] **Step 1: Write failing TypeScript conversion tests**

Cover one UI action followed by one request/response pair. Assert that:

```ts
expect(batch.events.map((event) => event.client_sequence)).toEqual([1, 2]);
expect(batch.events[0]).toMatchObject({ event_type: 'click' });
expect(batch.events[1]).toMatchObject({
  method: 'GET',
  path_template: '/jeecg-boot/purchase/apply/list',
  query_parameter_names: ['pageNo'],
  response_status: 200,
});
expect(JSON.stringify(batch)).not.toContain('admin');
expect(JSON.stringify(batch)).not.toContain('X-Access-Token');
```

Also test that unmatched response events, foreign origins, invalid methods, internal extension URLs, password
values, and stream metadata never produce executable network exchanges.

- [ ] **Step 2: Run and verify RED**

```powershell
cd browser_extension
pnpm test -- command-center-evidence.test.ts
```

Expected: FAIL because the converter is absent.

- [ ] **Step 3: Implement the pure converter**

Define the public boundary:

```ts
export type EvidenceConverter = {
  append(event: CapturedEvent): void;
  flush(recordingId: string): CommandCenterEvidenceBatch | null;
};

export function createEvidenceConverter(options: {
  allowedOrigins: string[];
  fingerprintKey: string;
  maxBufferedEvents?: number;
}): EvidenceConverter;
```

Use a request-id map to join `network_request` and `network_response`. Parse URLs and emit only path plus
sorted query parameter names. Generate HMAC-SHA256 fingerprints for selectors, values, request bodies,
responses when available, and endpoints. Never place raw values or headers into the output. Assign one
strictly increasing `client_sequence` across actions, mutations, and completed exchanges.

- [ ] **Step 4: Add a backend contract fixture**

Create `tests/test_browser_bc_extension_contract.py` with a representative JSON payload produced by the
TypeScript contract and validate it using:

```python
batch = ExtensionEventBatch.model_validate(payload)
assert batch.recording_id == recording_id
assert batch.events[0].client_sequence < batch.events[1].client_sequence
assert batch.events[1].path_template == "/jeecg-boot/purchase/apply/list"
```

Add rejection cases for a raw token field, foreign origin, and non-monotonic sequence.

- [ ] **Step 5: Run TypeScript and Python contract tests**

```powershell
cd browser_extension
pnpm test -- command-center-evidence.test.ts
cd ..
conda run -n langgraph python -m pytest tests/test_browser_bc_extension_contract.py tests/test_extension_recorder.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add browser_extension/src/command-center/evidence.ts browser_extension/tests/command-center-evidence.test.ts tests/test_browser_bc_extension_contract.py
git commit -m "feat: adapt browser traces to command center evidence"
```

### Task 4: Connect the Reliable Recording Lifecycle

**Files:**
- Create: `browser_extension/src/command-center/client.ts`
- Create: `browser_extension/src/command-center/session.ts`
- Test: `browser_extension/tests/command-center-client.test.ts`
- Test: `browser_extension/tests/command-center-session.test.ts`
- Modify: `browser_extension/src/entrypoints/background.ts`
- Modify: `browser_extension/src/recording/recorder.ts`
- Modify: `browser_extension/src/upload/runner.ts`

**Interfaces:**
- Produces: `CommandCenterClient` methods `createRecording`, `start`, `uploadEvents`, `stop`, `getStatus`.
- Produces: `CommandCenterSessionCoordinator.start`, `stop`, `resumeUpload`, `getStatus`.
- Consumes: profile and evidence converter from Tasks 2 and 3.

- [ ] **Step 1: Write failing HTTP client tests**

Use a deterministic fake `fetch` and assert exact requests:

```ts
expect(requests.map(({ path, method }) => [path, method])).toEqual([
  ['/recordings', 'POST'],
  [`/recordings/${recordingId}/extension/start`, 'POST'],
  [`/recordings/${recordingId}/extension/events`, 'POST'],
  [`/recordings/${recordingId}/extension/stop`, 'POST'],
  [`/recordings/${recordingId}`, 'GET'],
]);
```

Assert `X-CommandCenter-Recording-Token` is sent only to authorized recording endpoints and is never written
into an evidence body or error message.

- [ ] **Step 2: Run client tests and verify RED**

```powershell
cd browser_extension
pnpm test -- command-center-client.test.ts
```

Expected: FAIL because the client is absent.

- [ ] **Step 3: Implement the HTTP client**

Define:

```ts
export type CommandCenterClient = {
  createRecording(input: { objective: string; sourceSystem: string }): Promise<{ recordingId: string }>;
  start(recordingId: string): Promise<{ recordingToken: string }>;
  uploadEvents(recordingId: string, token: string, batch: CommandCenterEvidenceBatch): Promise<void>;
  stop(recordingId: string, token: string): Promise<{ status: string }>;
  getStatus(recordingId: string): Promise<CommandCenterRecordingStatus>;
};
```

Use bounded timeouts, parse non-2xx errors into status plus safe code, and never include response bodies that
may contain secrets in user-facing messages.

- [ ] **Step 4: Write failing coordinator recovery tests**

Test these state transitions against fake IndexedDB:

```text
idle -> recording -> ready -> uploading -> uploaded -> processing
uploading -> failed -> uploading
recording -> browser restart -> recording
```

Stopping must flush pending content-script sends, persist local evidence, upload all accepted batches, submit
stop once, and retain local data until CommandCenter acknowledges it.

- [ ] **Step 5: Run coordinator tests and verify RED**

```powershell
cd browser_extension
pnpm test -- command-center-session.test.ts
```

Expected: FAIL because the coordinator is absent.

- [ ] **Step 6: Implement and wire the coordinator**

Replace Browser-BC server upload calls in `upload/runner.ts` with the CommandCenter client while preserving
Dexie manifests and retry behavior. Update background messages so `start-recording` accepts objective and
profile, and `stop-recording` returns immediately after the CommandCenter `202` acknowledgement with a
recording id that can be polled.

- [ ] **Step 7: Run lifecycle tests and build**

```powershell
cd browser_extension
pnpm test -- command-center-client.test.ts command-center-session.test.ts upload-runner.test.ts recorder.test.ts
pnpm typecheck
pnpm build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add browser_extension/src/command-center browser_extension/src/entrypoints/background.ts browser_extension/src/recording/recorder.ts browser_extension/src/upload/runner.ts browser_extension/tests
git commit -m "feat: connect browser recorder lifecycle to command center"
```

### Task 5: Provide the Minimal Recording and Result UI

**Files:**
- Modify: `browser_extension/src/entrypoints/popup/App.tsx`
- Modify: `browser_extension/src/styles.css`
- Test: `browser_extension/tests/command-center-popup.test.tsx`
- Replace: `browser_extension/README.md`

**Interfaces:**
- Consumes: profile selection and coordinator status.
- Produces: objective entry, start/stop controls, local upload state, and CommandCenter learning result link/status.

- [ ] **Step 1: Write failing popup behavior tests**

Assert the popup:

```ts
expect(screen.getByLabelText('演示目标')).toBeVisible();
expect(screen.getByText('益丰 MES')).toBeVisible();
expect(screen.getByRole('button', { name: '开始录制' })).toBeEnabled();
expect(screen.queryByText(/同时观察 API/)).not.toBeInTheDocument();
expect(screen.queryByText(/debugger/i)).not.toBeInTheDocument();
```

Test visible states for `recording`, `pending_upload`, `learning`, `published`, `browser_candidate`, and
`failed`.

- [ ] **Step 2: Run and verify RED**

```powershell
cd browser_extension
pnpm test -- command-center-popup.test.tsx
```

Expected: FAIL because the upstream popup does not expose the CommandCenter workflow.

- [ ] **Step 3: Implement the minimal popup**

Keep only profile, exact selected origin, objective, start, stop, local upload state, recording id, and final
learning status. Do not add an administrator review workflow or Browser-BC bucket/Claude installation UI.

- [ ] **Step 4: Update installation and safety documentation**

Document:

- `pnpm install`, `pnpm build`, and loading `browser_extension/dist/chrome-mv3`;
- starting FastAPI with `conda run -n langgraph`;
- read-only MES test boundaries;
- status recovery after refresh;
- the limitation that injected hooks observe page JavaScript traffic, not every browser or Service Worker request.

- [ ] **Step 5: Run UI tests and build**

```powershell
cd browser_extension
pnpm test -- command-center-popup.test.tsx
pnpm test
pnpm typecheck
pnpm build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add browser_extension/src/entrypoints/popup browser_extension/src/styles.css browser_extension/tests/command-center-popup.test.tsx browser_extension/README.md
git commit -m "feat: add command center recording controls"
```

### Task 6: Verify the API Skill Vertical Slice

**Files:**
- Modify only if a real contract defect is found: `app/command_center/router.py`, `schemas.py`, `service.py`, `extension_recorder.py`
- Test: `tests/test_browser_bc_extension_contract.py`
- Test: `tests/test_real_mes_readonly_loop.py`
- Modify: `docs/architecture/browser-recording-dual-path.md`

**Interfaces:**
- Consumes: built extension and existing FastAPI/LangGraph learning pipeline.
- Produces: verified automated evidence that a Browser-BC trace reaches the API Skill learning path.

- [ ] **Step 1: Run the focused backend integration loop**

```powershell
conda run -n langgraph python -m pytest tests/test_browser_bc_extension_contract.py tests/test_extension_recorder.py tests/test_command_center_service.py tests/test_real_mes_readonly_loop.py -q
```

Expected: PASS. If it fails, classify the failure before changing behavior: implementation defect, missing agent
context/tool, prompt defect, model protocol violation, fixture defect, or invalid test assumption.

- [ ] **Step 2: Run the complete extension verification**

```powershell
cd browser_extension
pnpm test
pnpm typecheck
pnpm build
```

Expected: all tests pass, type-check exits 0, and WXT emits `dist/chrome-mv3`.

- [ ] **Step 3: Inspect the built manifest**

```powershell
Get-Content browser_extension\dist\chrome-mv3\manifest.json
```

Assert it contains the configured HTTP/HTTPS capture permissions and does not contain `debugger`.

- [ ] **Step 4: Run the complete CommandCenter verification**

```powershell
conda run -n langgraph python -m pytest -q
cd frontend
npm test
npm run build
```

Expected: all backend and frontend tests pass and the frontend production build exits 0.

- [ ] **Step 5: Update architecture status with verified facts**

Move implemented items out of “尚未完成”. Record the exact automated tests completed and leave isolated
Browser Operator verification as the next-stage gap. Do not claim a real MES recording until a human has
loaded the built extension and performed the read-only demonstration.

- [ ] **Step 6: Commit final integration evidence**

```powershell
git add app tests docs browser_extension frontend
git commit -m "feat: complete Browser-BC API recording loop"
```
