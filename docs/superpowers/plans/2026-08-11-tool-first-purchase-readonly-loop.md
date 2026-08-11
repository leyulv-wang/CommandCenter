# Tool-First Purchase Read-Only Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a direct, agent-planned read-only Tool path for MES purchase-application list queries and row details while preserving the existing Skill recording and Skill execution paths.

**Architecture:** LangGraph gains a Tool-first branch before its existing Skill matcher. The agent plans against the three allowlisted MES read Tools, deterministic code validates the plan and executes it through the existing `ToolExecutor`, and the existing Skill branch remains the fallback when no direct Tool applies. A detail request reuses the stored list result, passes the selected row as trusted task context, and returns a separately persisted detail run for the frontend.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, Pydantic, SQLAlchemy, httpx, Vue 3, TypeScript, Vite, Element Plus, Vitest.

## Global Constraints

- Use the local conda environment `langgraph` at `D:\anaconda3\envs\langgraph` for Python commands.
- Only the three `yifeng_mes` read operations already allowed by `app/data/system_profiles/yifeng_mes.json` may execute.
- Do not add, modify, submit, approve, complete, reverse, or delete MES data.
- Agent judgment selects Tools and parameters; deterministic code only enforces candidate membership, schema, permissions, side effects, limits, and audit evidence.
- Direct Tool execution must not create or persist a Skill.
- Existing browser recording, Skill analysis, automatic verification, Skill persistence, and Skill execution behavior must remain available.
- Credentials must remain in the Windows keyring path and must never enter prompts, task-run evidence, API responses, source code, or tests.
- The first implementation supports list queries, purchaser filtering, pagination, and clicking a returned row to view main-record and line-item details.
- Natural-language follow-ups such as “查看第一条详情” are outside this implementation.

---

## File Structure

- `app/command_center/schemas.py`: define direct Tool plan and verification schemas; allow an execution command to represent a non-Skill Tool invocation.
- `app/command_center/agents.py`: ask the configured model to plan and verify direct read-only Tool work; validate every returned Tool and argument against the supplied candidates.
- `app/command_center/direct_tool_runner.py`: execute an already validated read-only plan through `ToolExecutor` and return outputs plus safe evidence.
- `app/command_center/execution_graph.py`: route Tool-first, fall back to the unchanged Skill path, and expose direct Tool results.
- `app/main.py`: provide allowlisted read Tools and a credential-aware direct runner to the graph.
- `app/command_center/service.py`: locate a selected record in a persisted list run and create a separate detail run.
- `app/command_center/router.py`: expose the detail-run endpoint.
- `frontend/src/api/types.ts`: describe Tool-mode task runs and detail runs.
- `frontend/src/api/commandCenter.ts`: call the detail-run endpoint.
- `frontend/src/components/TaskResultTable.vue`: emit a row-detail action without exposing the internal MES ID as user input.
- `frontend/src/components/NaturalLanguageTaskPanel.vue`: retain the list result while loading and displaying a selected record’s details.
- Existing test modules receive focused regression tests; no unrelated file restructuring is included.

---

### Task 1: Define and validate the agent’s direct Tool plan

**Files:**
- Modify: `app/command_center/schemas.py`
- Modify: `app/command_center/agents.py`
- Test: `tests/test_agent_matching_runtime.py`
- Test: `tests/test_command_center_schemas.py`

**Interfaces:**
- Consumes: `ToolDefinition` from `app.command_center.tool_catalog` and the existing `AgentRuntime.run_structured(request)` interface.
- Produces: `DirectToolStep`, `DirectToolPlan`, `DirectToolVerification`, `AgentSuite.plan_tool_request(...)`, and `AgentSuite.verify_tool_result(...)`.

- [ ] **Step 1: Write failing schema tests**

Add tests that express the desired protocol:

```python
def test_direct_tool_plan_rejects_matched_plan_without_steps():
    with pytest.raises(ValidationError):
        DirectToolPlan(status="matched", steps=[], summary="matched")


def test_direct_tool_plan_allows_not_applicable_without_steps():
    plan = DirectToolPlan(status="not_applicable", steps=[], summary="use Skill")
    assert plan.steps == []
```

Define the planned shapes in the test imports:

```python
class DirectToolStep(BaseModel):
    step_id: str
    tool_id: str
    arguments: dict[str, dict[str, Any]]
    reason: str


class DirectToolPlan(BaseModel):
    status: Literal["matched", "not_applicable", "needs_input"]
    steps: list[DirectToolStep]
    missing_inputs: list[str] = Field(default_factory=list)
    summary: str
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_schemas.py -q
```

Expected: collection or import failure because the direct Tool schemas do not exist.

- [ ] **Step 3: Implement the minimal schemas**

Add the schemas to `schemas.py`. Use a Pydantic model validator so `status="matched"` requires one to three steps, `needs_input` requires at least one `missing_inputs` entry, and other statuses require zero steps. Add:

```python
class DirectToolVerification(BaseModel):
    status: Literal["passed", "failed", "inconclusive"]
    summary: str
```

Change `ExecutionCommand.skill_id` and `skill_version` to `UUID | None` and `int | None`, both defaulting to `None`; the existing `SkillRunner` must continue passing concrete values.

- [ ] **Step 4: Write failing agent-planning tests**

Add a capturing runtime test with three real `ToolDefinition` objects. Assert that:

```python
plan = agents.plan_tool_request(
    "查询孟明佳的采购申请，第一页每页10条",
    {"task_id": "user-request", "content": {}},
    tools,
)
assert plan.steps[0].tool_id == "yifeng_mes:queryPageListUsingGET_183"
assert plan.steps[0].arguments == {
    "query": {"applyBy": "孟明佳", "pageNo": 1, "pageSize": 10}
}
```

Also test boundary rejection for an unknown Tool ID, a write Tool, an undeclared parameter, an undeclared argument location, and more than three steps. The runtime’s captured request must contain compact Tool definitions but no credentials, base URL, response data, or Skill payload.

- [ ] **Step 5: Run the agent tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_agent_matching_runtime.py -q
```

Expected: failures because `plan_tool_request` and Tool-plan boundary validation do not exist.

- [ ] **Step 6: Implement Tool planning and verification**

Add these methods to `AgentSuite`:

```python
def plan_tool_request(
    self,
    user_request: str,
    task_context: dict[str, Any],
    tools: list[ToolDefinition],
) -> DirectToolPlan: ...

def verify_tool_result(
    self,
    user_request: str,
    plan: DirectToolPlan,
    step_results: list[StepResult],
) -> DirectToolVerification: ...
```

Pass only `tool_id`, `system_code`, description, side effect, and declared parameters to the model. In deterministic validation, require every selected Tool to be in the supplied set, require `side_effect == "read"`, allow only `query`, `path`, and `body` locations declared by that Tool, and reject unknown parameter names. Do not choose a Tool or fill a business value in validation code.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_schemas.py tests/test_agent_matching_runtime.py -q
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit Task 1**

```powershell
git add app/command_center/schemas.py app/command_center/agents.py tests/test_command_center_schemas.py tests/test_agent_matching_runtime.py
git commit -m "feat: add agent direct tool planning"
```

---

### Task 2: Execute read-only plans and retain safe evidence

**Files:**
- Create: `app/command_center/direct_tool_runner.py`
- Modify: `app/command_center/schemas.py`
- Test: `tests/test_direct_tool_runner.py`
- Test: `tests/test_tool_executor.py`

**Interfaces:**
- Consumes: a validated `DirectToolPlan`, `ToolCatalog.get(tool_id)`, and `ToolExecutor.execute(command)`.
- Produces: `DirectToolRunResult(status, step_results, outputs, evidence)` and `DirectToolRunner.run(plan, *, run_id)`.

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_direct_tool_runner.py` with an in-memory read catalog and recording executor. Cover:

```python
result = runner.run(plan, run_id=run_id)
assert result.status == "succeeded"
assert result.outputs == {"query": {"success": True, "result": {"records": []}}}
assert result.evidence == [
    {
        "step_id": "query",
        "tool_id": "yifeng_mes:queryPageListUsingGET_183",
        "arguments": {"query": {"applyBy": "孟明佳"}},
        "status": "succeeded",
        "request_summary": {"method": "GET", "path": "/jeecg-boot/purchase/apply/list"},
        "response_summary": {"status_code": 200},
    }
]
```

Add tests that the runner refuses a write Tool before invoking the executor, stops after a failed step, never places headers or credentials in evidence, and assigns `skill_id=None` on direct `ExecutionCommand` objects.

- [ ] **Step 2: Run runner tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_direct_tool_runner.py tests/test_tool_executor.py -q
```

Expected: import failure because `DirectToolRunner` does not exist or schema failure because direct commands do not permit null Skill identity.

- [ ] **Step 3: Implement the direct runner**

Create:

```python
@dataclass
class DirectToolRunResult:
    status: str
    step_results: list[StepResult]
    outputs: dict[str, Any]
    evidence: list[dict[str, Any]]


class DirectToolRunner:
    def __init__(self, catalog: ToolCatalog, executor: Executor): ...

    def run(self, plan: DirectToolPlan, *, run_id: UUID) -> DirectToolRunResult: ...
```

The runner must resolve each Tool from the same catalog used by the executor, reject non-read Tools, execute at most three steps, stop on failure, and build evidence only from Tool ID, arguments, status, request summary, and response summary. Never copy headers, cookies, credential values, or complete raw responses into evidence.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_direct_tool_runner.py tests/test_tool_executor.py tests/test_v1_vertical_loop.py -q
```

Expected: direct runner tests pass and the existing Skill runner remains green.

- [ ] **Step 5: Commit Task 2**

```powershell
git add app/command_center/direct_tool_runner.py app/command_center/schemas.py tests/test_direct_tool_runner.py tests/test_tool_executor.py
git commit -m "feat: execute read-only tool plans"
```

---

### Task 3: Add the Tool-first LangGraph branch and preserve Skill fallback

**Files:**
- Modify: `app/command_center/execution_graph.py`
- Modify: `app/main.py`
- Test: `tests/test_execution_graph.py`
- Test: `tests/test_connected_mes_execution.py`
- Test: `tests/test_v1_vertical_loop.py`

**Interfaces:**
- Consumes: `ExecutionDependencies.tools()`, `ExecutionDependencies.direct_runner`, `AgentSuite.plan_tool_request`, and `AgentSuite.verify_tool_result`.
- Produces: task-run states with `execution_mode="tool" | "skill"`, Tool outputs, and safe `tool_evidence`.

- [ ] **Step 1: Write failing graph tests for direct Tool routing**

Add graph fixtures with one read Tool and fake planning/verification agents. Assert:

```python
result = graph.invoke({"user_request": "查询孟明佳的采购申请"})
assert result["status"] == "succeeded"
assert result["execution_mode"] == "tool"
assert result["final_response"]["outputs"]["query"]["success"] is True
assert result["final_response"]["tool_evidence"][0]["tool_id"].startswith("yifeng_mes:")
```

Add tests for `not_applicable` falling through to the existing Skill matcher, `needs_input` returning a clear failure without Tool execution, Tool execution failure skipping verification, and an empty Skill list still succeeding when a direct Tool matches.

- [ ] **Step 2: Run graph tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_execution_graph.py tests/test_connected_mes_execution.py -q
```

Expected: constructor or state failures because the graph has no Tool-first dependencies or nodes.

- [ ] **Step 3: Implement Tool-first graph routing**

Extend `ExecutionDependencies`:

```python
tools: Callable[[], list[ToolDefinition]]
direct_runner: DirectToolRunner
```

Add state keys `tools`, `tool_plan`, `direct_run_result`, `tool_verification`, `execution_mode`, and optional `task_context`. Add nodes in this order:

```text
load_context
  -> plan_direct_tool
      matched -> execute_direct_tool -> verify_direct_tool -> END
      needs_input -> END
      not_applicable -> match_request -> existing Skill path
```

The Tool branch must persist `outputs` and `tool_evidence` in `final_response`. The existing Skill nodes must retain their current behavior and mark `execution_mode="skill"`.

- [ ] **Step 4: Wire allowlisted MES Tools in `app/main.py`**

Build one credential-aware `ToolExecutor` over `RoutingToolCatalog`, reuse it for `SkillRunner` and `DirectToolRunner`, and provide all read-only definitions from configured external system profiles:

```python
def executable_tools() -> list[ToolDefinition]:
    return [
        tool
        for system_code in profiles
        for tool in catalogs.get(system_code).definitions()
        if tool.side_effect == "read"
    ]
```

This list remains constrained by each trusted system profile’s exact method/path permissions.

- [ ] **Step 5: Run graph and integration tests and verify GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_execution_graph.py tests/test_connected_mes_execution.py tests/test_v1_vertical_loop.py -q
```

Expected: direct Tool scenarios and all existing Skill scenarios pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add app/command_center/execution_graph.py app/main.py tests/test_execution_graph.py tests/test_connected_mes_execution.py tests/test_v1_vertical_loop.py
git commit -m "feat: route task execution through tools first"
```

---

### Task 4: Create a persisted detail run from a selected list row

**Files:**
- Modify: `app/command_center/router.py`
- Modify: `app/command_center/service.py`
- Modify: `app/command_center/execution_graph.py`
- Test: `tests/test_command_center_api.py`
- Test: `tests/test_command_center_service.py`

**Interfaces:**
- Consumes: a parent task run containing a record array and a `record_id` selected from that array.
- Produces: `POST /task-runs/{run_id}/details` and `CommandCenterService.create_task_detail_run(run_id, record_id)` returning a separately persisted Tool-mode task run with `parent_run_id`.

- [ ] **Step 1: Write failing API and service tests**

Add:

```python
response = client.post(
    f"/task-runs/{parent_run_id}/details",
    json={"record_id": "2037430718812770305"},
)
assert response.status_code == 201
assert response.json()["parent_run_id"] == str(parent_run_id)
assert response.json()["status"] == "succeeded"
```

The service fixture must persist a parent list run whose nested output contains records. Assert that an unknown parent run returns 404, a record ID absent from the stored result returns 404, a row without an `id` cannot be selected, and the selected row is passed into graph state as `task_context.selected_record`.

- [ ] **Step 2: Run service/API tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_service.py tests/test_command_center_api.py -q
```

Expected: 404 or attribute failure because the detail endpoint and service method do not exist.

- [ ] **Step 3: Implement bounded record lookup and detail-run creation**

Add a request model:

```python
class CreateTaskDetailRequest(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)
```

Implement a bounded breadth-first lookup over `parent["final_response"]["outputs"]`: maximum depth 6, maximum 250 visited values, and exact string comparison against a record’s `id`. Do not accept an arbitrary row payload from the browser.

Invoke the graph with:

```python
{
    "user_request": "查看所选采购申请详情",
    "task_context": {"selected_record": selected_record},
}
```

Save the returned detail run under a new UUID and include `parent_run_id` in its payload. Extend `load_context` so the neutral task’s `content` contains the trusted `task_context`.

- [ ] **Step 4: Add the router endpoint**

Expose `POST /task-runs/{run_id}/details` with status 201. Map missing parent or row to 404 and invalid selection state to 409 without exposing stored raw output in errors.

- [ ] **Step 5: Run service/API tests and verify GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_service.py tests/test_command_center_api.py tests/test_execution_graph.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add app/command_center/router.py app/command_center/service.py app/command_center/execution_graph.py tests/test_command_center_api.py tests/test_command_center_service.py
git commit -m "feat: load purchase application details"
```

---

### Task 5: Add list-row detail interaction and visualization

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/commandCenter.ts`
- Modify: `frontend/src/components/TaskResultTable.vue`
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`
- Test: `frontend/src/components/__tests__/TaskResultTable.spec.ts`
- Test: `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

**Interfaces:**
- Consumes: Tool-mode `TaskRunView.final_response.outputs` and `POST /task-runs/{run_id}/details`.
- Produces: `createTaskDetailRun(parentRunId, recordId)`, `TaskResultTable`’s `view-detail` event, and a visible selected-record detail panel.

- [ ] **Step 1: Write failing table interaction tests**

Mount `TaskResultTable` with two records containing internal IDs. Assert that each row has one “查看详情” button, clicking it emits only the selected ID, and object-only or ID-less outputs show no detail action:

```typescript
await wrapper.get('[data-record-id="row-1"] [data-testid="view-detail"]').trigger('click')
expect(wrapper.emitted('view-detail')).toEqual([['row-1']])
```

- [ ] **Step 2: Run the table test and verify RED**

Run:

```powershell
npm test -- --run src/components/__tests__/TaskResultTable.spec.ts
```

Expected: no button or event exists.

- [ ] **Step 3: Implement the minimal table action**

Add optional prop `allowDetails: boolean = false`, emit `view-detail(recordId: string)`, and render a final action column only when details are enabled and `row.id` is a non-empty string. Keep the ID available to code but do not require the user to type it.

- [ ] **Step 4: Write failing panel/API tests**

Mock `createTaskRun` and `createTaskDetailRun`. Assert that a successful list run remains displayed while the detail call is pending, clicking a row calls the endpoint with the parent run ID and record ID, successful details render beneath the list, and a failed detail call shows an error without erasing the list.

- [ ] **Step 5: Run panel tests and verify RED**

Run:

```powershell
npm test -- --run src/components/__tests__/NaturalLanguageTaskPanel.spec.ts
```

Expected: missing API export or missing detail behavior.

- [ ] **Step 6: Implement frontend detail loading**

Add:

```typescript
export function createTaskDetailRun(parentRunId: string, recordId: string) {
  return request<TaskRunView>(`/task-runs/${parentRunId}/details`, {
    method: 'POST',
    body: JSON.stringify({ record_id: recordId }),
  })
}
```

Extend `TaskRunView` with optional `parent_run_id`, `execution_mode`, and `tool_evidence`. In `NaturalLanguageTaskPanel`, keep `run` and `detailRun` as separate refs, pass `allow-details` only to successful list results, show detail loading independently, and render detail outputs with `TaskResultTable` without recursive detail buttons.

- [ ] **Step 7: Run frontend tests and build and verify GREEN**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: all frontend tests pass and the production build succeeds. Existing Rollup chunk-size warnings are acceptable if unchanged.

- [ ] **Step 8: Commit Task 5**

```powershell
git add frontend/src/api/types.ts frontend/src/api/commandCenter.ts frontend/src/components/TaskResultTable.vue frontend/src/components/NaturalLanguageTaskPanel.vue frontend/src/components/__tests__/TaskResultTable.spec.ts frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts
git commit -m "feat: view purchase application details"
```

---

### Task 6: Verify the real read-only loop and protect Skill recording

**Files:**
- Modify: `docs/testing/2026-08-11-tool-first-purchase-readonly-acceptance.md`
- Test: `tests/test_real_mes_readonly_loop.py`
- Test: `tests/test_command_center_service.py`
- Test: `frontend/src/pages/__tests__/TestConsolePage.spec.ts`

**Interfaces:**
- Consumes: the complete Tool-first task flow, detail endpoint, existing browser recording endpoints, and existing system connection.
- Produces: reproducible automated regression evidence and a manual real-MES acceptance record.

- [ ] **Step 1: Add regression tests that direct Tool runs never persist Skills**

Capture `repository.list_published_skills()` and `repository.list_verified_candidates()` before and after a direct list run and a detail run. Assert both collections are unchanged. Run the existing recording lifecycle fixture and assert it can still reach its existing candidate or published terminal state.

- [ ] **Step 2: Run regression tests**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_real_mes_readonly_loop.py tests/test_command_center_service.py -q
```

Expected: all direct Tool and Skill recording regression tests pass.

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
conda run -n langgraph python -m pytest -q
cd frontend
npm test -- --run
npm run build
```

Expected: all backend and frontend tests pass; frontend production build succeeds.

- [ ] **Step 4: Perform real MES read-only acceptance**

With the existing keyring connection, execute these requests through the normal backend and frontend:

```text
查询采购申请列表第一页，每页10条
查询请购人孟明佳的采购申请列表
查询采购申请列表第二页，每页5条
```

Then click “查看详情” on an existing returned record. Confirm the task run reports `execution_mode="tool"`, the list query reuses `yifeng_mes:queryPageListUsingGET_183`, the detail run uses only the two allowlisted detail Tools, the UI shows main and line-item data, and no MES write request occurs.

- [ ] **Step 5: Record acceptance evidence**

Create `docs/testing/2026-08-11-tool-first-purchase-readonly-acceptance.md` containing the tested requests, run IDs, selected Tool IDs, record counts, detail status, test commands, and confirmation that credentials and raw sensitive payloads are omitted.

- [ ] **Step 6: Commit Task 6**

```powershell
git add tests/test_real_mes_readonly_loop.py tests/test_command_center_service.py frontend/src/pages/__tests__/TestConsolePage.spec.ts docs/testing/2026-08-11-tool-first-purchase-readonly-acceptance.md
git commit -m "test: verify tool-first purchase loop"
```
