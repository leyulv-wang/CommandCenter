# Demonstration Failure Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the demonstration workbench report the real failure stage and agent-produced reason instead of labeling every rejected recording as an automatic-test failure.

**Architecture:** LangGraph records deterministic failure metadata at the node where rejection occurs. `CommandCenterService` copies that metadata to the stable recording response and converts unexpected processing exceptions into a sanitized system-stage result. Vue consumes only the stable top-level fields and never infers stages from LangGraph internals.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, pytest, Vue 3, TypeScript, Vitest

## Global Constraints

- Keep the terminal recording state `needs_reteach` for backward-compatible retry behavior.
- Allowed failure stages are exactly `analysis`, `testing`, and `system`.
- Specific business reasons come from agent analysis or test results; frontend code must not recreate the business judgment.
- Old records without failure metadata use a neutral fallback message.
- Run Python through the local conda environment `langgraph`.

---

### Task 1: Learning graph emits deterministic failure feedback

**Files:**
- Modify: `tests/test_learning_graph.py`
- Modify: `app/command_center/learning_graph.py`

**Interfaces:**
- Consumes: `analysis.compilable`, `analysis.uncertainties`, `analysis.summary`, and harmless `test_results`.
- Produces: `LearningState.failure_stage: Literal["analysis", "testing"]` and `LearningState.failure_reasons: list[str]`.

- [ ] **Step 1: Write failing analysis-rejection and test-rejection tests**

Add an agent fixture returning:

```python
{
    "compilable": False,
    "summary": "实际调用了任务派发接口",
    "uncertainties": [
        {"description": "未观察到允许的创建采购申请接口"},
    ],
}
```

Assert that the graph returns:

```python
assert result["final_status"] == "rejected"
assert result["failure_stage"] == "analysis"
assert result["failure_reasons"] == ["未观察到允许的创建采购申请接口"]
assert "candidate_skill" not in result
assert "test_results" not in result
```

Extend the existing failed-test case so its failing result contains
`verification.summary == "参数变化测试未通过"` and assert:

```python
assert result["failure_stage"] == "testing"
assert result["failure_reasons"] == ["参数变化测试未通过"]
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_learning_graph.py -q
```

Expected: the new assertions fail because `failure_stage` and `failure_reasons` do not exist.

- [ ] **Step 3: Add minimal learning-state feedback**

In `app/command_center/learning_graph.py`:

```python
class LearningState(TypedDict, total=False):
    recording_id: str
    trace: Any
    analysis: Any
    candidate_skill: SkillDefinition
    test_plan: list[dict[str, Any]]
    test_results: list[dict[str, Any]]
    final_status: str
    errors: list[str]
    failure_stage: Literal["analysis", "testing"]
    failure_reasons: list[str]
```

For analysis rejection, extract non-empty `description` values from
`uncertainties`; fall back to `summary`. For test rejection, extract
`verification.summary` from each non-passing result and fall back to a neutral
test-category message.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_learning_graph.py -q
```

Expected: all learning-graph tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/learning_graph.py tests/test_learning_graph.py
git commit -m "fix: preserve learning rejection stage"
```

### Task 2: Recording responses expose feedback and sanitize system failures

**Files:**
- Modify: `tests/test_command_center_service.py`
- Modify: `app/command_center/service.py`

**Interfaces:**
- Consumes: `learning_graph.invoke()` result fields `final_status`, `failure_stage`, and `failure_reasons`.
- Produces: top-level recording fields `failure_stage` and `failure_reasons`.

- [ ] **Step 1: Write failing service tests**

Create one graph result:

```python
{
    "final_status": "rejected",
    "failure_stage": "analysis",
    "failure_reasons": ["未观察到创建采购申请接口"],
}
```

Assert the stopped recording persists those exact top-level fields. Add a graph
double whose `invoke()` raises `RuntimeError("secret provider detail")`; assert
the service returns and persists:

```python
assert stopped["status"] == "needs_reteach"
assert stopped["failure_stage"] == "system"
assert stopped["failure_reasons"] == [
    "系统处理演示时发生错误，请检查模型配置和服务日志后重试。"
]
assert "secret provider detail" not in str(stopped)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_service.py -q
```

Expected: the rejection metadata is absent and the exception escapes.

- [ ] **Step 3: Implement stable response fields**

Update `stop_recording()` so published results omit failure fields, rejected
results copy graph feedback, and unexpected learning exceptions are saved as a
sanitized `system` failure without exposing exception text to the API.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
conda run -n langgraph python -m pytest tests/test_command_center_service.py -q
```

Expected: all service tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/service.py tests/test_command_center_service.py
git commit -m "fix: expose recording failure feedback"
```

### Task 3: Demonstration workbench renders the real failure stage

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts`
- Modify: `frontend/src/pages/DemonstrationWorkbenchPage.vue`

**Interfaces:**
- Consumes: `RecordingView.failure_stage?: "analysis" | "testing" | "system"` and `failure_reasons?: string[]`.
- Produces: stage-correct progress highlighting, heading, and reason list.

- [ ] **Step 1: Write failing component tests**

Mock `createRecording`, `startRecording`, and `stopRecording`. For an analysis
rejection, make `stopRecording` return:

```typescript
{
  recording_id: 'recording-1',
  status: 'needs_reteach',
  objective: '创建采购申请',
  source_system: 'connected_system',
  source_task_id: 'purchase-demonstration',
  failure_stage: 'analysis',
  failure_reasons: ['未观察到创建采购申请接口'],
}
```

After starting and stopping, assert the page contains
`演示内容无法生成 Skill` and the reason, does not contain
`自动测试没有通过`, and the `learn` progress item is active. Add a legacy-record
case with no failure fields and assert the neutral fallback.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- DemonstrationWorkbenchPage.spec.ts
```

Expected: assertions fail because the component still hard-codes automatic-test
failure and test-stage highlighting.

- [ ] **Step 3: Implement typed feedback rendering**

Extend `RecordingView` with the optional failure fields. Store them after
`stopRecording()`. Derive:

- `analysis` title: `演示内容无法生成 Skill`;
- `testing` title: `自动测试没有通过`;
- `system` title: `系统处理失败`;
- missing stage title: `本次演示未能发布 Skill`.

Render `failure_reasons` as a list and calculate `stepState()` from the returned
failure stage. Keep the retry button behavior unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
Set-Location frontend
npm test -- DemonstrationWorkbenchPage.spec.ts
```

Expected: all demonstration-workbench tests pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api/types.ts frontend/src/pages/DemonstrationWorkbenchPage.vue frontend/src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts
git commit -m "fix: show actual demonstration failure stage"
```

### Task 4: Full verification

**Files:**
- No production files.

**Interfaces:**
- Consumes: completed backend and frontend changes.
- Produces: fresh evidence that the repository remains healthy.

- [ ] **Step 1: Run all backend tests**

```powershell
conda run -n langgraph python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run all frontend tests**

```powershell
Set-Location frontend
npm test
```

Expected: zero failures.

- [ ] **Step 3: Build the frontend**

```powershell
Set-Location frontend
npm run build
```

Expected: TypeScript checking and Vite build both exit successfully.

- [ ] **Step 4: Inspect repository state**

```powershell
git status --short
git diff --check
```

Expected: no whitespace errors; only known user-owned untracked artifacts may
remain.
