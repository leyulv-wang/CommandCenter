# URL User Approval Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `u001` create a purchase request and let `u002` open the same CommandCenter frontend through a URL parameter to see and complete the generated approval task.

**Architecture:** The frontend resolves a local test-user context from `?user=` and uses that ID for all task queries and completions. The purchase test system remains the source of truth: its existing purchase-request transaction also inserts one approval task assigned to `u002`, while the existing task APIs provide user filtering and completion.

**Tech Stack:** FastAPI, SQLite, Vue 3, TypeScript, Vitest, pytest

## Global Constraints

- Use only the fixed demo users `u001` and `u002`.
- Do not add login, passwords, sessions, JWT, or a user database.
- Unknown or missing `user` parameters fall back to `u001`.
- The approval task belongs to the purchase test system and is assigned to `u002`.
- Repeated requests with the same idempotency key must not duplicate either the purchase request or its approval task.
- Run Python through conda environment `langgraph`.
- Preserve the existing untracked evidence directory and research document.

---

### Task 1: Generate one idempotent purchase approval task

**Files:**
- Modify: `tests/test_external_systems.py`
- Modify: `external_systems/common.py`

**Interfaces:**
- Consumes: existing `POST /api/purchase-requests`, `GET /api/tasks`, and `POST /api/tasks/complete`.
- Produces: `POST /api/purchase-requests` response field `data.approval_task_id: str` and one pending task with `assignee_id="u002"`.

- [ ] **Step 1: Extend the purchase-request integration test**

Replace the current purchase-request assertions with behavior assertions covering the complete demo boundary:

```python
def test_purchase_request_creates_one_idempotent_u002_approval_task(tmp_path: Path):
    app = create_external_app(
        system_name="采购业务系统",
        system_code="connected_system",
        interface_type="workflow",
        workflow_template_id="purchase_request_001",
        task_type="purchase_review",
        task_form_code="purchase_task_result",
        database_path=tmp_path / "connected.sqlite3",
        seed_records=[],
        seed_tasks=[],
    )
    client = TestClient(app)
    payload = {"item_name": "签字笔", "quantity": 10, "reason": "库存不足"}
    headers = {"Idempotency-Key": "skill:purchase:create"}

    first = client.post("/api/purchase-requests", json=payload, headers=headers)
    second = client.post("/api/purchase-requests", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.json() == first.json()
    approval_task_id = first.json()["data"]["approval_task_id"]
    assert len(client.get("/api/submissions").json()["items"]) == 1
    assert client.get(
        "/api/tasks",
        params={"operator_id": "u001", "status": "pending"},
    ).json()["items"] == []
    u002_tasks = client.get(
        "/api/tasks",
        params={"operator_id": "u002", "status": "pending"},
    ).json()["items"]
    assert [task["task_id"] for task in u002_tasks] == [approval_task_id]
    assert u002_tasks[0]["content"] == {
        "purchase_request_id": "WORKFLOW-0001",
        "item_name": "签字笔",
        "quantity": 10,
        "reason": "库存不足",
        "applicant_id": "u001",
    }
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_external_systems.py::test_purchase_request_creates_one_idempotent_u002_approval_task -q
```

Expected: FAIL because the purchase endpoint does not create or return an approval task.

- [ ] **Step 3: Insert the approval task in the existing transaction**

After generating `ticket_id` in `create_purchase_request()`, allocate the next task row and insert:

```python
next_task_id = connection.execute(
    "select coalesce(max(id), 0) + 1 as next_id from tasks"
).fetchone()["next_id"]
approval_task_id = f"{system_code.upper()}-TASK-{next_task_id:04d}"
task_content = {
    "purchase_request_id": ticket_id,
    "item_name": request.item_name,
    "quantity": request.quantity,
    "reason": request.reason,
    "applicant_id": "u001",
}
connection.execute(
    """
    insert into tasks(
        task_id, title, task_type, form_code, content, status,
        assignee_id, created_at
    )
    values (?, ?, ?, ?, ?, 'pending', 'u002', ?)
    """,
    (
        approval_task_id,
        f"审批采购申请：{request.item_name}",
        task_type,
        task_form_code,
        json.dumps(task_content, ensure_ascii=False),
        created_at,
    ),
)
```

Add `"approval_task_id": approval_task_id` to `response["data"]`. Keep task creation before `_store_idempotent_response()` and the single `commit()`, so an idempotent replay returns the saved response without creating a second task.

- [ ] **Step 4: Run focused external-system tests**

Run:

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_external_systems.py -q
```

Expected: all external-system tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_external_systems.py external_systems/common.py
git commit -m "feat: create purchase approval task"
```

### Task 2: Resolve the current demo user from the URL

**Files:**
- Create: `frontend/src/userContext.ts`
- Create: `frontend/src/__tests__/userContext.spec.ts`

**Interfaces:**
- Produces: `TestUser`, `TEST_USERS`, and `resolveTestUser(search?: string): TestUser`.
- Consumed by: `TaskCenterPage.vue` in Task 3.

- [ ] **Step 1: Write URL-resolution tests**

```typescript
import { describe, expect, it } from 'vitest'
import { resolveTestUser } from '../userContext'

describe('resolveTestUser', () => {
  it('defaults to the applicant when the parameter is absent', () => {
    expect(resolveTestUser('').id).toBe('u001')
  })

  it('resolves the purchase approver', () => {
    expect(resolveTestUser('?user=u002')).toEqual({
      id: 'u002',
      name: '采购审批人',
      role: '采购审批',
    })
  })

  it('falls back for an unknown test user', () => {
    expect(resolveTestUser('?user=unknown').id).toBe('u001')
  })
})
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- src/__tests__/userContext.spec.ts
```

Expected: FAIL because `userContext.ts` does not exist.

- [ ] **Step 3: Implement the deterministic demo-user resolver**

Create:

```typescript
export interface TestUser {
  id: 'u001' | 'u002'
  name: string
  role: string
}

export const TEST_USERS: Record<TestUser['id'], TestUser> = {
  u001: { id: 'u001', name: '普通员工', role: '采购申请' },
  u002: { id: 'u002', name: '采购审批人', role: '采购审批' },
}

export function resolveTestUser(search = window.location.search): TestUser {
  const candidate = new URLSearchParams(search).get('user')
  return candidate === 'u002' ? TEST_USERS.u002 : TEST_USERS.u001
}
```

- [ ] **Step 4: Run the resolver tests and verify GREEN**

Run:

```powershell
Set-Location frontend
npm test -- src/__tests__/userContext.spec.ts
```

Expected: all three tests pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/userContext.ts frontend/src/__tests__/userContext.spec.ts
git commit -m "feat: resolve demo user from URL"
```

### Task 3: Apply the URL user to the task center

**Files:**
- Create: `frontend/src/pages/__tests__/TaskCenterPage.spec.ts`
- Modify: `frontend/src/pages/TaskCenterPage.vue`

**Interfaces:**
- Consumes: `resolveTestUser()` from Task 2.
- Produces: user-specific calls to `listTasks(operatorId, status)` and `completeTask(..., {operator_id, values})`.

- [ ] **Step 1: Write the TaskCenter integration test**

Mock only HTTP-facing API modules and mount the real page:

```typescript
import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { listExternalSystemForms, listExternalSystems } from '../../api/externalSystems'
import { listTasks } from '../../api/tasks'
import TaskCenterPage from '../TaskCenterPage.vue'

vi.mock('../../api/externalSystems', () => ({
  listExternalSystems: vi.fn(),
  listExternalSystemForms: vi.fn(),
}))
vi.mock('../../api/tasks', () => ({
  listTasks: vi.fn(),
  completeTask: vi.fn(),
}))
vi.mock('../../api/forms', () => ({
  getForm: vi.fn(),
  submitForm: vi.fn(),
}))

describe('TaskCenterPage demo user', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    window.history.replaceState({}, '', '/?user=u002')
    vi.mocked(listExternalSystems).mockResolvedValue([])
    vi.mocked(listExternalSystemForms).mockResolvedValue([])
    vi.mocked(listTasks).mockResolvedValue({ operator_id: 'u002', items: [] })
  })

  it('loads and labels the u002 task center', async () => {
    const wrapper = shallowMount(TaskCenterPage)
    await flushPromises()

    expect(wrapper.text()).toContain('采购审批人')
    expect(wrapper.text()).toContain('u002')
    expect(listTasks).toHaveBeenCalledWith('u002', 'pending')
    expect(listTasks).toHaveBeenCalledWith('u002', 'completed')
  })
})
```

- [ ] **Step 2: Run the page test and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- src/pages/__tests__/TaskCenterPage.spec.ts
```

Expected: FAIL because the page still uses the fixed `u001`.

- [ ] **Step 3: Use the resolved user throughout TaskCenter**

In `TaskCenterPage.vue`:

```typescript
import { resolveTestUser } from '../userContext'

const currentUser = resolveTestUser()
const operatorId = currentUser.id
```

Change the identity tag to:

```vue
<el-tag>
  {{ currentUser.name }}：{{ currentUser.id }} · {{ currentUser.role }}
</el-tag>
```

Keep the existing `listTasks(operatorId, ...)`, `DynamicForm :operator-id="operatorId"`, and completion calls. Hide the natural-language launch panel for the approver:

```vue
<NaturalLanguageTaskPanel v-if="currentUser.id === 'u001'" />
```

- [ ] **Step 4: Run all frontend tests and build**

Run:

```powershell
Set-Location frontend
npm test
npm run build
```

Expected: all tests and the TypeScript/Vite production build pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/pages/TaskCenterPage.vue frontend/src/pages/__tests__/TaskCenterPage.spec.ts
git commit -m "feat: show user-specific task center"
```

### Task 4: Verify the two-user vertical slice

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-url-user-approval-demo-design.md`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: verified services and an implemented design status.

- [ ] **Step 1: Run the complete backend suite**

```powershell
conda run --no-capture-output -n langgraph python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run the complete frontend suite and build**

```powershell
Set-Location frontend
npm test
npm run build
```

Expected: zero failures and a successful production build.

- [ ] **Step 3: Mark the design implemented**

Change:

```text
状态：已确认，待实施
```

to:

```text
状态：已实施
```

- [ ] **Step 4: Restart affected local services**

Restart the purchase system on port `8101` and the frontend on port `5173` using the existing project commands. Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8101/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/
```

Expected: purchase health reports `ok`; frontend returns HTTP 200.

- [ ] **Step 5: Run a harmless API-level demonstration**

Create one purchase request with a unique idempotency key, query `u001` and `u002` pending tasks, then complete the new task as `u002`. Verify:

- the request returns one `approval_task_id`;
- the new task is absent from `u001` pending tasks;
- the task is present in `u002` pending tasks;
- completion as `u002` succeeds;
- the task appears in `u002` completed tasks.

- [ ] **Step 6: Commit the implementation status**

```powershell
git add docs/superpowers/specs/2026-07-30-url-user-approval-demo-design.md
git commit -m "docs: mark URL user demo implemented"
```

- [ ] **Step 7: Inspect final repository state**

```powershell
git diff --check
git status --short
```

Expected: only the existing user-owned evidence directory and research document remain untracked.
