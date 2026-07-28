# CommandCenter V1 Minimal Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest working vertical loop in which an employee demonstrates a cross-system process once, agents compile and harmlessly test an API Skill, and another employee request executes the published Skill through LangGraph.

**Architecture:** A Playwright recorder captures trusted UI events and the matching allowlisted HTTP exchanges from the two local business systems. Pydantic-validated agents turn the trace into an immutable Skill, a learning LangGraph tests and publishes it, and an execution LangGraph handles natural-language requests and invokes only the recorded API tools. SQLite stores structured state; trace ZIPs and screenshots remain local evidence files.

**Tech Stack:** Python 3.11 in conda environment `langgraph`, FastAPI, Pydantic v2, SQLAlchemy, LangGraph, OpenAI-compatible structured model calls, HTTPX, Playwright Python, SQLite, Vue 3, TypeScript, Vite, Element Plus, pytest.

## Global Constraints

- Run Python through `conda run -n langgraph`.
- Published V1 Skills execute APIs only; browser replay is outside V1.
- The model may reason about business meaning, but only deterministic code may enforce API allowlists, schemas, idempotency, test isolation, immutable publication, and ambiguity selection.
- A candidate publishes only after normal, parameter-variation, and idempotency tests all pass with no unknown side effects.
- A failed test is not repaired automatically; the employee must demonstrate again.
- A failed production run stops before later writes, preserves evidence, and does not modify the Skill.
- No administrator workflow, account system, Celery, arbitrary Python expressions, or production credentials.
- Preserve the user-owned untracked file `docs/research/2026-07-27-gui-agent-demonstration-learning-projects.md`.

---

## File Structure

### CommandCenter backend

- `app/command_center/schemas.py`: all validated recording, Skill, test, execution, and verification contracts.
- `app/command_center/database.py`: SQLAlchemy engine/session setup.
- `app/command_center/models.py`: recording, Skill version, test, and task-run rows.
- `app/command_center/repository.py`: persistence methods and immutable publication transition.
- `app/command_center/tool_catalog.py`: OpenAPI allowlist loading, request matching, and version hashing.
- `app/command_center/tool_executor.py`: allowlisted HTTP invocation, binding resolution, redaction, and idempotency headers.
- `app/command_center/model.py`: common structured model client with one schema-repair retry.
- `app/command_center/agents.py`: five logical agent roles and prompts.
- `app/command_center/recorder.py`: Playwright session lifecycle and OperationTrace capture.
- `app/command_center/testing.py`: isolated fixtures, three-category test execution, and publish gate.
- `app/command_center/learning_graph.py`: demonstration-to-published-Skill LangGraph.
- `app/command_center/execution_graph.py`: natural-language-to-verified-result LangGraph.
- `app/command_center/service.py`: application façade used by FastAPI routes.
- `app/command_center/router.py`: recording, Skill, and task-run endpoints.
- `app/main.py`: mounts the V1 router.

### Test business systems

- `external_systems/common.py`: idempotency table, task detail endpoint, processing-state update, and generic submission lookup.
- `external_systems/ui/app.js`: actual purchase creation and purchase-number writeback UI.
- `external_systems/ui/index.html`: operation panels used during demonstration.

### Frontend

- `frontend/src/api/commandCenter.ts`: recording, Skill, and task-run API calls.
- `frontend/src/api/types.ts`: V1 view contracts.
- `frontend/src/pages/DemonstrationWorkbenchPage.vue`: start/stop demonstration and learning status.
- `frontend/src/pages/TaskCenterPage.vue`: adds natural-language Skill execution without removing existing normal tasks.
- `frontend/src/App.vue`: separates demonstration workbench from the ordinary task center.

### Tests

- `tests/test_command_center_schemas.py`
- `tests/test_tool_catalog.py`
- `tests/test_command_center_repository.py`
- `tests/test_external_systems.py`
- `tests/test_tool_executor.py`
- `tests/test_learning_graph.py`
- `tests/test_execution_graph.py`
- `tests/test_command_center_api.py`

---

### Task 1: Idempotent APIs and real operation UI in the two test systems

**Files:**
- Modify: `external_systems/common.py`
- Modify: `external_systems/ui/index.html`
- Modify: `external_systems/ui/app.js`
- Modify: `external_systems/ui/app.css`
- Modify: `tests/test_external_systems.py`

**Interfaces:**
- Produces: `GET /api/tasks/{task_id}`, `POST /api/tasks/{task_id}/purchase-link`, and idempotent existing submission endpoints accepting `Idempotency-Key`.
- Produces: response header/body behavior where repeated identical keys return the first response and create no duplicate row.

- [ ] **Step 1: Write failing API tests**

```python
def test_workflow_submission_is_idempotent(tmp_path):
    client = TestClient(build_connected_app(tmp_path))
    headers = {"Idempotency-Key": "skill:1:task:step"}
    first = client.post("/api/workflows/start", data=workflow_payload(), headers=headers)
    second = client.post("/api/workflows/start", data=workflow_payload(), headers=headers)
    assert second.json() == first.json()
    assert len(client.get("/api/submissions").json()["items"]) == 1


def test_office_task_can_link_purchase_request(tmp_path):
    client = TestClient(build_onboarding_app(tmp_path))
    response = client.post(
        "/api/tasks/OFFICE-TASK-0001/purchase-link",
        json={"purchase_request_id": "WORKFLOW-0001"},
        headers={"Idempotency-Key": "skill:1:office:step"},
    )
    assert response.json()["status"] == "processing"
    assert response.json()["result_values"]["purchase_request_id"] == "WORKFLOW-0001"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_external_systems.py -q`

Expected: new idempotency and purchase-link tests fail because the table/endpoints do not exist.

- [ ] **Step 3: Implement deterministic idempotency storage**

Add an `idempotency_records` table keyed by `(operation, idempotency_key)` and a helper:

```python
def _idempotent_write(connection, operation, key, perform):
    existing = connection.execute(
        "select response_json from idempotency_records where operation = ? and idempotency_key = ?",
        (operation, key),
    ).fetchone()
    if existing:
        return json.loads(existing["response_json"])
    response = perform()
    connection.execute(
        "insert into idempotency_records(operation, idempotency_key, response_json) values (?, ?, ?)",
        (operation, key, json.dumps(response, ensure_ascii=False)),
    )
    return response
```

Require the header for the new purchase-link write and support it on form/workflow submissions.

- [ ] **Step 4: Add actual employee operation panels**

The connected-system panel submits a purchase request and displays its ID. The onboarding-system panel lists pending office tasks and posts a chosen purchase ID back to the task. Use existing `request()` and `refreshData()` helpers and semantic labels/test IDs so the recorder receives useful UI evidence.

- [ ] **Step 5: Run backend tests**

Run: `conda run -n langgraph python -m pytest tests/test_external_systems.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add external_systems/common.py external_systems/ui tests/test_external_systems.py
git commit -m "feat: add idempotent demo business operations"
```

---

### Task 2: Validated contracts and durable repository

**Files:**
- Create: `app/command_center/__init__.py`
- Create: `app/command_center/schemas.py`
- Create: `app/command_center/database.py`
- Create: `app/command_center/models.py`
- Create: `app/command_center/repository.py`
- Create: `tests/test_command_center_schemas.py`
- Create: `tests/test_command_center_repository.py`

**Interfaces:**
- Produces: `OperationTrace`, `DemonstrationAnalysis`, `SkillDefinition`, `TestPlan`, `ExecutionCommand`, `StepResult`, and `VerificationResult`.
- Produces: `CommandCenterRepository.create_recording()`, `save_trace()`, `save_candidate_skill()`, `publish_skill()`, `list_published_skills()`, `create_task_run()`, and `update_task_run()`.

- [ ] **Step 1: Write failing schema and repository tests**

```python
def test_published_skill_rejects_unknown_binding_expression():
    payload = valid_skill_payload()
    payload["steps"][0]["input_bindings"]["item"] = "python:__import__('os')"
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(payload)


def test_published_version_is_immutable(tmp_path):
    repository = repository_for(tmp_path)
    candidate = repository.save_candidate_skill(valid_skill())
    repository.publish_skill(candidate.skill_id, candidate.version)
    with pytest.raises(ImmutableSkillError):
        repository.replace_skill(candidate)
```

- [ ] **Step 2: Run and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_schemas.py tests/test_command_center_repository.py -q`

Expected: import failures.

- [ ] **Step 3: Implement focused Pydantic models**

Use discriminated string enums and validators. `BindingExpression` accepts only:

```text
task.<field>
steps.<step_id>.output.<field>
literal.<name>
```

Do not persist cookies, authorization headers, model reasoning, or executable code.

- [ ] **Step 4: Implement SQLite repository**

Use a configurable `COMMAND_CENTER_DATABASE_URL` defaulting to a gitignored SQLite file. Store structured payloads as JSON and enforce publication with a single transaction:

```python
def publish_skill(self, skill_id: UUID, version: int) -> SkillDefinition:
    row = self._get_skill_row(skill_id, version)
    if row.status != "testing":
        raise InvalidTransitionError(f"Skill status must be testing, got {row.status}")
    if not self._all_required_tests_passed(skill_id, version):
        raise PublishGateError("normal, parameter_variation and idempotency must pass")
    row.status = "published"
    row.published_at = utc_now()
    self.session.commit()
    return SkillDefinition.model_validate_json(row.payload_json)
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_schemas.py tests/test_command_center_repository.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/command_center tests/test_command_center_schemas.py tests/test_command_center_repository.py
git commit -m "feat: add command center contracts and repository"
```

---

### Task 3: Allowlisted OpenAPI tool catalog and executor

**Files:**
- Create: `app/command_center/tool_catalog.py`
- Create: `app/command_center/tool_executor.py`
- Create: `tests/test_tool_catalog.py`
- Create: `tests/test_tool_executor.py`

**Interfaces:**
- Consumes: `SkillDefinition`, `ExecutionCommand`, and `StepResult`.
- Produces: `ToolCatalog.load()`, `ToolCatalog.match_exchange()`, `BindingResolver.resolve()`, and `ToolExecutor.execute()`.

- [ ] **Step 1: Write failing catalog tests**

```python
def test_matches_only_allowlisted_operation():
    catalog = ToolCatalog.from_openapi_documents(documents, allowlist)
    match = catalog.match_exchange("connected_system", "POST", "/api/workflows/start")
    assert match.tool_id == "connected_system:start_workflow_api_workflows_start_post"
    assert catalog.match_exchange("connected_system", "POST", "/api/demo/reset") is None
```

- [ ] **Step 2: Write failing executor tests**

```python
def test_executor_resolves_previous_step_output_and_sets_idempotency():
    command = build_command(binding="steps.create_purchase.output.data.id")
    result = executor.execute(command, prior_steps={"create_purchase": purchase_result})
    assert transport.last_headers["Idempotency-Key"] == command.idempotency_key
    assert transport.last_json["purchase_request_id"] == "WORKFLOW-0001"
```

- [ ] **Step 3: Run and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_tool_catalog.py tests/test_tool_executor.py -q`

Expected: import failures.

- [ ] **Step 4: Implement catalog**

Fetch `/openapi.json` for both configured systems, normalize path templates, retain only explicit `(system_code, operation_id)` allowlist entries, and SHA-256 the canonical catalog JSON. Request matching is deterministic by system, method, and normalized path.

- [ ] **Step 5: Implement executor**

Resolve bindings, validate arguments against catalog request metadata, set the deterministic `Idempotency-Key` for writes, redact sensitive headers, call through an injectable HTTPX transport, and normalize successful/error responses into `StepResult`.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `conda run -n langgraph python -m pytest tests/test_tool_catalog.py tests/test_tool_executor.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/command_center/tool_catalog.py app/command_center/tool_executor.py tests/test_tool_catalog.py tests/test_tool_executor.py
git commit -m "feat: add allowlisted API tool execution"
```

---

### Task 4: Playwright demonstration recorder

**Files:**
- Modify: `requirements.txt`
- Create: `app/command_center/recorder.py`
- Create: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `ToolCatalog`.
- Produces: `RecorderService.start(recording_id, start_url)`, `RecorderService.stop(recording_id) -> OperationTrace`.

- [ ] **Step 1: Write failing recorder aggregation test**

```python
async def test_recorder_orders_ui_and_api_evidence(fake_browser, catalog):
    recorder = RecorderService(browser_factory=fake_browser, catalog=catalog)
    await recorder.start(recording_id, "http://127.0.0.1:8102")
    fake_browser.emit_click({"tag": "button", "accessible_name": "回写采购单号"})
    fake_browser.emit_exchange(
        "POST",
        "/api/tasks/OFFICE-TASK-1/purchase-link",
        {"purchase_request_id": "WORKFLOW-0001"},
    )
    trace = await recorder.stop(recording_id)
    assert trace.ui_events[0].sequence < trace.api_exchanges[0].sequence
    assert trace.api_exchanges[0].matched_tool_id
```

- [ ] **Step 2: Run and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_recorder.py -q`

Expected: import failure.

- [ ] **Step 3: Add Playwright dependency**

Add `playwright` to `requirements.txt`; install with the project conda environment and install Chromium.

- [ ] **Step 4: Implement recorder lifecycle**

Use `async_playwright`, `browser_context.add_init_script()`, and an exposed binding to capture click/input/select/submit/navigation metadata. Listen to request/response events, redact authorization/cookie values, match exchanges through the Tool catalog, enable Playwright Trace, and close every browser/context/playwright resource on stop or error.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `conda run -n langgraph python -m pytest tests/test_recorder.py -q`

Expected: PASS without launching a real browser because the test injects a fake.

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt app/command_center/recorder.py tests/test_recorder.py
git commit -m "feat: capture demonstration operation traces"
```

---

### Task 5: Structured agents and learning/publish LangGraph

**Files:**
- Create: `app/command_center/model.py`
- Create: `app/command_center/agents.py`
- Create: `app/command_center/testing.py`
- Create: `app/command_center/learning_graph.py`
- Create: `tests/test_learning_graph.py`

**Interfaces:**
- Consumes: repository, trace, catalog, executor, and reset/fixture clients.
- Produces: `build_learning_graph(dependencies)` and a published or rejected Skill result.

- [ ] **Step 1: Write failing happy-path and rejection tests**

```python
def test_learning_graph_publishes_after_three_agent_tests(dependencies):
    state = build_learning_graph(dependencies).invoke({"recording_id": recording_id})
    assert state["final_status"] == "published"
    assert [result.category for result in state["test_results"]] == [
        "normal", "parameter_variation", "idempotency"
    ]


def test_learning_graph_rejects_unknown_side_effect(dependencies):
    dependencies.verifier.return_unknown_side_effect = True
    state = build_learning_graph(dependencies).invoke({"recording_id": recording_id})
    assert state["final_status"] == "rejected"
```

- [ ] **Step 2: Run and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_learning_graph.py -q`

Expected: import failure.

- [ ] **Step 3: Implement structured model wrapper**

Load `.env.ai`, call the OpenAI-compatible model with JSON output, validate with a requested Pydantic type, and retry exactly once with the validation error. Never log the API key or chain-of-thought.

- [ ] **Step 4: Implement five logical agent roles**

Create focused methods:

```python
analyze_demonstration(trace, catalog) -> DemonstrationAnalysis
compile_skill(analysis, trace, catalog) -> SkillDefinition
design_tests(skill, fixture_capabilities) -> TestPlan
build_execution_command(skill, step, context) -> ExecutionCommand
verify_result(skill, steps, observed_state) -> VerificationResult
```

Each method uses its own system prompt and validated output contract.

- [ ] **Step 5: Implement harmless test service**

For every case, reset both local test systems, create a marked office task, execute the candidate against isolated data, query final state, and let the verifier judge it. The idempotency case executes the same logical run twice and asserts one purchase request.

- [ ] **Step 6: Implement learning graph**

Implement the approved nodes and conditional routing. Deterministic nodes reject unknown tools, missing bindings, missing idempotency on writes, incomplete test categories, failed/inconclusive verification, or unknown side effects.

- [ ] **Step 7: Run tests and verify GREEN**

Run: `conda run -n langgraph python -m pytest tests/test_learning_graph.py -q`

Expected: PASS using fake agent and transport dependencies.

- [ ] **Step 8: Commit**

```powershell
git add app/command_center/model.py app/command_center/agents.py app/command_center/testing.py app/command_center/learning_graph.py tests/test_learning_graph.py
git commit -m "feat: learn test and publish demonstrated skills"
```

---

### Task 6: Natural-language execution LangGraph

**Files:**
- Create: `app/command_center/execution_graph.py`
- Create: `tests/test_execution_graph.py`

**Interfaces:**
- Consumes: published Skill repository, agents, catalog, executor, and business-system read clients.
- Produces: `build_execution_graph(dependencies)` returning success, failure, or `needs_object_selection`.

- [ ] **Step 1: Write failing execution tests**

```python
def test_natural_language_request_executes_published_skill(dependencies):
    result = graph.invoke({"user_request": "处理签字笔库存不足任务"})
    assert result["verification_result"].status == "passed"
    assert result["final_response"]["purchase_request_id"].startswith("WORKFLOW-")


def test_multiple_matching_objects_require_employee_selection(dependencies):
    dependencies.business_reader.tasks = [task("A"), task("B")]
    result = graph.invoke({"user_request": "处理库存不足任务"})
    assert result["status"] == "needs_object_selection"
    assert len(result["candidate_objects"]) == 2
```

- [ ] **Step 2: Run and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_execution_graph.py -q`

Expected: import failure.

- [ ] **Step 3: Implement execution graph**

Allow the task agent to rewrite intent, select read tools, and rank published Skills. Require employee selection when more than one business object remains. Execute the selected immutable Skill step-by-step; stop on the first failed write; query final state; run verifier; return a plain employee-facing summary.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `conda run -n langgraph python -m pytest tests/test_execution_graph.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/execution_graph.py tests/test_execution_graph.py
git commit -m "feat: execute published skills from natural language"
```

---

### Task 7: FastAPI façade and status endpoints

**Files:**
- Create: `app/command_center/service.py`
- Create: `app/command_center/router.py`
- Modify: `app/main.py`
- Create: `tests/test_command_center_api.py`

**Interfaces:**
- Consumes: recorder, learning graph, execution graph, and repository.
- Produces: approved recording, Skill, task-run, object-selection, and event endpoints.

- [ ] **Step 1: Write failing API lifecycle test**

```python
def test_recording_stop_starts_learning_and_exposes_published_status(client, fake_service):
    created = client.post(
        "/recordings",
        json={
            "objective": "演示采购回写",
            "source_system": "onboarding_system",
            "source_task_id": "OFFICE-TASK-0001",
        },
    ).json()
    client.post(f"/recordings/{created['recording_id']}/start")
    stopped = client.post(f"/recordings/{created['recording_id']}/stop")
    assert stopped.status_code == 202
    assert client.get(f"/recordings/{created['recording_id']}").json()["status"] == "published"
```

- [ ] **Step 2: Run and verify RED**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_api.py -q`

Expected: 404 or import failure.

- [ ] **Step 3: Implement service and router**

Mount:

```text
POST /recordings
POST /recordings/{id}/start
POST /recordings/{id}/stop
GET  /recordings/{id}
GET  /skills
GET  /skills/{id}
POST /task-runs
POST /task-runs/{id}/select-object
GET  /task-runs/{id}
GET  /task-runs/{id}/events
```

Use application-local asyncio tasks for learning/execution, keep the service injectable for tests, and return employee-readable status without exposing internal prompts or credentials.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `conda run -n langgraph python -m pytest tests/test_command_center_api.py -q`

Expected: PASS.

- [ ] **Step 5: Run full backend regression**

Run: `conda run -n langgraph python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add app/main.py app/command_center/service.py app/command_center/router.py tests/test_command_center_api.py
git commit -m "feat: expose command center V1 APIs"
```

---

### Task 8: Demonstration Workbench and natural-language Task Center

**Files:**
- Create: `frontend/src/api/commandCenter.ts`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/pages/DemonstrationWorkbenchPage.vue`
- Modify: `frontend/src/pages/TaskCenterPage.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: V1 FastAPI endpoints.
- Produces: two employee-facing flows: Demonstration Workbench and ordinary Task Center.

- [ ] **Step 1: Add typed frontend API client**

Implement calls for create/start/stop/poll recording, list Skills, create/poll task run, and submit an ambiguity selection. Keep internal agent schemas out of view types.

- [ ] **Step 2: Build Demonstration Workbench**

Show:

```text
选择测试任务 → 填写演示目标 → 开始演示 → 结束演示
→ 分析中 → 自动测试中 → Skill 已发布 / 需要重新演示
```

Opening a recording starts the controlled browser; status polling stops at `published` or `needs_reteach`.

- [ ] **Step 3: Add natural-language execution to Task Center**

Place a compact task command panel above existing normal forms/tasks. Show business-level progress, an object chooser only when required, and the final purchase ID/status or failure summary.

- [ ] **Step 4: Separate navigation**

Add independent sidebar entries for `任务中心` and `演示工作台`. Retain `外部业务系统` and `AI 生成配置` as administrator-oriented pages without adding accounts or review workflows.

- [ ] **Step 5: Build frontend**

Run: `npm run build` in `frontend`

Expected: `vue-tsc -b && vite build` succeeds.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src
git commit -m "feat: add V1 demonstration and skill execution UI"
```

---

### Task 9: End-to-end acceptance, documentation, and final verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-28-command-center-v1-minimal-agent-loop-design.md`
- Create: `tests/test_v1_vertical_loop.py`

**Interfaces:**
- Consumes: the complete V1.
- Produces: one repeatable acceptance test and operator instructions.

- [ ] **Step 1: Write end-to-end acceptance test**

Use in-process test apps/fake structured agents to prove:

```text
one demonstration
→ candidate Skill
→ normal + variation + idempotency pass
→ auto-publication
→ natural-language run on another office task
→ one purchase request
→ purchase ID written back
→ verifier passes
```

Also inject one write failure and assert later steps do not execute and evidence remains.

- [ ] **Step 2: Run acceptance test**

Run: `conda run -n langgraph python -m pytest tests/test_v1_vertical_loop.py -q`

Expected: PASS.

- [ ] **Step 3: Update operator documentation**

Document dependency installation, `playwright install chromium`, four service start commands, model configuration reuse through `.env.ai`, the demonstration flow, the ordinary task flow, reset behavior, and the fact that V1 only executes allowlisted APIs.

- [ ] **Step 4: Mark approved spec implemented only after verification**

Change the spec status from `待用户审阅书面规格` to `已批准并完成 V1 实现` only if all acceptance checks pass.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
conda run -n langgraph python -m pytest -q
Set-Location frontend
npm run build
```

Expected: all backend tests and frontend build pass.

- [ ] **Step 6: Inspect the user-visible workflow**

Start all services, open the frontend, verify the separate workbench/task pages, perform one real controlled-browser demonstration using the configured model, and capture any environment-only limitation distinctly from code failures.

- [ ] **Step 7: Commit**

```powershell
git add README.md docs/superpowers/specs/2026-07-28-command-center-v1-minimal-agent-loop-design.md tests/test_v1_vertical_loop.py
git commit -m "test: verify CommandCenter V1 vertical loop"
```
