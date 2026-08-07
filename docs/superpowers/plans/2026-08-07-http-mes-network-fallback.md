# HTTP MES Network Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make API evidence recording reliable on ordinary HTTP enterprise systems by adding deterministic SHA-256 fallback and a browser `webRequest` metadata channel.

**Architecture:** Page-context Fetch/XHR capture remains the rich primary channel. The extension background records minimal browser request metadata as `browser_web_request`; upload selects primary HTTP events when present and otherwise promotes the fallback channel. This avoids timing heuristics and duplicate API exchanges.

**Tech Stack:** WXT, TypeScript, Chrome MV3 `webRequest`, Dexie, Vitest, Playwright.

## Global Constraints

- Do not record request headers, response headers, cookies, credentials, request bodies, or response bodies in the fallback channel.
- Observe only active-recording tabs and exact allowed origins.
- Do not infer business meaning, Tool identity, or safety from URL text in extension code.
- Backend `SystemProfile.tool_permissions` remains the execution boundary.
- Use `pnpm` for browser extension commands.
- Implement inline in the current session; do not dispatch Codex subagents.

---

### Task 1: HTTP-safe SHA-256

**Files:**
- Modify: `browser_extension/src/shared/hash.ts`
- Modify: `browser_extension/tests/id-hash.test.ts`

**Interfaces:**
- Consumes: `sha256Hex(input: string | ArrayBuffer | Uint8Array | Blob)`.
- Produces: identical SHA-256 hex output whether `crypto.subtle` exists or not.

- [ ] **Step 1: Write the failing Web Crypto absence test**

Stub `globalThis.crypto` without `subtle`, call `sha256Hex('abc')`, and require the standard digest
`ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`.

- [ ] **Step 2: Run the narrow test and verify it fails**

Run: `pnpm test -- tests/id-hash.test.ts`

- [ ] **Step 3: Generalize the synchronous implementation to byte input**

Add `sha256BytesHexSync(bytes: Uint8Array): string`, make `sha256HexSync(string)` delegate to it,
and make `sha256Hex` use it only when `globalThis.crypto?.subtle` is unavailable.

- [ ] **Step 4: Run hash tests and type checking**

Run: `pnpm test -- tests/id-hash.test.ts && pnpm run typecheck`

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/shared/hash.ts browser_extension/tests/id-hash.test.ts
git commit -m "fix: hash evidence on HTTP pages"
```

### Task 2: Browser webRequest metadata recorder

**Files:**
- Create: `browser_extension/src/recording/web-request-fallback.ts`
- Create: `browser_extension/tests/web-request-fallback.test.ts`
- Modify: `browser_extension/src/shared/types.ts`

**Interfaces:**
- Produces: `createWebRequestFallbackRecorder(options)` with `beforeRequest(details)`,
  `completed(details)`, `failed(details)`, and `clear(traceId?)`.
- Adds optional `capture_channel: 'browser_web_request'` to HTTP request/response events.

- [ ] **Step 1: Write failing recorder tests**

Cover a GET request/200 response pair, exact allowed-origin filtering, active-tab filtering, non-HTTP
filtering, error cleanup, and clearing a stopped trace. Assert emitted events contain no headers or bodies.

- [ ] **Step 2: Run the narrow test and verify it fails**

Run: `pnpm test -- tests/web-request-fallback.test.ts`

- [ ] **Step 3: Implement the focused recorder module**

Use browser request ID for deterministic pairing. Read the active context from a callback returning:

```ts
type WebRequestRecordingContext = {
  traceId: string;
  tabIds: ReadonlySet<number>;
  allowedOrigins: readonly string[];
};
```

Emit `network_request` and `network_response` with `capture_channel: 'browser_web_request'`, empty
`req_headers`, no bodies, and timestamps from the provided clock.

- [ ] **Step 4: Run recorder tests and type checking**

Run: `pnpm test -- tests/web-request-fallback.test.ts && pnpm run typecheck`

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/recording/web-request-fallback.ts browser_extension/src/shared/types.ts browser_extension/tests/web-request-fallback.test.ts
git commit -m "feat: record browser request metadata fallback"
```

### Task 3: Deterministic primary-or-fallback upload selection

**Files:**
- Modify: `browser_extension/src/command-center/upload.ts`
- Modify: `browser_extension/tests/command-center-upload.test.ts`

**Interfaces:**
- Produces: `selectCommandCenterNetworkChannel(events: CapturedEvent[]): CapturedEvent[]`.
- Primary channel means HTTP `network_request` without `capture_channel=browser_web_request`.

- [ ] **Step 1: Write failing selection tests**

Test that primary request/response events exclude all browser fallback HTTP pairs, while a trace with no
primary HTTP request retains the fallback pair. Keep UI and non-HTTP stream events in both cases.

- [ ] **Step 2: Run the narrow test and verify it fails**

Run: `pnpm test -- tests/command-center-upload.test.ts`

- [ ] **Step 3: Implement and apply selection before evidence conversion**

Select once for the full trace immediately after reading Dexie events. Do not use URL matching, timing
windows, endpoint names, or status thresholds.

- [ ] **Step 4: Run upload tests and type checking**

Run: `pnpm test -- tests/command-center-upload.test.ts && pnpm run typecheck`

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/command-center/upload.ts browser_extension/tests/command-center-upload.test.ts
git commit -m "fix: promote browser network fallback when needed"
```

### Task 4: Background lifecycle integration

**Files:**
- Modify: `browser_extension/src/entrypoints/background.ts`
- Modify: `browser_extension/tests/background-recording-state.test.ts`
- Modify: `browser_extension/tests/web-request-fallback.test.ts`

**Interfaces:**
- Consumes: `createWebRequestFallbackRecorder` from Task 2.
- Maintains: active trace ID, allowed origins, and the set of successfully connected recording tab IDs.

- [ ] **Step 1: Add failing lifecycle tests**

Verify connected allowed tabs enter the context, created/updated allowed tabs join it, removed tabs leave
it, and stop/failure clears the fallback request map before the next trace.

- [ ] **Step 2: Run the narrow tests and verify they fail**

Run: `pnpm test -- tests/background-recording-state.test.ts tests/web-request-fallback.test.ts`

- [ ] **Step 3: Register webRequest listeners and lifecycle state**

Register `onBeforeRequest`, `onCompleted`, and `onErrorOccurred` once in the background. Forward their
details to the recorder, append emitted events through the existing recorder API, and update the tab set
only after `connectRecordingTab` returns `messaged` or `injected` for an allowed URL.

- [ ] **Step 4: Run lifecycle tests, type checking, and build**

Run: `pnpm test -- tests/background-recording-state.test.ts tests/web-request-fallback.test.ts && pnpm run typecheck && pnpm run build`

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/entrypoints/background.ts browser_extension/tests/background-recording-state.test.ts browser_extension/tests/web-request-fallback.test.ts
git commit -m "feat: connect web request fallback to recordings"
```

### Task 5: Regression verification and documentation

**Files:**
- Modify: `browser_extension/README.md`
- Modify: `docs/architecture/browser-recording-dual-path.md`
- Create: `docs/testing/2026-08-07-http-mes-network-fallback.md`

**Interfaces:**
- Produces: repeatable local commands and a safe real-MES acceptance checklist.

- [ ] **Step 1: Run the local real-extension E2E**

Run: `pnpm run test:e2e:local`
Expected: one pass and no purchase-system data change.

- [ ] **Step 2: Run full regression suites**

Run backend: `conda run -n langgraph python -m pytest -q`

Run extension: `pnpm test && pnpm run typecheck && pnpm run build`

Run frontend: `npm test -- --run && npm run build`

- [ ] **Step 3: Document channel selection and evidence limits**

Record exact test totals, the HTTP failure root cause, and the rule that browser metadata fallback never
captures credentials or bodies.

- [ ] **Step 4: Commit**

```powershell
git add browser_extension/README.md docs/architecture/browser-recording-dual-path.md docs/testing/2026-08-07-http-mes-network-fallback.md
git commit -m "docs: verify HTTP MES network fallback"
```

- [ ] **Step 5: Perform the real MES read-only acceptance**

Reload the unpacked extension, record only the existing “采购申请” query, and verify the backend trace
contains a matched `GET /jeecg-boot/purchase/apply/list` exchange and no write exchange.
