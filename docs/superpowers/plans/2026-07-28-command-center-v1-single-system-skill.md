# CommandCenter V1 Single-System Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unfinished cross-system V1 sample with a complete single-system loop that learns, tests, publishes, and executes a “创建采购申请” API Skill.

**Architecture:** Keep the general recorder, structured-agent, Skill runner, repository, and LangGraph infrastructure. Narrow the V1 adapters to the procurement system on port 8101: the recorder opens that system, fixtures create procurement inputs directly, verification reads procurement submissions, and natural-language execution binds extracted values without searching office-supply tasks.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, Pydantic, SQLAlchemy, httpx, Playwright, pytest, Vue 3, TypeScript, Vite, Element Plus, Vitest.

## Global Constraints

- The V1 test uses only CommandCenter and the procurement business system.
- The office-supply system remains available to older project features but is not used by V1 recording, testing, publishing, or execution.
- Published Skills execute allowlisted API Tools; they do not replay UI clicks.
- Every write call carries an idempotency key.
- Model output must pass the existing structured Pydantic validation.
- Use the `langgraph` conda environment for Python commands.

---

### Task 1: Procurement-Only Demonstration Entry

**Files:**
- Modify: `tests/test_command_center_service.py`
- Modify: `app/command_center/service.py`
- Modify: `frontend/src/pages/DemonstrationWorkbenchPage.vue`
- Modify: `frontend/src/pages/DemonstrationWorkbenchPage.test.ts`

**Interfaces:**
- Consumes: `CommandCenterService.start_recording(recording_id)`
- Produces: recorder launch URL `http://127.0.0.1:8101` and a source object with `system_code="connected_system"`

- [ ] **Step 1: Write the failing backend test**

```python
async def test_start_recording_opens_only_procurement_system(service, recorder):
    created = service.create_recording(
        RecordingCreate(
            objective="创建采购申请",
            source_system="connected_system",
            source_task_id="purchase-demonstration",
        )
    )
    await service.start_recording(created["recording_id"])
    assert recorder.started_url == "http://127.0.0.1:8101"
```

- [ ] **Step 2: Run the backend test and verify it fails**

Run: `conda run --no-capture-output -n langgraph python -m pytest tests/test_command_center_service.py -q`

Expected: FAIL because the service still opens port 8102.

- [ ] **Step 3: Write the failing frontend assertions**

```ts
expect(wrapper.text()).toContain('在采购系统填写并提交一条采购申请')
expect(wrapper.text()).not.toContain('回写')
expect(wrapper.find('input[placeholder="OFFICE-TASK-0001"]').exists()).toBe(false)
```

- [ ] **Step 4: Run the frontend test and verify it fails**

Run: `npm run test --prefix frontend -- DemonstrationWorkbenchPage.test.ts`

Expected: FAIL because the workbench still asks for an office task and describes writeback.

- [ ] **Step 5: Implement the procurement-only entry**

Change `CommandCenterService.start_recording()` to open port 8101. In the workbench, use the fixed objective “创建采购申请”, remove the office-task input, submit `source_system: "connected_system"` with `source_task_id: "purchase-demonstration"`, and tell the employee to submit one purchase request.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_command_center_service.py -q
npm run test --prefix frontend -- DemonstrationWorkbenchPage.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/command_center/service.py tests/test_command_center_service.py frontend/src/pages/DemonstrationWorkbenchPage.vue frontend/src/pages/DemonstrationWorkbenchPage.test.ts
git commit -m "feat: make V1 demonstration procurement-only"
```

### Task 2: Procurement-Only Harmless Testing

**Files:**
- Modify: `tests/test_harmless_testing.py`
- Modify: `app/command_center/testing.py`

**Interfaces:**
- Consumes: test-case `fixture.source_task.content`
- Produces: a synthetic task dictionary whose fields bind directly into the create-purchase Tool, plus observed procurement submissions

- [ ] **Step 1: Write the failing fixture test**

```python
def test_fixture_resets_only_procurement_and_returns_purchase_inputs(fixture_service):
    task = fixture_service.prepare({
        "source_task": {
            "content": {
                "applicant": "测试员工",
                "item_name": "打印纸",
                "quantity": 10,
                "usage": "行政采购",
            }
        }
    })
    assert task["system_code"] == "connected_system"
    assert task["content"]["item_name"] == "打印纸"
    assert fixture_service.observe(task)["purchase_count"] == 0
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `conda run --no-capture-output -n langgraph python -m pytest tests/test_harmless_testing.py -q`

Expected: FAIL because `LocalFixtureService` currently creates and reads an office-supply task.

- [ ] **Step 3: Implement the procurement fixture**

`prepare()` resets only `connected_system` and returns a deterministic synthetic source object:

```python
return {
    "task_id": source.get("task_id", f"purchase-test-{uuid4()}"),
    "system_code": "connected_system",
    "content": source.get("content", {}),
}
```

`observe()` reads only `connected_system/api/submissions` and returns `purchase_requests` and `purchase_count`.

- [ ] **Step 4: Run the test and verify it passes**

Run: `conda run --no-capture-output -n langgraph python -m pytest tests/test_harmless_testing.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/testing.py tests/test_harmless_testing.py
git commit -m "refactor: isolate V1 skill tests to procurement"
```

### Task 3: Natural-Language Procurement Execution

**Files:**
- Modify: `tests/test_execution_graph.py`
- Modify: `app/command_center/execution_graph.py`
- Modify: `app/command_center/agents.py`

**Interfaces:**
- Consumes: employee `user_request` and published procurement Skills
- Produces: one selected Skill, extracted literals, one procurement API execution, and procurement-only verification state

- [ ] **Step 1: Write the failing graph test**

```python
def test_executes_procurement_skill_without_searching_business_tasks(graph):
    result = graph.invoke({"user_request": "帮我为行政部采购10箱打印纸"})
    assert result["status"] == "succeeded"
    assert result["selected_object"]["system_code"] == "connected_system"
    assert result["final_response"]["observed_state"]["purchase_count"] == 1
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `conda run --no-capture-output -n langgraph python -m pytest tests/test_execution_graph.py -q`

Expected: FAIL because `LocalBusinessReader` searches the office-supply task API.

- [ ] **Step 3: Implement procurement request context**

Change the execution graph so the business reader builds one synthetic input object from the employee request, the matching agent extracts Skill literals, and verification reads only procurement submissions. Remove the object-selection branch from the V1 path while keeping the generic graph state compatible with existing repository/API responses.

- [ ] **Step 4: Update agent prompts**

The matching prompt must select a published Skill and extract procurement fields from natural language. The verification prompt must determine whether exactly one matching procurement submission was created and report its procurement number.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_execution_graph.py tests/test_structured_agents.py tests/test_skill_runner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/command_center/execution_graph.py app/command_center/agents.py tests/test_execution_graph.py tests/test_structured_agents.py
git commit -m "feat: execute procurement skills from natural language"
```

### Task 4: Single-System Vertical Loop and Documentation

**Files:**
- Modify: `tests/test_v1_vertical_loop.py`
- Modify: `app/main.py`
- Modify: `docs/superpowers/specs/2026-07-28-command-center-v1-minimal-agent-loop-design.md`
- Modify: `D:\ObsidianNote\ObsidianNote\00-Inbox\CommandCenter V1最小智能体闭环设计.md`

**Interfaces:**
- Consumes: procurement OpenAPI document and allowlisted create-purchase operation
- Produces: end-to-end evidence that one demonstration publishes a one-step Skill and a later natural-language request creates exactly one purchase request

- [ ] **Step 1: Replace the end-to-end test with a single-system case**

The deterministic Skill must contain only:

```python
{
    "step_id": "create_purchase",
    "tool_id": "connected_system:create_purchase_request_api_purchase_requests_post",
    "input_bindings": {
        "body.applicant": "task.content.applicant",
        "body.item_name": "task.content.item_name",
        "body.quantity": "task.content.quantity",
        "body.reason": "task.content.usage",
    },
    "side_effect": "write",
}
```

Assert that learning publishes it, natural-language execution creates one procurement submission, the returned ID is present, and no office-system client exists in the test.

- [ ] **Step 2: Run the end-to-end test and verify it fails**

Run: `conda run --no-capture-output -n langgraph python -m pytest tests/test_v1_vertical_loop.py -q`

Expected: FAIL while the V1 app dependencies and test still require the office-supply system.

- [ ] **Step 3: Narrow V1 dependency wiring**

In `app/main.py`, keep the broader product registry intact but build the CommandCenter V1 ToolCatalog, test fixture, and business reader with only `connected_system` and its allowlisted create-purchase operation.

- [ ] **Step 4: Update current documentation and knowledge note**

Mark the old cross-system V1 sample as superseded by `2026-07-28-command-center-v1-single-system-skill-design.md`. Update the existing Obsidian note in place because the user previously requested that project decisions stay synchronized with the knowledge base.

- [ ] **Step 5: Run all verification**

Run:

```powershell
conda run --no-capture-output -n langgraph python -m pytest -q
npm run test --prefix frontend
npm run build --prefix frontend
```

Expected: all backend and frontend tests pass; frontend production build succeeds.

- [ ] **Step 6: Commit**

```powershell
git add app/main.py tests/test_v1_vertical_loop.py docs/superpowers/specs/2026-07-28-command-center-v1-minimal-agent-loop-design.md
git commit -m "test: verify procurement-only V1 vertical loop"
```

