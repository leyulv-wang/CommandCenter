# Purchase Progress Tracking Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only LangChain Agent loop that starts from a user-selected purchase application and traces its purchase orders and receiving/warehouse records, with LangGraph orchestration and a simple visual progress result.

**Architecture:** Keep the existing natural-language purchase application query unchanged. Add a separate purchase-progress LangGraph invoked from a trusted saved result row. Three logical LangChain agents scope the selected record, dynamically call allowlisted MES Tools, and verify/summarize evidence; deterministic code enforces read-only permissions, schemas, resource limits, trusted-record selection, and audit evidence.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, LangChain 1.x `create_agent`, LangGraph 1.x, `langchain-openai`, httpx, Vue 3, TypeScript, Element Plus, Vitest, pytest.

## Global Constraints

- Use the local Conda environment `langgraph`; run Python through `conda run -n langgraph`.
- Do not hard-code API keys; continue reading model configuration from `.env.ai`.
- Only verified read operations may be exposed to the purchase tracking agents.
- A `GET` method is not sufficient proof of read-only behavior; endpoints with audit, complete, generate, update, or other mutation semantics remain forbidden.
- Users select a record from a saved task result; they never need to provide a MES internal ID or application number.
- Track only `采购申请 → 采购订单 → 收货/入库`; exclude invoice, payment, and financial settlement.
- Keep existing direct Tool querying, details, Skill recording, analysis, verification, and Microsoft Runtime adapter behavior intact.
- Semantic Tool choice and business association remain agent judgments; deterministic code only enforces trusted input, protocol, authorization, read-only policy, and resource limits.
- Automated tests use fake models and fake MES responses; only the final acceptance check may call the real MES read-only endpoints.
- Execute inline in the current session; do not dispatch subagents.

---

## File Structure

### New files

- `app/command_center/langchain_purchase_agents.py` — builds the LangChain agents, adapts allowlisted `ToolDefinition` objects into Agent Tools, records bounded Tool results, and exposes the three role methods.
- `app/command_center/purchase_tracking_graph.py` — owns the LangGraph state and orchestration for scope, trace, and verification.
- `tests/test_langchain_purchase_agents.py` — verifies Tool adaptation, dynamic multi-step execution, limits, read-only rejection, and structured role outputs.
- `tests/test_purchase_tracking_graph.py` — verifies graph transitions and business/technical terminal states.
- `frontend/src/components/PurchaseProgress.vue` — renders the compact stage timeline and expandable evidence.
- `frontend/src/components/__tests__/PurchaseProgress.spec.ts` — verifies progress visualization.
- `docs/testing/2026-08-11-purchase-progress-tracking-acceptance.md` — records automated and real MES acceptance evidence.

### Modified files

- `requirements.txt` — explicitly declares LangChain 1.x because application code will import it directly.
- `app/command_center/model.py` — adds a reusable `ChatOpenAI` factory using the existing `.env.ai` variables.
- `app/command_center/schemas.py` — defines internal agent handoff and public progress result schemas.
- `app/command_center/tool_catalog.py` — exposes shared deterministic Tool argument validation.
- `app/command_center/agents.py` — reuses the public validation helper for existing direct Tool plans.
- `app/data/system_profiles/yifeng_mes.json` — allowlists only the verified purchase order and receiving/warehouse read endpoints.
- `app/main.py` — composes the LangChain purchase agents and tracking graph without contacting MES at startup.
- `app/command_center/service.py` — finds the trusted saved row and creates a child purchase-progress task run.
- `app/command_center/router.py` — exposes the progress endpoint and validates its request body.
- `tests/test_tool_catalog.py` — protects argument validation and endpoint permissions.
- `tests/test_command_center_service.py` — protects trusted row selection and child-run persistence.
- `tests/test_command_center_api.py` — protects API success, missing record, and invalid state behavior.
- `tests/test_real_mes_readonly_loop.py` — adds the end-to-end fake MES purchase chain.
- `frontend/src/api/types.ts` — types structured progress results and new execution status.
- `frontend/src/api/commandCenter.ts` — calls the progress endpoint.
- `frontend/src/components/TaskResultTable.vue` — emits a progress action for trusted rows.
- `frontend/src/components/NaturalLanguageTaskPanel.vue` — invokes progress tracking and displays its result.
- `frontend/src/components/__tests__/TaskResultTable.spec.ts` — protects the new row action.
- `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts` — protects progress loading, success, and error states.

---

### Task 1: Define Purchase Tracking Protocols and Shared Tool Validation

**Files:**
- Modify: `app/command_center/schemas.py`
- Modify: `app/command_center/tool_catalog.py`
- Modify: `app/command_center/agents.py`
- Test: `tests/test_command_center_schemas.py`
- Test: `tests/test_tool_catalog.py`
- Test: `tests/test_agent_matching_runtime.py`

**Interfaces:**
- Produces: `PurchaseTrackingScope`, `PurchaseTrackingDraft`, `PurchaseProgressStage`, `PurchaseProgressResult`, and `validate_tool_arguments(tool, arguments) -> None`.
- Consumes: existing `ToolDefinition`, `StepResult`, and Pydantic v2.

- [ ] **Step 1: Write failing schema tests**

```python
def test_purchase_progress_result_accepts_multiple_records_per_stage():
    result = PurchaseProgressResult.model_validate({
        "status": "complete",
        "summary": "采购申请已生成订单并完成收货",
        "stages": [{
            "stage": "receiving",
            "status": "completed",
            "summary": "找到 2 条收货记录",
            "record_count": 2,
            "records": [{"orderNumber": "CGDD01"}, {"orderNumber": "CGDD01"}],
            "evidence_step_ids": ["receiving_1"],
        }],
    })
    assert result.stages[0].record_count == 2


def test_purchase_tracking_scope_requires_trusted_application_identity():
    with pytest.raises(ValidationError):
        PurchaseTrackingScope.model_validate({"application": {}, "goal": "追踪采购"})
```

- [ ] **Step 2: Run the schema tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_schemas.py -q
```

Expected: collection or import failure because the purchase tracking schemas do not exist.

- [ ] **Step 3: Add the typed handoff and final-result schemas**

```python
class PurchaseTrackingScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=500)
    application: dict[str, Any]
    application_id: str = Field(min_length=1, max_length=128)
    application_number: str = Field(min_length=1, max_length=128)


class PurchaseTrackingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["complete", "business_pending", "incomplete", "failed"]
    summary: str = Field(min_length=1, max_length=2_000)
    evidence_step_ids: list[str] = Field(default_factory=list, max_length=16)


class PurchaseProgressStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["application", "order", "receiving", "warehouse"]
    status: Literal["completed", "in_progress", "pending", "not_found", "failed"]
    summary: str = Field(min_length=1, max_length=2_000)
    record_count: int = Field(ge=0)
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    evidence_step_ids: list[str] = Field(default_factory=list, max_length=16)


class PurchaseProgressResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["complete", "business_pending", "incomplete", "failed"]
    summary: str = Field(min_length=1, max_length=2_000)
    stages: list[PurchaseProgressStage] = Field(min_length=1, max_length=4)
```

Add a model validator to `PurchaseTrackingScope` that copies identity only from the supplied trusted record and requires both `id` and `applyNo` to agree with `application_id` and `application_number`.

- [ ] **Step 4: Write failing Tool argument boundary tests**

```python
def test_validate_tool_arguments_rejects_unknown_query_parameter():
    tool = purchase_list_tool(query_names={"sourceCode"})
    with pytest.raises(ValueError, match="unknown parameter"):
        validate_tool_arguments(tool, {"query": {"madeUp": "x"}})


def test_validate_tool_arguments_rejects_non_read_tool():
    tool = replace(purchase_list_tool(), side_effect="write")
    with pytest.raises(ValueError, match="read-only"):
        validate_tool_arguments(tool, {"query": {}})
```

- [ ] **Step 5: Run Tool boundary tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_tool_catalog.py -q
```

Expected: import failure because `validate_tool_arguments` does not exist.

- [ ] **Step 6: Move direct-plan boundary logic into the shared helper**

Implement:

```python
def validate_tool_arguments(
    tool: ToolDefinition,
    arguments: dict[str, Any],
    *,
    require_read: bool = True,
) -> None:
    if require_read and tool.side_effect != "read":
        raise ValueError("Tool execution is read-only")
    declared = declared_argument_names(tool)
    for location, values in arguments.items():
        if location not in {"query", "path", "body"} or not isinstance(values, dict):
            raise ValueError("unsupported Tool argument location")
        if set(values) - declared[location]:
            raise ValueError("Tool arguments reference an unknown parameter")
```

Update `_validate_direct_tool_plan` to call this helper so the existing direct path and new LangChain path share one stable security invariant.

- [ ] **Step 7: Run targeted tests and confirm GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_schemas.py tests/test_tool_catalog.py tests/test_agent_matching_runtime.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit the protocol boundary**

```powershell
git add app/command_center/schemas.py app/command_center/tool_catalog.py app/command_center/agents.py tests/test_command_center_schemas.py tests/test_tool_catalog.py tests/test_agent_matching_runtime.py
git commit -m "feat: define purchase tracking boundaries"
```

---

### Task 2: Add LangChain Model Factory and Read-Only Agent Tool Adapter

**Files:**
- Modify: `requirements.txt`
- Modify: `app/command_center/model.py`
- Create: `app/command_center/langchain_purchase_agents.py`
- Create: `tests/test_langchain_purchase_agents.py`

**Interfaces:**
- Consumes: `ToolDefinition`, `ToolExecutor.execute(ExecutionCommand)`, the schemas from Task 1, and `.env.ai`.
- Produces: `build_chat_model_from_environment() -> BaseChatModel`, `PurchaseAgentRun`, and `LangChainPurchaseAgents.scope(...)`, `.trace(...)`, `.verify(...)`.

- [ ] **Step 1: Declare the direct LangChain dependency**

Add to `requirements.txt`:

```text
langchain>=1.2,<2
```

Do not change the existing Agent Framework pins.

- [ ] **Step 2: Write a failing model-factory test**

```python
def test_chat_model_factory_reuses_existing_ai_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=https://model.test/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=secret\n"
        "AI_CONFIG_TIMEOUT_SECONDS=12\n",
        encoding="utf-8",
    )
    model = build_chat_model_from_environment(env_file)
    assert model.model_name == "test-model"
```

- [ ] **Step 3: Run the factory test and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_langchain_purchase_agents.py -q
```

Expected: import failure because the factory and module do not exist.

- [ ] **Step 4: Implement the model factory without logging secrets**

```python
def build_chat_model_from_environment(config_path: Path | None = None) -> BaseChatModel:
    path = config_path or Path(os.getenv("COMMAND_CENTER_AI_ENV_FILE", ".env.ai"))
    load_dotenv(path, override=True)
    return ChatOpenAI(
        base_url=_required_env("AI_CONFIG_MODEL_BASE_URL"),
        api_key=SecretStr(_required_env("AI_CONFIG_API_KEY")),
        model=_required_env("AI_CONFIG_MODEL_NAME"),
        timeout=float(os.getenv("AI_CONFIG_TIMEOUT_SECONDS", "60")),
        temperature=0,
    )
```

Validate that timeout is finite and greater than zero, matching the current runtime boundary.

- [ ] **Step 5: Write failing adapter tests for dynamic Tool use and safety**

Use a fake `create_agent` implementation that captures messages and invokes registered Tools in this order:

```python
def test_trace_agent_can_use_previous_tool_output_for_next_call():
    result = agents.trace(scope)
    assert [item.tool_id for item in result.step_results] == [
        "yifeng_mes:queryPageListUsingGET_124",
        "yifeng_mes:receivingRecordsUsingGET_1",
    ]
    assert executor.commands[1].arguments["query"]["orderNumber"] == "CGDD01"


def test_agent_adapter_rejects_write_tool_before_model_invocation():
    with pytest.raises(ValueError, match="read-only"):
        LangChainPurchaseAgents(model, [write_tool], executor)


def test_agent_adapter_stops_after_tool_limit():
    with pytest.raises(PurchaseTrackingLimitError, match="Tool call limit"):
        agents.trace(scope)
```

- [ ] **Step 6: Run adapter tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_langchain_purchase_agents.py -q
```

Expected: failures because the adapter behavior is not implemented.

- [ ] **Step 7: Implement per-Tool LangChain wrappers and the run ledger**

Create one `StructuredTool` for each allowlisted `ToolDefinition`. Each wrapper accepts the stable envelope below and closes over its exact `tool_id`:

```python
class AgentToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: dict[str, Any] = Field(default_factory=dict)
    path: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
```

Before execution:

1. call `validate_tool_arguments(tool, arguments)`;
2. increment a call-scoped counter and enforce `max_tool_calls=8`;
3. build `ExecutionCommand` with a generated step ID and the shared run ID;
4. call the existing `ToolExecutor`;
5. append the complete `StepResult` to a call-scoped ledger;
6. return bounded JSON containing status and normalized output to the model;
7. never expose credentials, request headers, or model chain-of-thought.

- [ ] **Step 8: Implement the three role methods with LangChain `create_agent`**

Use `ToolStrategy` for structured results and `recursion_limit` for the model loop:

```python
scope_agent = create_agent(
    model=model,
    tools=[],
    system_prompt=SCOPE_PROMPT,
    response_format=ToolStrategy(PurchaseTrackingScope),
)

trace_agent = create_agent(
    model=model,
    tools=agent_tools,
    system_prompt=TRACE_PROMPT,
    response_format=ToolStrategy(PurchaseTrackingDraft),
)

verify_agent = create_agent(
    model=model,
    tools=[],
    system_prompt=VERIFY_PROMPT,
    response_format=ToolStrategy(PurchaseProgressResult),
)
```

Pass only the selected application, compact Tool metadata, and recorded `StepResult` evidence needed by each role. Return `PurchaseAgentRun(output, step_results, events)` from every method. Reject missing `structured_response` and malformed responses rather than fabricating a result.

- [ ] **Step 9: Run adapter tests and confirm GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_langchain_purchase_agents.py -q
```

Expected: all adapter tests pass without network access.

- [ ] **Step 10: Commit the LangChain adapter**

```powershell
git add requirements.txt app/command_center/model.py app/command_center/langchain_purchase_agents.py tests/test_langchain_purchase_agents.py
git commit -m "feat: add LangChain purchase agents"
```

---

### Task 3: Build the Purchase Tracking LangGraph

**Files:**
- Create: `app/command_center/purchase_tracking_graph.py`
- Create: `tests/test_purchase_tracking_graph.py`

**Interfaces:**
- Consumes: `LangChainPurchaseAgents.scope`, `.trace`, `.verify` and Task 1 schemas.
- Produces: `build_purchase_tracking_graph(PurchaseTrackingDependencies)` returning a compiled graph that accepts `selected_application` and emits `final_response`.

- [ ] **Step 1: Write failing graph transition tests**

```python
def test_graph_runs_scope_trace_and_verify_in_order():
    result = graph.invoke({"selected_application": application_record()})
    assert agents.calls == ["scope", "trace", "verify"]
    assert result["status"] == "succeeded"
    assert result["final_response"]["progress"]["status"] == "complete"


def test_graph_preserves_business_pending_as_successful_result():
    result = graph_with_no_order.invoke({"selected_application": application_record()})
    assert result["status"] == "succeeded"
    assert result["final_response"]["progress"]["status"] == "business_pending"


def test_graph_marks_tool_failure_as_technical_failure():
    result = graph_with_failed_step.invoke({"selected_application": application_record()})
    assert result["status"] == "failed"
    assert result["errors"] == ["采购进度追踪发生技术错误"]
```

- [ ] **Step 2: Run graph tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_purchase_tracking_graph.py -q
```

Expected: import failure because the graph module does not exist.

- [ ] **Step 3: Implement focused graph state and nodes**

```python
class PurchaseTrackingState(TypedDict, total=False):
    selected_application: dict[str, Any]
    scope: PurchaseTrackingScope
    trace_draft: PurchaseTrackingDraft
    step_results: list[StepResult]
    events: list[dict[str, Any]]
    progress: PurchaseProgressResult
    status: str
    final_response: dict[str, Any]
    errors: list[str]
```

Nodes:

- `scope_application`: require a trusted `id` and `applyNo`, then call the scope agent;
- `trace_chain`: run the dynamic Tool loop and preserve every `StepResult`;
- `verify_and_summarize`: call the verification agent with the scope, draft, and evidence;
- `finalize_failure`: emit a safe technical error without exposing credentials or raw exception text.

Edges:

```text
START → scope_application → trace_chain → verify_and_summarize → END
```

Each node catches only expected runtime, protocol, Tool, and limit errors. Unexpected exceptions remain logged server-side and become the same safe terminal response.

- [ ] **Step 4: Run graph tests and confirm GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_purchase_tracking_graph.py -q
```

Expected: all graph tests pass.

- [ ] **Step 5: Commit the graph**

```powershell
git add app/command_center/purchase_tracking_graph.py tests/test_purchase_tracking_graph.py
git commit -m "feat: orchestrate purchase progress tracking"
```

---

### Task 4: Allowlist Verified MES Purchase Chain Tools

**Files:**
- Modify: `app/data/system_profiles/yifeng_mes.json`
- Modify: `tests/test_system_profiles.py`
- Modify: `tests/test_tool_catalog.py`

**Interfaces:**
- Consumes: the cached or live MES OpenAPI document through the existing `ProfileCatalogRegistry`.
- Produces: read-only definitions for purchase order list/detail, receiving records, and warehouse notification list/detail.

- [ ] **Step 1: Write failing profile permission tests**

```python
@pytest.mark.parametrize("path", [
    "/jeecg-boot/jiafang.purchase.order/order/list",
    "/jeecg-boot/jiafang.purchase.order/order/listOrderDetailByMainId",
    "/jeecg-boot/jiafang.purchase.order/order/receivingRecords",
    "/jeecg-boot/jiafang.purchase.warehouse/purchaseWarehouse/list",
    "/jeecg-boot/jiafang.purchase.warehouse/purchaseWarehouse/listPurchaseWarehouseDetailByMainId",
])
def test_yifeng_profile_allows_purchase_tracking_reads(path):
    profile = load_system_profile(Path("app/data/system_profiles/yifeng_mes.json"))
    assert profile.permission_for("GET", path).side_effect == "read"
```

Also assert that known audit, complete, generate, update, and delete paths have no permission.

- [ ] **Step 2: Run profile tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_system_profiles.py tests/test_tool_catalog.py -q
```

Expected: the new paths are not currently permitted.

- [ ] **Step 3: Add only the verified read permissions**

Add the five exact `GET` paths from Step 1 with `"side_effect": "read"`. Do not add wildcard paths or nearby action endpoints.

- [ ] **Step 4: Verify Tool definitions from an OpenAPI fixture**

Build a minimal OpenAPI test fixture containing the five operations and assert that the resulting Tool definitions expose `sourceCode`, `orderNumber`, `purchaseOrder`, `mainCode`, `pageNo`, and `pageSize` where declared by the document.

- [ ] **Step 5: Run profile and catalog tests and confirm GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_system_profiles.py tests/test_tool_catalog.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the allowlist**

```powershell
git add app/data/system_profiles/yifeng_mes.json tests/test_system_profiles.py tests/test_tool_catalog.py
git commit -m "feat: allow purchase tracking read tools"
```

---

### Task 5: Compose the Backend and Expose a Trusted Progress Endpoint

**Files:**
- Modify: `app/main.py`
- Modify: `app/command_center/service.py`
- Modify: `app/command_center/router.py`
- Modify: `tests/test_command_center_service.py`
- Modify: `tests/test_command_center_api.py`

**Interfaces:**
- Consumes: `build_purchase_tracking_graph`, saved task-run outputs, and the existing system credential store.
- Produces: `POST /task-runs/{run_id}/purchase-progress` with body `{ "record_id": "..." }` and a persisted child `TaskRunView`.

- [ ] **Step 1: Write failing service tests for trusted row selection**

```python
def test_create_purchase_progress_run_uses_saved_record_not_request_payload(service):
    parent = save_parent_run_with_records(service, [application_record()])
    result = service.create_purchase_progress_run(parent["run_id"], application_record()["id"])
    assert tracking_graph.inputs == [{"selected_application": application_record()}]
    assert result["parent_run_id"] == parent["run_id"]


def test_create_purchase_progress_run_rejects_record_missing_from_parent(service):
    parent = save_parent_run_with_records(service, [application_record()])
    with pytest.raises(KeyError):
        service.create_purchase_progress_run(parent["run_id"], "untrusted-id")
```

- [ ] **Step 2: Run service tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_service.py -q
```

Expected: `create_purchase_progress_run` is missing.

- [ ] **Step 3: Add the service dependency and child-run method**

Extend `CommandCenterService.__init__` with optional `purchase_tracking_graph`. Implement:

```python
def create_purchase_progress_run(self, run_id: UUID | str, record_id: str) -> dict[str, Any]:
    parent_run_id = UUID(str(run_id))
    parent = self.repository.get_task_run(parent_run_id)
    selected = _find_record_by_id(parent.get("final_response", {}).get("outputs"), record_id)
    if selected is None:
        raise KeyError("record is not present in the saved task result")
    if self.purchase_tracking_graph is None:
        raise RuntimeError("purchase tracking is not configured")
    child_run_id = uuid4()
    result = self.purchase_tracking_graph.invoke({"selected_application": selected})
    payload = {
        "run_id": str(child_run_id),
        "parent_run_id": str(parent_run_id),
        "user_request": "追踪所选采购申请进度",
        **jsonable_encoder(result),
    }
    self.repository.save_task_run(child_run_id, payload)
    return payload
```

- [ ] **Step 4: Write failing API contract tests**

```python
def test_purchase_progress_endpoint_returns_child_run(client):
    response = client.post(
        f"/task-runs/{parent_run_id}/purchase-progress",
        json={"record_id": "application-1"},
    )
    assert response.status_code == 201
    assert response.json()["final_response"]["progress"]["status"] == "complete"


def test_purchase_progress_endpoint_hides_missing_record_detail(client):
    response = client.post(
        f"/task-runs/{parent_run_id}/purchase-progress",
        json={"record_id": "unknown"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "task run record not found"
```

- [ ] **Step 5: Add request schema and route**

```python
class CreatePurchaseProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1, max_length=128)
```

Map missing parent or record to `404`, unconfigured tracking to `409`, and external Tool failures to the persisted graph result rather than leaking exceptions.

- [ ] **Step 6: Compose the tracking graph in `build_command_center_components`**

Create the Chat model, `LangChainPurchaseAgents`, and graph only when the default execution components are composed. Reuse `execution_catalog`, `execution_executor`, system credentials, and the lazily loaded profile catalog. Construction must not call the MES network; Tool definitions are loaded at the first progress request.

If lazy composition needs a provider, inject a callable that returns the current `yifeng_mes` read Tool definitions and let the tracking graph resolve them at invocation time.

- [ ] **Step 7: Run backend endpoint tests and confirm GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_service.py tests/test_command_center_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit backend integration**

```powershell
git add app/main.py app/command_center/service.py app/command_center/router.py tests/test_command_center_service.py tests/test_command_center_api.py
git commit -m "feat: expose purchase progress tracking"
```

---

### Task 6: Add a Fake MES End-to-End Purchase Chain

**Files:**
- Modify: `tests/test_real_mes_readonly_loop.py`

**Interfaces:**
- Consumes: the endpoint from Task 5 and the LangChain agent factory injection points from Task 2.
- Produces: deterministic integration evidence that a selected application drives order and receiving queries using values returned by earlier Tools.

- [ ] **Step 1: Write the failing complete-chain integration test**

```python
def test_selected_application_traces_order_and_receiving_without_user_internal_ids():
    parent = create_purchase_list_run("查询孟明佳的采购申请")
    progress = client.post(
        f"/task-runs/{parent['run_id']}/purchase-progress",
        json={"record_id": "application-1"},
    ).json()
    assert progress["status"] == "succeeded"
    assert progress["final_response"]["progress"]["status"] == "complete"
    assert mes_requests[0].params["sourceCode"] == "CGSQ01"
    assert mes_requests[1].params["orderNumber"] == "CGDD01"
```

- [ ] **Step 2: Add business-pending and multi-record fixtures**

Cover:

- no purchase order returns `business_pending` and no receiving Tool call;
- one application with two orders queries and retains both branches;
- one order with two receiving records reports `record_count == 2`;
- a `401` invalidates the stored credential and returns technical failure;
- no request uses a write endpoint.

- [ ] **Step 3: Run the integration tests and confirm RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_real_mes_readonly_loop.py -q
```

Expected: new chain assertions fail until the endpoint composition and fake Agent loop are fully connected.

- [ ] **Step 4: Complete only the missing integration seams**

Adjust dependency injection, fake Agent responses, or bounded response conversion. Do not add business keyword rules or sample-specific ID branches. Classify each failure as implementation, context, prompt/protocol, fixture, or test-assumption defect before changing production code.

- [ ] **Step 5: Run integration tests and confirm GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_real_mes_readonly_loop.py -q
```

Expected: all fake MES read-only tests pass.

- [ ] **Step 6: Commit the backend vertical slice**

```powershell
git add tests/test_real_mes_readonly_loop.py app/command_center/langchain_purchase_agents.py app/command_center/purchase_tracking_graph.py app/main.py
git commit -m "test: verify purchase progress agent loop"
```

---

### Task 7: Add the Minimal Progress UI

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/commandCenter.ts`
- Modify: `frontend/src/components/TaskResultTable.vue`
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`
- Create: `frontend/src/components/PurchaseProgress.vue`
- Modify: `frontend/src/components/__tests__/TaskResultTable.spec.ts`
- Modify: `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`
- Create: `frontend/src/components/__tests__/PurchaseProgress.spec.ts`

**Interfaces:**
- Consumes: `POST /task-runs/{run_id}/purchase-progress` and `final_response.progress`.
- Produces: row-level “追踪采购进度” action and a stage list with expandable evidence.

- [ ] **Step 1: Write failing row-action tests**

```typescript
it('emits the trusted row id for purchase progress tracking', async () => {
  const wrapper = mount(TaskResultTable, {
    props: { outputs: { records: [{ id: 'row-1', applyNo: 'CGSQ01' }] }, allowProgress: true },
  })
  await wrapper.get('[data-testid="track-progress"]').trigger('click')
  expect(wrapper.emitted('track-progress')).toEqual([['row-1']])
})
```

- [ ] **Step 2: Write failing progress visualization tests**

```typescript
it('renders all purchase stages and record counts', () => {
  const wrapper = mount(PurchaseProgress, { props: { progress: completeProgress } })
  expect(wrapper.text()).toContain('采购申请')
  expect(wrapper.text()).toContain('采购订单')
  expect(wrapper.text()).toContain('收货')
  expect(wrapper.text()).toContain('2 条记录')
})
```

- [ ] **Step 3: Run component tests and confirm RED**

Run:

```powershell
Set-Location frontend
npm test -- --run src/components/__tests__/TaskResultTable.spec.ts src/components/__tests__/PurchaseProgress.spec.ts src/components/__tests__/NaturalLanguageTaskPanel.spec.ts
```

Expected: missing component, props, emits, and API function failures.

- [ ] **Step 4: Add API and TypeScript types**

```typescript
export type PurchaseProgressStatus = 'complete' | 'business_pending' | 'incomplete' | 'failed'

export interface PurchaseProgressStage {
  stage: 'application' | 'order' | 'receiving' | 'warehouse'
  status: 'completed' | 'in_progress' | 'pending' | 'not_found' | 'failed'
  summary: string
  record_count: number
  records: Array<Record<string, unknown>>
  evidence_step_ids: string[]
}

export interface PurchaseProgressResult {
  status: PurchaseProgressStatus
  summary: string
  stages: PurchaseProgressStage[]
}
```

Extend `TaskRunView.final_response` with optional `progress`. Add:

```typescript
export function createPurchaseProgressRun(parentRunId: string, recordId: string) {
  return request<TaskRunView>(`/task-runs/${parentRunId}/purchase-progress`, {
    method: 'POST',
    body: JSON.stringify({ record_id: recordId }),
  })
}
```

- [ ] **Step 5: Implement the row action and progress component**

`TaskResultTable` receives `allowProgress`, emits `track-progress`, and shows the new button only when the row contains a non-empty trusted `id` and an application number.

`PurchaseProgress.vue` renders stages in returned order, uses simple Chinese labels, shows the summary and record count, and places stage records inside a closed `<details>` element. Do not build charts, animations, or new navigation.

- [ ] **Step 6: Connect the panel loading and terminal states**

`NaturalLanguageTaskPanel` keeps list results visible while progress loads, calls `createPurchaseProgressRun`, and renders `PurchaseProgress` when `final_response.progress` exists. API errors appear in a dedicated progress error block and do not erase the original query result.

- [ ] **Step 7: Run component tests and confirm GREEN**

Run:

```powershell
Set-Location frontend
npm test -- --run src/components/__tests__/TaskResultTable.spec.ts src/components/__tests__/PurchaseProgress.spec.ts src/components/__tests__/NaturalLanguageTaskPanel.spec.ts
```

Expected: all selected frontend tests pass.

- [ ] **Step 8: Commit the UI**

```powershell
git add frontend/src/api/types.ts frontend/src/api/commandCenter.ts frontend/src/components/TaskResultTable.vue frontend/src/components/NaturalLanguageTaskPanel.vue frontend/src/components/PurchaseProgress.vue frontend/src/components/__tests__
git commit -m "feat: visualize purchase progress"
```

---

### Task 8: Full Verification and Read-Only Acceptance

**Files:**
- Create: `docs/testing/2026-08-11-purchase-progress-tracking-acceptance.md`
- Modify only if failures expose real defects: files changed in Tasks 1-7

**Interfaces:**
- Consumes: complete backend and frontend implementation.
- Produces: reproducible test evidence and a real MES read-only acceptance record.

- [ ] **Step 1: Run the full backend suite**

Run:

```powershell
conda run -n langgraph python -m pytest -q
```

Expected: all backend tests pass.

- [ ] **Step 2: Run the full frontend suite and production build**

Run:

```powershell
Set-Location frontend
npm test -- --run
npm run build
```

Expected: all frontend tests pass and Vite build exits successfully.

- [ ] **Step 3: Start the local services and perform a real MES read-only trace**

Start the backend and frontend using the existing project commands. In the UI:

1. query a known person's purchase applications;
2. select one returned record;
3. click “追踪采购进度”;
4. compare application, order, receiving, and warehouse stages with the MES pages;
5. inspect backend events and confirm every Tool was allowlisted and read-only;
6. confirm no MES data changed.

Do not run the acceptance if the stored MES credential is unavailable. Record that as an external prerequisite, not an implementation success.

- [ ] **Step 4: Write the acceptance record with exact evidence**

Document:

- commit under test;
- backend and frontend command outputs;
- sanitized task wording;
- selected record identifiers only where already visible in the authorized MES session;
- Tool IDs and read-only paths called;
- returned business state;
- whether the result matched MES;
- explicit confirmation that no write Tool was called;
- any remaining limitations.

- [ ] **Step 5: Commit acceptance evidence**

```powershell
git add docs/testing/2026-08-11-purchase-progress-tracking-acceptance.md
git commit -m "test: accept purchase progress tracking"
```

