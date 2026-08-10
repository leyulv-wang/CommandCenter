# Task Result List Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw JSON as the primary task result with a large, generic list table while preserving diagnostic JSON in a collapsed section.

**Architecture:** A focused `TaskResultTable` component receives `final_response.outputs`, recursively locates the first record-object array, derives dynamic columns, and renders a responsive table. The task panel remains responsible for execution state, while the test-console page changes only its desktop grid proportion.

**Tech Stack:** Vue 3, TypeScript, Vitest, Vue Test Utils, Vite

## Global Constraints

- Desktop task execution and learning panels use approximately 70% / 30% width.
- Rendering must not hard-code MES field names or business status meanings.
- The original JSON remains available only in a collapsed diagnostic section.
- Mobile layout remains a single vertical column.
- No new frontend dependencies.

---

### Task 1: Generic task-result table

**Files:**
- Create: `frontend/src/components/TaskResultTable.vue`
- Create: `frontend/src/components/__tests__/TaskResultTable.spec.ts`
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`
- Modify: `frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

**Interfaces:**
- Consumes: prop `outputs?: Record<string, unknown>`.
- Produces: a semantic table for the first nested array of plain record objects, plus a collapsed raw-output section.

- [ ] **Step 1: Write failing component tests**

Test nested extraction, dynamic columns, null rendering, empty arrays, and collapsed JSON:

```ts
const outputs = {
  query: { result: { records: [{ applyNo: 'CGSQ01', applyDate: '2026-04-22' }] } },
}
const wrapper = mount(TaskResultTable, { props: { outputs } })
expect(wrapper.get('table').text()).toContain('CGSQ01')
expect(wrapper.get('details').attributes('open')).toBeUndefined()
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `npm test -- --run src/components/__tests__/TaskResultTable.spec.ts src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

Expected: FAIL because `TaskResultTable.vue` does not exist and the task panel still renders a primary JSON block.

- [ ] **Step 3: Implement the generic renderer**

`TaskResultTable.vue` will use bounded recursive traversal and deterministic formatting:

```ts
type Row = Record<string, unknown>

function findRecordArray(value: unknown, depth = 0): Row[] | null {
  if (depth > 6) return null
  if (Array.isArray(value)) {
    return value.every(isPlainObject) ? value as Row[] : null
  }
  if (!isPlainObject(value)) return null
  for (const child of Object.values(value)) {
    const found = findRecordArray(child, depth + 1)
    if (found) return found
  }
  return null
}
```

Derive a stable union of record keys, render primitive values directly, `null` as `—`, nested values as compact JSON, and show “查询成功，暂无记录” for an empty detected record array. Put `JSON.stringify(outputs, null, 2)` inside a closed `<details>` element.

- [ ] **Step 4: Replace the task panel JSON block**

```vue
<TaskResultTable
  v-if="run.final_response?.outputs"
  :outputs="run.final_response.outputs"
/>
```

Remove the computed `formattedOutputs` and old primary `<pre>` block.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `npm test -- --run src/components/__tests__/TaskResultTable.spec.ts src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/TaskResultTable.vue frontend/src/components/__tests__/TaskResultTable.spec.ts frontend/src/components/NaturalLanguageTaskPanel.vue frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts
git commit -m "feat: visualize task list results"
```

### Task 2: Expand the task execution area

**Files:**
- Modify: `frontend/src/pages/TestConsolePage.vue`
- Modify: `frontend/src/pages/__tests__/TestConsolePage.spec.ts`

**Interfaces:**
- Consumes: the existing two child panels.
- Produces: desktop `7fr / 3fr` proportions and unchanged mobile stacking.

- [ ] **Step 1: Write a failing layout test**

Add stable layout classes to the child wrappers and assert their presence:

```ts
expect(wrapper.get('.console-grid').classes()).toContain('result-focused')
```

- [ ] **Step 2: Run the page test and confirm RED**

Run: `npm test -- --run src/pages/__tests__/TestConsolePage.spec.ts`

Expected: FAIL because the result-focused grid class does not exist.

- [ ] **Step 3: Implement the 70/30 layout**

```css
.console-grid.result-focused {
  grid-template-columns: minmax(0, 7fr) minmax(280px, 3fr);
}
```

Keep the current media rule that changes `.console-grid` to `grid-template-columns: 1fr` below 860px.

- [ ] **Step 4: Run frontend verification**

Run: `npm test`

Expected: all frontend tests pass.

Run: `npm run build`

Expected: Vue type-check and Vite production build succeed.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/pages/TestConsolePage.vue frontend/src/pages/__tests__/TestConsolePage.spec.ts
git commit -m "feat: expand task result workspace"
```
