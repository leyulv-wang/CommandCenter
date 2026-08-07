# Query Parameter Fingerprint Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add privacy-preserving query-value equality evidence so agents can map recorded UI values to API query parameters without receiving raw values.

**Architecture:** The existing extension evidence converter computes an HMAC for each query value using the recording fingerprint key and uploads a parameter-to-fingerprint-list mapping. Pydantic validates the protocol, and the field-mapping agent interprets equality together with UI semantics and timing. When later browser-candidate fallback crashes, the service preserves the earlier structured API rejection reasons instead of replacing them with a generic message.

**Tech Stack:** WXT, TypeScript, Vitest, FastAPI, Pydantic, LangGraph, pytest

## Global Constraints

- Never upload or persist raw query parameter values.
- Never capture Cookie, Authorization, Token, request headers, response headers, request bodies, or response bodies through the `webRequest` fallback.
- Do not add MES paths, parameter names, button labels, keyword matching, timing thresholds, or business-specific branches.
- Agents decide semantic field mapping; deterministic code validates protocol, privacy, references, and Tool boundaries.
- Use `conda run -n langgraph` for Python commands and `pnpm` for browser extension commands.
- Work directly on `main`; do not create a branch or dispatch subagents.

---

### Task 1: Extension query fingerprint evidence

**Files:**
- Modify: `browser_extension/src/command-center/evidence.ts`
- Modify: `browser_extension/tests/command-center-evidence.test.ts`

**Interfaces:**
- Consumes: `createEvidenceConverter({ allowedOrigins, fingerprintKey })` and `NetworkRequestEvent.full_url`.
- Produces: `CommandCenterNetworkExchange.query_parameter_fingerprints: Record<string, string[]>`.

- [ ] **Step 1: Write failing conversion tests**

Extend the completed GET exchange test with `applyBy=alice&tag=a&tag=b&empty=` and assert:

```ts
const exchange = batch?.events[1];
expect(exchange).toMatchObject({
  query_parameter_names: ['applyBy', 'empty', 'tag'],
  query_parameter_fingerprints: {
    applyBy: [expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/)],
    tag: [
      expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/),
      expect.stringMatching(/^hmac-sha256:[0-9a-f]{64}$/),
    ],
  },
});
expect(exchange.query_parameter_fingerprints.empty).toBeUndefined();
expect(JSON.stringify(batch)).not.toContain('alice');
```

Add a page input action with value `alice` and assert its `value_fingerprint` equals the fingerprint for `applyBy`. Assert the two repeated `tag` fingerprints differ.

- [ ] **Step 2: Verify RED**

Run:

```powershell
cd browser_extension
pnpm test -- tests/command-center-evidence.test.ts
```

Expected: FAIL because `query_parameter_fingerprints` is absent.

- [ ] **Step 3: Implement minimal conversion**

Add the property to `CommandCenterNetworkExchange`. In `convertExchange`, iterate unique valid parameter names, call `url.searchParams.getAll(name)`, discard empty strings, HMAC each remaining value with the existing `fingerprint()` function, and include only non-empty lists. Increment `fingerprintedValueCount` for every emitted query fingerprint. Never place raw values in the returned object.

- [ ] **Step 4: Verify GREEN**

Run the same test plus typecheck:

```powershell
pnpm test -- tests/command-center-evidence.test.ts
pnpm run typecheck
```

Expected: all selected tests pass and TypeScript exits 0.

- [ ] **Step 5: Commit**

```powershell
git add browser_extension/src/command-center/evidence.ts browser_extension/tests/command-center-evidence.test.ts
git commit -m "feat: fingerprint recorded query parameter values"
```

### Task 2: Backend evidence protocol

**Files:**
- Modify: `app/command_center/schemas.py`
- Modify: `app/command_center/extension_recorder.py`
- Modify: `tests/test_command_center_schemas.py`
- Modify: `tests/test_extension_recorder.py`
- Modify: `tests/test_browser_bc_extension_contract.py`

**Interfaces:**
- Consumes: extension `query_parameter_fingerprints` JSON object.
- Produces: `RecordedNetworkExchange.query_parameter_fingerprints: dict[EvidenceIdentifier, list[EvidenceFingerprint]]` and the same field in finalized trace exchanges.

- [ ] **Step 1: Write failing schema and recorder tests**

Add a valid batch containing:

```python
"query_parameter_fingerprints": {
    "applyBy": ["hmac-sha256:" + "a" * 64],
    "tag": ["hmac-sha256:" + "b" * 64, "hmac-sha256:" + "c" * 64],
}
```

Assert validation and finalized trace preserve the mapping. Add invalid cases for an illegal parameter name and a non-HMAC value. Assert raw sample text is absent from serialized output.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:CONDA_NO_PLUGINS='true'
conda run -n langgraph python -m pytest tests/test_command_center_schemas.py tests/test_extension_recorder.py tests/test_browser_bc_extension_contract.py -q
```

Expected: FAIL because the strict evidence model rejects the new field.

- [ ] **Step 3: Implement minimal protocol support**

Add the typed dictionary field with `default_factory=dict` to `RecordedNetworkExchange`. In `ExtensionRecorder.stop`, copy `item.query_parameter_fingerprints` into each trace exchange next to `query_parameter_names`. Do not transform fingerprints into values.

- [ ] **Step 4: Verify GREEN and compatibility**

Run the same three test files. Existing payloads without the field must remain valid and produce an empty mapping.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/schemas.py app/command_center/extension_recorder.py tests/test_command_center_schemas.py tests/test_extension_recorder.py tests/test_browser_bc_extension_contract.py
git commit -m "feat: accept query fingerprints in recording evidence"
```

### Task 3: Agent evidence guidance and safe failure preservation

**Files:**
- Modify: `app/command_center/agents.py`
- Modify: `app/command_center/service.py`
- Modify: `tests/test_structured_agents.py`
- Modify: `tests/test_command_center_service.py`

**Interfaces:**
- Consumes: trace exchanges containing `query_parameter_fingerprints` and an optional earlier `api_learning_result.failure_reasons`.
- Produces: agent guidance that uses fingerprint equality as evidence and sanitized actionable failure reasons when browser fallback crashes.

- [ ] **Step 1: Write failing prompt and service tests**

Assert the field-mapping prompt states that equal HMAC fingerprints are equality evidence, must be combined with semantic and temporal evidence, and unequal/missing fingerprints must not be guessed.

Create a service fixture whose API learning returns `rejected` with `failure_reasons=["字段对应关系证据不足"]`, then whose browser distiller raises. Assert the final status remains `needs_reteach` but `failure_reasons` contains the structured API reason rather than only the generic system message.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:CONDA_NO_PLUGINS='true'
conda run -n langgraph python -m pytest tests/test_structured_agents.py tests/test_command_center_service.py -q
```

Expected: prompt assertion and preserved-reason assertion fail.

- [ ] **Step 3: Implement the agent prompt**

Extend only `AgentSuite.map_fields` guidance: matching fingerprints prove value equality but not business meaning; the agent must combine equality with control semantics, sequence, Tool schema, and API attribution. Explicitly prohibit mapping from names alone.

- [ ] **Step 4: Implement safe failure preservation**

Add a small private helper in `service.py` that extracts at most five non-empty strings, each at most 300 characters, from `api_learning_result.failure_reasons`. In the analysis exception handler, use these already-structured reasons when present; otherwise retain the existing generic message. Never expose exception text or model raw output.

- [ ] **Step 5: Verify GREEN**

Run the two selected test files and confirm all pass.

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/agents.py app/command_center/service.py tests/test_structured_agents.py tests/test_command_center_service.py
git commit -m "fix: retain actionable learning failure evidence"
```

### Task 4: Full regression, documentation, and real MES acceptance preparation

**Files:**
- Modify: `browser_extension/README.md`
- Modify: `docs/architecture/browser-recording-dual-path.md`
- Modify: `docs/testing/2026-08-07-http-mes-network-fallback.md`

**Interfaces:**
- Consumes: completed extension/backend protocol and agent behavior.
- Produces: production extension build and documented real-MES acceptance criteria.

- [ ] **Step 1: Run extension regression**

```powershell
cd browser_extension
pnpm test
pnpm run typecheck
pnpm run build
pnpm run test:e2e:local
```

Expected: all unit tests, build, and local read-only recording loop pass.

- [ ] **Step 2: Run backend and frontend regression**

```powershell
$env:CONDA_NO_PLUGINS='true'
conda run -n langgraph python -m pytest -q
cd frontend
npm test -- --run
npm run build
```

Expected: zero test failures and both production builds exit 0.

- [ ] **Step 3: Update documentation**

Document that query values are converted to per-parameter HMAC fingerprints, raw query values never leave the extension conversion boundary, and semantic mapping remains an agent judgment. Record exact test counts and commands from this run.

- [ ] **Step 4: Commit**

```powershell
git add browser_extension/README.md docs/architecture/browser-recording-dual-path.md docs/testing/2026-08-07-http-mes-network-fallback.md
git commit -m "docs: verify private query parameter alignment"
```

- [ ] **Step 5: Prepare real MES acceptance**

Build `browser_extension/dist/chrome-mv3`, ask the user to reload that unpacked extension in Edge, and record one read-only procurement application query. Inspect the newest recording and require: matched `/jeecg-boot/purchase/apply/list`, non-empty query fingerprints for non-empty filters, successful field mapping, and no write exchange.
