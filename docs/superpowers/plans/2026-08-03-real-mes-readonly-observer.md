# Real MES Readonly Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a test-only browser extension and CommandCenter learning path that records a selected logged-in MES tab, correlates UI fields with allowlisted OpenAPI operations, and produces an automatically verified but unpublished “查询采购申请” Skill without changing MES business data.

**Architecture:** A Manifest V3 extension captures semantic UI events and Chrome DevTools Protocol network events from one explicitly selected tab. It streams sanitized batches to a new extension recorder in FastAPI; a staged LangGraph multi-agent workflow segments the trace, attributes APIs, maps fields, compiles a read-only Skill, and validates it through an explicit read-only MES Tool allowlist. Credentials use a separate ephemeral in-memory channel and never enter recordings, prompts, repositories, or logs.

**Tech Stack:** Python 3 in conda environment `langgraph`, FastAPI, Pydantic, LangGraph, SQLAlchemy, httpx, Chromium Manifest V3 extension, Chrome Debugger API, JavaScript `node:test`.

## Global Constraints

- Run Python commands through `conda run -n langgraph`.
- Only the selected `yifeng.dtsum.com` tab may be observed.
- The first real workflow is采购申请查询和详情查看 only.
- Only explicitly allowlisted method-and-path pairs are read-only; GET is not inherently safe in this MES.
- Allowed verification operations are `GET /jeecg-boot/purchase/apply/list`, `GET /jeecg-boot/purchase/apply/queryById`, and `GET /jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId`.
- Passwords, cookies, `Authorization`, `X-Access-Token`, CAPTCHA values, uploaded file contents, local storage, and unrelated tabs must never enter traces, prompts, repositories, or ordinary logs.
- A captured `X-Access-Token` may exist only in the extension background and the backend ephemeral credential vault; it must be represented as `SecretStr`, never persisted, and cleared after verification or failure.
- The generated real MES Skill ends as `verified_candidate`; it is not returned by the published Skill registry and cannot be called from the ordinary task center.
- Reuse the existing `OperationTrace`, Skill compiler, repository, and LangGraph architecture through adapters; do not copy third-party projects or make a MES-only recorder core.
- Agent judgment owns segmentation, API attribution, semantic field mapping, transformation reasoning, and uncertainty. Deterministic code owns domain isolation, redaction, Tool allowlists, schemas, credentials, timeouts, size limits, evidence integrity, and publication gates.
- The implementation must not create, edit, audit, finish, reverse, or delete any MES business record.

---

## File Structure

### New backend files

- `app/command_center/system_profiles.py`: typed system profile and explicit method/path Tool permissions.
- `app/command_center/openapi_loader.py`: bounded Swagger/OpenAPI loader with cache and profile-to-catalog conversion.
- `app/command_center/redaction.py`: deterministic recursive sanitization and stable value fingerprints.
- `app/command_center/credential_vault.py`: ephemeral `SecretStr` credentials keyed by recording.
- `app/command_center/extension_recorder.py`: extension recording sessions, event ingestion, sequence ordering, and trace finalization.
- `app/command_center/readonly_testing.py`: real-system query-only candidate Skill validation.
- `app/data/system_profiles/yifeng_mes.json`: MES domain, OpenAPI location, limits, and exact read-only Tool allowlist.

### New extension files

- `browser_extension/manifest.json`: Manifest V3 permissions, selected domain, popup, content script, and module service worker.
- `browser_extension/popup.html`, `popup.css`, `popup.mjs`: start/stop UI for the active tab.
- `browser_extension/content.js`: password-safe semantic DOM event capture in the selected tab and its frames.
- `browser_extension/background.mjs`: recording lifecycle, `chrome.debugger` network capture, batching, and credential handoff.
- `browser_extension/shared/protocol.mjs`: message and event builders shared by popup/background tests.
- `browser_extension/shared/redaction.mjs`: extension-side header/body sanitization and size limits.
- `browser_extension/tests/protocol.test.mjs`, `redaction.test.mjs`: dependency-free Node tests.
- `browser_extension/README.md`: unpacked installation and the exact read-only demonstration procedure.

### Existing files to modify

- `app/command_center/schemas.py`: richer trace evidence, staged agent outputs, `query.` bindings, and `verified_candidate` status.
- `app/command_center/tool_catalog.py`: Swagger 2 parameters, explicit side-effect classification, and agent-visible parameter metadata.
- `app/command_center/tool_executor.py`: query parameters and ephemeral credential injection based on Tool metadata.
- `app/command_center/recorder.py`: expose reusable trace builder methods without changing local Playwright behavior.
- `app/command_center/router.py`: extension start, event batch, credential, stop, and candidate Skill endpoints.
- `app/command_center/service.py`: choose Playwright or extension recorder and retain verified candidates.
- `app/command_center/agents.py`: staged agent roles and generic read-only Skill prompts.
- `app/command_center/learning_graph.py`: segmentation → attribution → mapping → compilation → read-only testing → verified candidate.
- `app/command_center/repository.py`: list verified candidates separately while preserving published-only execution.
- `app/main.py`: compose profile loader, extension recorder, credential vault, and read-only tester.

### Tests to add or modify

- `tests/test_system_profiles.py`
- `tests/test_openapi_loader.py`
- `tests/test_redaction.py`
- `tests/test_credential_vault.py`
- `tests/test_extension_recorder.py`
- `tests/test_command_center_schemas.py`
- `tests/test_tool_catalog.py`
- `tests/test_tool_executor.py`
- `tests/test_structured_agents.py`
- `tests/test_learning_graph.py`
- `tests/test_readonly_testing.py`
- `tests/test_command_center_api.py`
- `tests/test_command_center_service.py`
- `tests/test_real_mes_readonly_loop.py`

---

### Task 1: Add the typed MES profile and exact read-only Tool boundary

**Files:**
- Create: `app/command_center/system_profiles.py`
- Create: `app/data/system_profiles/yifeng_mes.json`
- Create: `tests/test_system_profiles.py`

**Interfaces:**
- Produces: `SystemProfile`, `ToolPermission`, `ProfileLimits`, `load_system_profile(path: Path) -> SystemProfile`.
- `ToolPermission` identifies one Tool by `method`, `path`, and `side_effect: Literal["read", "write"]`.
- Later tasks consume `SystemProfile.is_allowed(method, path)` and `SystemProfile.permission_for(method, path)`.

- [ ] **Step 1: Write the failing profile tests**

```python
def test_yifeng_profile_only_allows_three_read_operations():
    profile = load_system_profile(
        Path("app/data/system_profiles/yifeng_mes.json")
    )

    assert profile.system_code == "yifeng_mes"
    assert profile.allowed_hosts == {"yifeng.dtsum.com"}
    assert profile.permission_for(
        "GET", "/jeecg-boot/purchase/apply/list"
    ).side_effect == "read"
    assert profile.permission_for(
        "GET", "/jeecg-boot/purchase/apply/audit"
    ) is None
    assert profile.permission_for(
        "POST", "/jeecg-boot/purchase/apply/add"
    ) is None


def test_profile_rejects_wildcard_permissions():
    payload = valid_profile_payload()
    payload["tool_permissions"] = [
        {"method": "GET", "path": "/jeecg-boot/*", "side_effect": "read"}
    ]

    with pytest.raises(ValidationError):
        SystemProfile.model_validate(payload)
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_system_profiles.py -q`

Expected: FAIL because `system_profiles.py` and the MES profile do not exist.

- [ ] **Step 3: Implement strict profile types and the MES JSON**

```python
class ToolPermission(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    side_effect: Literal["read", "write"]

    @field_validator("path")
    @classmethod
    def exact_path_only(cls, value: str) -> str:
        if not value.startswith("/") or "*" in value:
            raise ValueError("tool permission must use an exact absolute path")
        return value


class SystemProfile(BaseModel):
    system_code: str
    display_name: str
    allowed_hosts: set[str]
    openapi_url: HttpUrl
    base_url: HttpUrl
    api_path_prefix: str
    credential_header: Literal["X-Access-Token"]
    limits: ProfileLimits
    value_capture_policy: Literal["fingerprint_by_default"]
    sensitive_field_patterns: list[str]
    tool_permissions: list[ToolPermission]

    def permission_for(self, method: str, path: str) -> ToolPermission | None:
        return next(
            (
                item
                for item in self.tool_permissions
                if item.method == method.upper() and item.path == path
            ),
            None,
        )

    def is_allowed(self, method: str, path: str) -> bool:
        return self.permission_for(method, path) is not None
```

The JSON must contain exactly the three method/path pairs listed in Global Constraints and no write permissions. It must set `value_capture_policy` to `fingerprint_by_default`; raw values are allowed only when the popup marks an explicitly entered synthetic demonstration value as safe for the current recording.

- [ ] **Step 4: Run tests and verify success**

Run: `conda run -n langgraph python -m pytest tests/test_system_profiles.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/system_profiles.py app/data/system_profiles/yifeng_mes.json tests/test_system_profiles.py
git commit -m "feat: add strict MES readonly profile"
```

### Task 2: Parse Swagger 2 into a parameter-aware, side-effect-aware Tool catalog

**Files:**
- Create: `app/command_center/openapi_loader.py`
- Modify: `app/command_center/tool_catalog.py`
- Create: `tests/test_openapi_loader.py`
- Modify: `tests/test_tool_catalog.py`

**Interfaces:**
- Consumes: `SystemProfile` from Task 1.
- Produces: `OpenAPIDocumentLoader.load(profile: SystemProfile) -> dict[str, Any]` and `ToolCatalog.from_system_profile(document, profile)`.
- Extends `ToolDefinition` with `description`, `side_effect`, `query_parameters`, `body_schema`, and `credential_header`.

- [ ] **Step 1: Add failing Swagger 2 catalog tests**

```python
def test_swagger2_query_parameters_enter_allowlisted_tool():
    profile = profile_for(
        "GET", "/jeecg-boot/purchase/apply/list", side_effect="read"
    )
    document = {
        "swagger": "2.0",
        "paths": {
            "/jeecg-boot/purchase/apply/list": {
                "get": {
                    "operationId": "listPurchaseApply",
                    "summary": "采购申请-分页列表查询",
                    "parameters": [
                        {"name": "applyNo", "in": "query", "type": "string"}
                    ],
                }
            },
            "/jeecg-boot/purchase/apply/audit": {
                "get": {"operationId": "auditPurchaseApply"}
            },
        },
    }

    catalog = ToolCatalog.from_system_profile(document, profile)
    tool = catalog.get("yifeng_mes:listPurchaseApply")

    assert tool.side_effect == "read"
    assert tool.query_parameters["applyNo"].type == "string"
    with pytest.raises(KeyError):
        catalog.get("yifeng_mes:auditPurchaseApply")
```

- [ ] **Step 2: Add failing bounded-loader tests**

Test `Content-Type`, status code, maximum document bytes, timeout, and a cache keyed by profile/OpenAPI URL. Use `httpx.MockTransport`; never call the real MES in automated tests.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_openapi_loader.py tests/test_tool_catalog.py -q`

Expected: FAIL because Swagger 2 parameters and explicit side effects are unsupported.

- [ ] **Step 4: Implement minimal loader and catalog conversion**

```python
@dataclass(frozen=True)
class ToolParameter:
    name: str
    location: Literal["query", "path", "body"]
    type: str | None
    required: bool
    description: str | None


@dataclass(frozen=True)
class ToolDefinition:
    # preserve existing fields
    description: str | None
    side_effect: Literal["read", "write"]
    query_parameters: dict[str, ToolParameter]
    body_schema: dict[str, Any]
    credential_header: str | None
```

Only operations explicitly present in `profile.tool_permissions` become Tools. A GET omitted from the profile must not appear in the catalog.

- [ ] **Step 5: Run focused and regression tests**

Run: `conda run -n langgraph python -m pytest tests/test_openapi_loader.py tests/test_tool_catalog.py tests/test_recorder.py -q`

Expected: PASS, including existing OpenAPI 3 local Tool catalog behavior.

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/openapi_loader.py app/command_center/tool_catalog.py tests/test_openapi_loader.py tests/test_tool_catalog.py tests/test_recorder.py
git commit -m "feat: support allowlisted Swagger tools"
```

### Task 3: Add deterministic redaction, fingerprints, and ephemeral credentials

**Files:**
- Create: `app/command_center/redaction.py`
- Create: `app/command_center/credential_vault.py`
- Create: `tests/test_redaction.py`
- Create: `tests/test_credential_vault.py`

**Interfaces:**
- Produces: `TraceRedactor.redact_headers`, `TraceRedactor.redact_payload`, `TraceRedactor.fingerprint`.
- Produces: `EphemeralCredentialVault.put(recording_id, header, secret)`, `.headers_for(recording_id)`, `.clear(recording_id)`.
- The vault returns a fresh plain header dictionary only at request-send time; no method exposes all stored credentials.

- [ ] **Step 1: Write failing redaction tests**

```python
def test_redactor_removes_credentials_and_fingerprints_sensitive_values():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    assert redactor.redact_headers(
        {"X-Access-Token": "secret", "Content-Type": "application/json"}
    ) == {"Content-Type": "application/json"}
    assert redactor.redact_payload(
        {"password": "pw", "supplierName": "江苏测试公司"},
        sensitive_paths={"supplierName"},
    ) == {
        "password": "[REDACTED]",
        "supplierName": {"fingerprint": redactor.fingerprint("江苏测试公司")},
    }
```

- [ ] **Step 2: Write failing credential lifecycle tests**

```python
def test_ephemeral_credential_is_masked_and_cleared():
    vault = EphemeralCredentialVault()
    recording_id = uuid4()
    vault.put(recording_id, "X-Access-Token", SecretStr("secret"))

    assert vault.headers_for(recording_id) == {"X-Access-Token": "secret"}
    assert "secret" not in repr(vault)
    vault.clear(recording_id)
    assert vault.headers_for(recording_id) == {}
```

- [ ] **Step 3: Run tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_redaction.py tests/test_credential_vault.py -q`

- [ ] **Step 4: Implement recursive, size-bounded sanitization and in-memory vault**

Use HMAC-SHA256 for stable local fingerprints. Reject payloads deeper than the configured depth, truncate arrays/strings by profile limits, and replace sensitive-key values rather than logging or raising with the value included.

- [ ] **Step 5: Run tests and verify success**

Run: `conda run -n langgraph python -m pytest tests/test_redaction.py tests/test_credential_vault.py -q`

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/redaction.py app/command_center/credential_vault.py tests/test_redaction.py tests/test_credential_vault.py
git commit -m "feat: protect recorder evidence and credentials"
```

### Task 4: Extend trace schemas for extension evidence and query bindings

**Files:**
- Modify: `app/command_center/schemas.py`
- Modify: `tests/test_command_center_schemas.py`

**Interfaces:**
- Produces: `ControlDescriptor`, `PageMutationEvidence`, `RecordedBrowserEvent`, `RecordedNetworkExchange`, `ExtensionEventBatch`.
- Extends `OperationTrace` with `capture_source`, `page_mutations`, and `redaction_summary` while preserving defaults for old traces.
- Extends Skill binding targets to `body.`, `path.`, and `query.`.
- Extends Skill status with `verified_candidate`.

- [ ] **Step 1: Write failing backward-compatibility and security tests**

```python
def test_old_operation_trace_remains_valid():
    trace = OperationTrace.model_validate(existing_trace_payload())
    assert trace.capture_source == "playwright"


def test_extension_batch_requires_one_recording_and_monotonic_client_sequence():
    with pytest.raises(ValidationError):
        ExtensionEventBatch.model_validate(batch_with_duplicate_sequence())


def test_skill_step_accepts_query_binding():
    step = valid_skill_step().model_copy(
        update={"input_bindings": {"query.applyNo": "literal.apply_no"}}
    )
    assert SkillStep.model_validate(step).input_bindings
```

- [ ] **Step 2: Run tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_schemas.py -q`

- [ ] **Step 3: Implement additive schemas**

Keep raw extension events out of agent payloads. Convert them to existing `UIEvent` and `APIExchange` plus additive evidence models during ingestion. Do not add arbitrary executable mapping expressions.

- [ ] **Step 4: Run schema and Skill runner tests**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_schemas.py tests/test_skill_runner.py -q`

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/schemas.py tests/test_command_center_schemas.py tests/test_skill_runner.py
git commit -m "feat: model extension traces and query skills"
```

### Task 5: Build the test-only Manifest V3 recorder shell

**Files:**
- Create: `browser_extension/manifest.json`
- Create: `browser_extension/popup.html`
- Create: `browser_extension/popup.css`
- Create: `browser_extension/popup.mjs`
- Create: `browser_extension/content.js`
- Create: `browser_extension/shared/protocol.mjs`
- Create: `browser_extension/tests/protocol.test.mjs`

**Interfaces:**
- Produces extension messages `CC_START_CAPTURE`, `CC_STOP_CAPTURE`, and `CC_UI_EVENT`.
- `buildUIEvent(input) -> sanitized event object` never accepts a password value.
- Popup only enables start when the active tab host exactly matches the profile host.

- [ ] **Step 1: Write failing dependency-free protocol tests**

```javascript
test('password controls never carry values', () => {
  const event = buildUIEvent({
    actionType: 'input',
    control: { type: 'password', label: '密码' },
    valueBefore: '',
    valueAfter: 'secret',
  });
  assert.equal(event.valueBefore, null);
  assert.equal(event.valueAfter, null);
});

test('semantic control context is retained', () => {
  const event = buildUIEvent({
    actionType: 'input',
    control: { type: 'number', label: '数量', section: '采购申请明细' },
    valueBefore: '',
    valueAfter: '10',
  });
  assert.equal(event.control.label, '数量');
});
```

- [ ] **Step 2: Run Node tests and verify failure**

Run: `node --test browser_extension/tests/protocol.test.mjs`

Expected: FAIL because extension files do not exist.

- [ ] **Step 3: Implement the minimal popup and content capture**

The content script listens in the capture phase for `click`, `input`, `change`, and `submit`. It describes the nearest business control using tag, role, accessible name, associated label, placeholder, table column, row position, dialog title, and section heading. It sends final value transitions, not individual keystrokes.

A bounded `MutationObserver` records only semantic local changes: visible alert/toast text, dialog open/close, selected tab or section changes, and row identifiers represented by fingerprints. It must ignore animation/style churn and stop observing when capture stops.

The manifest must use `activeTab`, `scripting`, and host permission only for `http://yifeng.dtsum.com/*` in the test version. Set `all_frames: true` for the content script so same-host application frames are represented.

- [ ] **Step 4: Run tests and syntax checks**

Run: `node --test browser_extension/tests/protocol.test.mjs`

Run: `node --check browser_extension/popup.mjs`

Run: `node --check browser_extension/content.js`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add browser_extension
git commit -m "feat: add selected-tab recorder extension"
```

### Task 6: Capture and sanitize selected-tab network evidence

**Files:**
- Create: `browser_extension/background.mjs`
- Create: `browser_extension/shared/redaction.mjs`
- Create: `browser_extension/tests/redaction.test.mjs`
- Modify: `browser_extension/manifest.json`
- Modify: `browser_extension/popup.mjs`

**Interfaces:**
- Background functions: `attachToTab(tabId)`, `detachFromTab(tabId)`, `flushBatch()`, `handoffCredential(name, value)`.
- Observes `Network.requestWillBeSent`, `Network.requestWillBeSentExtraInfo`, `Network.responseReceived`, and `Network.loadingFinished` for one tab.
- Sends sanitized evidence batches; sends the token only through the dedicated credential endpoint.

- [ ] **Step 1: Write failing extension redaction tests**

```javascript
test('credential headers are removed from evidence', () => {
  assert.deepEqual(
    sanitizeHeaders({
      'X-Access-Token': 'secret',
      'Content-Type': 'application/json',
    }),
    { 'Content-Type': 'application/json' },
  );
});

test('response summaries obey the byte limit', () => {
  const result = summarizeBody('x'.repeat(100), 16);
  assert.equal(result.truncated, true);
  assert.equal(result.body.length <= 16, true);
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `node --test browser_extension/tests/redaction.test.mjs`

- [ ] **Step 3: Implement debugger lifecycle and network correlation**

Maintain an in-memory map by CDP `requestId`. Parse JSON bodies only below the configured byte limit. Never call `Network.getResponseBody` for static assets, downloads, or responses above the limit. On navigation away from the exact host, flush, detach, and mark the recording paused.

When `requestWillBeSentExtraInfo` contains `X-Access-Token`, keep it in extension memory, remove it from evidence, and hand it to the dedicated backend credential route authenticated by the recording ingest token.

- [ ] **Step 4: Verify tests and syntax**

Run: `node --test browser_extension/tests`

Run: `node --check browser_extension/background.mjs`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add browser_extension
git commit -m "feat: capture sanitized tab network evidence"
```

### Task 7: Add authenticated extension recording ingestion

**Files:**
- Create: `app/command_center/extension_recorder.py`
- Modify: `app/command_center/recorder.py`
- Modify: `app/command_center/router.py`
- Modify: `app/command_center/service.py`
- Create: `tests/test_extension_recorder.py`
- Modify: `tests/test_command_center_api.py`
- Modify: `tests/test_command_center_service.py`

**Interfaces:**
- Produces `ExtensionRecorder.start(recording_id, objective, source_task, profile) -> IngestGrant`.
- Produces `ingest(recording_id, batch, token)`, `put_credential(recording_id, name, secret, token)`, and `stop(recording_id, token) -> OperationTrace`.
- HTTP routes:
  - `POST /recordings/{id}/extension/start`
  - `POST /recordings/{id}/extension/events`
  - `PUT /recordings/{id}/extension/credential`
  - `POST /recordings/{id}/extension/stop`
- Each route requires `X-CommandCenter-Recording-Token`; plaintext token is returned only from start and only its SHA-256 digest is retained for validation.

- [ ] **Step 1: Write failing recorder tests**

```python
def test_extension_recorder_orders_events_and_matches_allowlisted_api():
    grant = recorder.start(recording_id, "查询采购申请", {}, profile)
    recorder.ingest(recording_id, batch_with_ui_then_list_request(), grant.token)

    trace = recorder.stop(recording_id, grant.token)

    assert trace.capture_source == "browser_extension"
    assert trace.ui_events[0].sequence < trace.api_exchanges[0].sequence
    assert trace.api_exchanges[0].matched_tool_id.endswith("listPurchaseApply")
```

Add tests for bad token, duplicate batch ID, sequence conflicts, wrong host, non-allowlisted audit request retained as `not_allowed`, token header absent from serialized trace, and vault cleanup after stop failure.

- [ ] **Step 2: Write failing API lifecycle tests**

Start an extension recording, post one batch, hand off a `SecretStr` credential, and stop. Assert no endpoint response or persisted recording includes the raw credential.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_extension_recorder.py tests/test_command_center_api.py tests/test_command_center_service.py -q`

- [ ] **Step 4: Implement the extension session adapter and routes**

Use the existing `OperationTraceBuilder` to create normalized `UIEvent` and `APIExchange` instances. The extension recorder owns only browser-extension sessions; existing Playwright `RecorderService.start/stop` behavior stays unchanged.

The service selects the recorder from an explicit `capture_source` saved at recording creation. This is a protocol boundary, not an agent judgment.

- [ ] **Step 5: Run focused and old recorder tests**

Run: `conda run -n langgraph python -m pytest tests/test_extension_recorder.py tests/test_recorder.py tests/test_command_center_api.py tests/test_command_center_service.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/extension_recorder.py app/command_center/recorder.py app/command_center/router.py app/command_center/service.py tests/test_extension_recorder.py tests/test_command_center_api.py tests/test_command_center_service.py
git commit -m "feat: ingest browser extension recordings"
```

### Task 8: Split demonstration learning into staged agent judgments

**Files:**
- Modify: `app/command_center/schemas.py`
- Modify: `app/command_center/agents.py`
- Modify: `app/command_center/learning_graph.py`
- Modify: `tests/test_structured_agents.py`
- Modify: `tests/test_learning_graph.py`

**Interfaces:**
- Produces `TraceSegmentation`, `APIAttributionAnalysis`, and `FieldMappingAnalysis` Pydantic outputs.
- `AgentSuite.segment_trace(trace) -> TraceSegmentation`.
- `AgentSuite.attribute_apis(segmentation, trace, catalog) -> APIAttributionAnalysis`.
- `AgentSuite.map_fields(attribution, trace, catalog) -> FieldMappingAnalysis`.
- `AgentSuite.compile_skill(mapping, attribution, trace, catalog) -> SkillDefinition`.

- [ ] **Step 1: Write failing structured-output tests**

```python
def test_api_attribution_requires_evidence_ids_from_trace():
    attribution = APIAttributionAnalysis.model_validate(
        valid_attribution_payload()
    )
    assert attribution.segments[0].primary_tool_ids == [
        "yifeng_mes:listPurchaseApply"
    ]


def test_field_mapping_can_target_query_parameter():
    mapping = FieldMappingAnalysis.model_validate(
        {
            "mappings": [
                {
                    "skill_input_name": "apply_no",
                    "api_target": "query.applyNo",
                    "source_ui_event_ids": [str(uuid4())],
                    "source_exchange_ids": [str(uuid4())],
                    "transformation": "identity",
                    "evidence_summary": "页面申请单号与请求 applyNo 相同",
                }
            ],
            "uncertainties": [],
            "compilable": True,
        }
    )
    assert mapping.mappings[0].api_target == "query.applyNo"
```

- [ ] **Step 2: Write failing graph-order tests**

Use fake agents that append calls. Assert exact order `segment_trace`, `attribute_apis`, `map_fields`, `compile_skill`, and that an inconclusive stage stops before compilation with its evidence-based reasons.

- [ ] **Step 3: Run tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_structured_agents.py tests/test_learning_graph.py -q`

- [ ] **Step 4: Implement staged schemas, prompts, and LangGraph nodes**

Prompts must be system-generic and receive the profile/catalog. They must explicitly distinguish primary business API, supporting lookup, verification query, static/telemetry traffic, and uncertain candidates. They must not contain MES-specific keyword branches in Python.

Before accepting each structured result, deterministic validation checks that every referenced UI event, exchange, segment, and Tool exists. Invalid references reject the analysis; code does not replace the agent’s semantic choice.

- [ ] **Step 5: Run focused tests and existing vertical-loop regressions**

Run: `conda run -n langgraph python -m pytest tests/test_structured_agents.py tests/test_learning_graph.py tests/test_v1_vertical_loop.py -q`

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/schemas.py app/command_center/agents.py app/command_center/learning_graph.py tests/test_structured_agents.py tests/test_learning_graph.py tests/test_v1_vertical_loop.py
git commit -m "feat: stage demonstration learning agents"
```

### Task 9: Execute query bindings with ephemeral credentials and explicit read safety

**Files:**
- Modify: `app/command_center/tool_executor.py`
- Modify: `app/command_center/testing.py`
- Create: `app/command_center/readonly_testing.py`
- Modify: `tests/test_tool_executor.py`
- Create: `tests/test_readonly_testing.py`

**Interfaces:**
- `ToolExecutor` accepts `credential_provider: Callable[[str], dict[str, str]]` and includes `query` arguments as HTTP `params`.
- Side effects and retry safety come from `ToolDefinition.side_effect`, never from HTTP method.
- `ReadOnlySkillTestService.run(skill, case) -> dict[str, Any]` rejects every write Tool before execution.

- [ ] **Step 1: Write failing executor tests**

```python
def test_executor_sends_query_and_ephemeral_token_without_logging_secret():
    executor = ToolExecutor(
        catalog,
        client,
        credential_provider=lambda _: {"X-Access-Token": "secret"},
    )
    result = executor.execute(command_with_query_apply_no())

    assert observed["query"] == {"applyNo": "CGSQ001"}
    assert observed["token"] == "secret"
    assert "secret" not in json.dumps(result.model_dump(mode="json"))
    assert result.side_effect == {"occurred": False}
```

Add a regression test proving an allowlisted GET declared `side_effect="write"` is treated as a write and is not retry-safe without protection.

- [ ] **Step 2: Write failing read-only test service tests**

Test normal query, parameter variation, repeated query, response contract verification, write Tool rejection before request, missing credential, and credential cleanup.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_tool_executor.py tests/test_readonly_testing.py -q`

- [ ] **Step 4: Implement query execution and query-only verification**

The read-only verifier may accept changed result counts because other employees can use the MES concurrently. It verifies: all executed Tools are explicitly read, HTTP/schema contracts are valid, repeated identical query has no CommandCenter side effect, and the response contains the expected structural fields. It must not claim global MES immutability from a row count comparison.

- [ ] **Step 5: Run focused and harmless-test regressions**

Run: `conda run -n langgraph python -m pytest tests/test_tool_executor.py tests/test_readonly_testing.py tests/test_harmless_testing.py tests/test_skill_runner.py -q`

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/tool_executor.py app/command_center/testing.py app/command_center/readonly_testing.py tests/test_tool_executor.py tests/test_readonly_testing.py tests/test_harmless_testing.py tests/test_skill_runner.py
git commit -m "feat: validate readonly query skills safely"
```

### Task 10: Stop real MES learning at `verified_candidate`

**Files:**
- Modify: `app/command_center/learning_graph.py`
- Modify: `app/command_center/repository.py`
- Modify: `app/command_center/service.py`
- Modify: `app/command_center/router.py`
- Modify: `tests/test_learning_graph.py`
- Modify: `tests/test_command_center_repository.py`
- Modify: `tests/test_command_center_service.py`
- Modify: `tests/test_command_center_api.py`

**Interfaces:**
- `LearningDependencies.publish_policy: Literal["auto_publish", "verified_candidate"]`.
- `CommandCenterRepository.mark_verified_candidate(skill_id, version)`.
- `CommandCenterRepository.list_verified_candidates()`.
- `GET /skills?status=verified_candidate` exposes candidates for inspection; default `/skills` stays published-only.

- [ ] **Step 1: Write failing publication-boundary tests**

```python
def test_real_mes_skill_stops_after_readonly_tests():
    result = graph_with_policy("verified_candidate").invoke(valid_state())

    assert result["final_status"] == "verified_candidate"
    assert result["candidate_skill"].status == "verified_candidate"
    assert repository.list_published_skills() == []
    assert len(repository.list_verified_candidates()) == 1
```

Add a regression test proving the local test-system policy still auto-publishes after its three existing harmless tests.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_learning_graph.py tests/test_command_center_repository.py tests/test_command_center_service.py tests/test_command_center_api.py -q`

- [ ] **Step 3: Implement the policy branch and candidate query endpoint**

The policy is selected from the trusted system profile, not by the model. The model can recommend rejection or compilation, but cannot promote a real MES Skill to published status.

- [ ] **Step 4: Run focused tests and verify success**

Run: `conda run -n langgraph python -m pytest tests/test_learning_graph.py tests/test_command_center_repository.py tests/test_command_center_service.py tests/test_command_center_api.py -q`

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/learning_graph.py app/command_center/repository.py app/command_center/service.py app/command_center/router.py tests/test_learning_graph.py tests/test_command_center_repository.py tests/test_command_center_service.py tests/test_command_center_api.py
git commit -m "feat: retain verified MES skill candidates"
```

### Task 11: Compose the real MES vertical slice

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_real_mes_readonly_loop.py`
- Modify: `tests/test_api.py`
- Modify: `browser_extension/background.mjs`
- Modify: `browser_extension/popup.mjs`

**Interfaces:**
- `build_command_center_components()` returns profile-indexed catalogs, extension recorder, credential vault, local and readonly testers, and learning-graph factories.
- Extension start request selects `source_system="yifeng_mes"`, `capture_source="browser_extension"`, and objective `查询采购申请`.

- [ ] **Step 1: Write a failing backend tracer-bullet test**

Use a synthetic Swagger document and `httpx.MockTransport`; do not contact the real MES.

```python
def test_record_query_generate_and_verify_candidate(tmp_path):
    recording = service.create_extension_recording("查询采购申请")
    service.ingest_extension_events(
        recording["recording_id"],
        ui_query_and_three_api_exchanges(),
        recording["ingest_token"],
    )
    result = service.stop_extension_recording(
        recording["recording_id"], recording["ingest_token"]
    )

    assert result["status"] == "verified_candidate"
    assert result["learning_result"]["candidate_skill"]["name"] == "查询采购申请"
    assert repository.list_published_skills() == []
```

- [ ] **Step 2: Write a failing extension lifecycle test with mocked Chrome APIs**

Assert the popup starts only on the allowed host, the background attaches only the chosen tab ID, batches UI/network events, posts the credential separately, stops observation before analysis, and reports the verified-candidate result.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `conda run -n langgraph python -m pytest tests/test_real_mes_readonly_loop.py tests/test_api.py -q`

Run: `node --test browser_extension/tests`

- [ ] **Step 4: Wire components without making real MES startup mandatory**

Load the profile at startup, but load the 5 MB OpenAPI document lazily when an extension session starts. Cache the parsed document with a bounded TTL. If the document is unavailable, the local CommandCenter and existing test system must continue to start; the extension session returns a clear unavailable error.

- [ ] **Step 5: Run the tracer bullet and full automated suite**

Run: `conda run -n langgraph python -m pytest tests/test_real_mes_readonly_loop.py tests/test_api.py -q`

Run: `conda run -n langgraph python -m pytest -q`

Run: `node --test browser_extension/tests`

Run: `npm run test`

Run: `npm run build`

Working directory for the final two commands: `D:\python\CommandCenter\frontend`.

Expected: all commands pass and no test contacts or mutates the real MES.

- [ ] **Step 6: Commit**

```powershell
git add app/main.py tests/test_real_mes_readonly_loop.py tests/test_api.py browser_extension/background.mjs browser_extension/popup.mjs
git commit -m "feat: complete readonly MES observer loop"
```

### Task 12: Document and perform the controlled real-MES read-only acceptance test

**Files:**
- Create: `browser_extension/README.md`
- Create: `docs/testing/2026-08-03-yifeng-mes-readonly-acceptance.md`
- Modify after execution: `docs/superpowers/specs/2026-08-03-real-mes-readonly-observer-design.md`

**Interfaces:**
- Produces a human-readable install/runbook and an append-only acceptance result with recording ID, timestamps, Tool IDs, redaction checks, and candidate Skill ID. It must not contain credentials or raw sensitive business values.

- [ ] **Step 1: Write the unpacked-extension runbook**

Document exact steps:

1. Start FastAPI with `conda run -n langgraph uvicorn app.main:app --host 127.0.0.1 --port 8000`.
2. Open `edge://extensions` or `chrome://extensions`.
3. Enable developer mode and load `D:\python\CommandCenter\browser_extension` unpacked.
4. Log in to MES manually; never put credentials in the project.
5. Open采购申请列表.
6. Start recording the current tab.
7. Use a query that does not change data, open one existing detail, and stop.
8. Confirm the candidate is `verified_candidate` and `/skills` still excludes it.

- [ ] **Step 2: Add a preflight safety checklist**

The checklist must require confirmation that the profile contains only the three query paths, no browser DevTools session is competing for the tab, the extension shows the exact selected tab, and the observer displays read-only mode before recording.

- [ ] **Step 3: Run automated preflight**

Run: `conda run -n langgraph python -m pytest -q`

Run: `node --test browser_extension/tests`

Run: `npm run test` and `npm run build` from `frontend`.

Expected: PASS before touching the real MES.

- [ ] **Step 4: Perform one controlled real read-only recording**

Do not click新增、编辑、保存、提交、审核、完成、反审核、反完成、删除, or any action not named by the acceptance checklist. If the page or extension presents ambiguity, stop recording and mark the acceptance result inconclusive rather than exploring with writes.

- [ ] **Step 5: Verify evidence and candidate isolation**

Check:

- selected-tab ID and host match the session;
- trace contains UI and API evidence for list/detail only;
- serialized recording contains no credential header names with values;
- non-allowlisted traffic is evidence-only and cannot execute;
- candidate Skill contains only read steps and `query.` bindings;
- ordinary `/skills` and task-center execution cannot see the candidate;
- no MES business record or status was changed by CommandCenter.

- [ ] **Step 6: Record the result and update design status**

Write `passed`, `failed`, or `inconclusive` with concrete evidence. Change the design status to `已实施并通过只读验收` only when the acceptance result is `passed`; otherwise keep `待实施` or use `已实施，验收未通过` with the reason.

- [ ] **Step 7: Commit documentation**

```powershell
git add browser_extension/README.md docs/testing/2026-08-03-yifeng-mes-readonly-acceptance.md docs/superpowers/specs/2026-08-03-real-mes-readonly-observer-design.md
git commit -m "docs: record readonly MES acceptance"
```

---

## Final Verification

- [ ] Run `conda run -n langgraph python -m pytest -q`.
- [ ] Run `node --test browser_extension/tests`.
- [ ] Run `npm run test` from `frontend`.
- [ ] Run `npm run build` from `frontend`.
- [ ] Run `git diff --check`.
- [ ] Run `git status --short` and confirm only intentionally preserved user files remain untracked.
- [ ] Confirm the real MES acceptance document contains no password, token, cookie, CAPTCHA, raw credential header, or unnecessary business value.
- [ ] Confirm no candidate real MES Skill appears in the published Skill registry.
- [ ] Confirm all real MES Tool calls in acceptance evidence are one of the three exact read-only method/path pairs.
