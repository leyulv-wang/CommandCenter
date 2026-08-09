# Minimal CommandCenter Test Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy multi-page Vue frontend with one minimal test console for natural-language execution and browser-recording Skill results.

**Architecture:** `TestConsolePage` owns recording loading, selection, and polling. Focused presentational components render the selected learning result and recording history, while the existing task-run API remains the only natural-language execution path. A small pure presentation module converts protocol statuses and untrusted learning-result payloads into UI-safe labels without making business decisions.

**Tech Stack:** Vue 3, TypeScript, Vite, Element Plus, Vitest, Vue Test Utils

## Global Constraints

- The formal frontend remains under `frontend/`.
- The application has exactly one active page and no sidebar navigation.
- Keep only natural-language execution, latest learning result, and recent browser-extension recordings.
- The browser extension remains the only recording control; the web page never starts or stops a recording.
- Skill matching, authorization, and execution readiness remain backend decisions.
- `api_candidate` means “API Skill 已生成，等待执行连接”; it is not failed, published, or executable.
- Do not modify backend APIs, the local test business system, or the browser extension.
- Use the palette and responsive behavior defined in `docs/superpowers/specs/2026-08-09-minimal-command-center-test-console-design.md`.
- Preserve visible keyboard focus and respect `prefers-reduced-motion`.

---

## File Map

- Create `frontend/src/recordingPresentation.ts`: pure status labels, tones, terminal-state detection, and safe Skill summary extraction.
- Create `frontend/src/components/LatestLearningResult.vue`: selected recording status and Skill details.
- Create `frontend/src/components/RecordingHistory.vue`: recent recording selector.
- Create `frontend/src/pages/TestConsolePage.vue`: data loading, polling, selection, and layout orchestration.
- Modify `frontend/src/components/NaturalLanguageTaskPanel.vue`: concise test-console copy and accessible execution result styling; retain existing task API behavior.
- Modify `frontend/src/api/types.ts`: typed extension recording detail and candidate Skill result.
- Modify `frontend/src/App.vue`: mount only `TestConsolePage`.
- Replace `frontend/src/styles/global.css`: single-page test-console tokens and responsive shell.
- Replace frontend tests with focused console and component tests.
- Delete legacy page and form-only component files after the new app no longer imports them.

### Task 1: Recording presentation contract

**Files:**
- Create: `frontend/src/recordingPresentation.ts`
- Create: `frontend/src/__tests__/recordingPresentation.spec.ts`
- Modify: `frontend/src/api/types.ts`

**Interfaces:**
- Consumes: raw `ExtensionRecordingStatus`, `RecordingSummary`, and `learning_result` JSON returned by the existing backend.
- Produces: `isRecordingTerminal(status): boolean`, `recordingStatusPresentation(status): { label: string; detail: string; tone: RecordingTone }`, and `extractCandidateSkill(recording): CandidateSkillSummary | null`.

- [ ] **Step 1: Write failing pure-function tests**

```ts
expect(recordingStatusPresentation('api_candidate')).toEqual({
  label: 'API Skill 已生成',
  detail: '等待业务系统配置执行连接',
  tone: 'waiting',
})
expect(isRecordingTerminal('analyzing')).toBe(false)
expect(isRecordingTerminal('api_candidate')).toBe(true)
expect(extractCandidateSkill(recording)).toEqual({
  name: '查询采购申请列表',
  status: 'candidate',
  executionVerification: 'pending_system_connection',
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend && npm test -- --run src/__tests__/recordingPresentation.spec.ts`

Expected: FAIL because `recordingPresentation.ts` and the typed detail contract do not exist.

- [ ] **Step 3: Add the typed detail contract and pure presentation helpers**

Define these public types in `api/types.ts`:

```ts
export interface CandidateSkillSummary {
  name: string
  status: string
  executionVerification?: string
}

export interface ExtensionRecordingDetail extends RecordingSummary {
  learning_result?: {
    final_status?: string
    execution_verification?: string
    candidate_skill?: { name?: string; status?: string }
  }
}
```

Implement exhaustive status copy in the pure module. Treat only `created`, `recording`, `recorded`, and `analyzing` as non-terminal. `extractCandidateSkill` must return `null` when the candidate name is missing and must never infer a Skill from the objective.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `cd frontend && npm test -- --run src/__tests__/recordingPresentation.spec.ts`

Expected: all presentation tests PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add frontend/src/api/types.ts frontend/src/recordingPresentation.ts frontend/src/__tests__/recordingPresentation.spec.ts
git commit -m "feat: define recording presentation contract"
```

### Task 2: Learning result and recording history components

**Files:**
- Create: `frontend/src/components/LatestLearningResult.vue`
- Create: `frontend/src/components/RecordingHistory.vue`
- Create: `frontend/src/components/__tests__/LatestLearningResult.spec.ts`
- Create: `frontend/src/components/__tests__/RecordingHistory.spec.ts`

**Interfaces:**
- Consumes: `ExtensionRecordingDetail | undefined` for the result card and `RecordingSummary[]` plus `selectedId` for history.
- Produces: `RecordingHistory` emits `select(recordingId: string)`; both components contain no network calls.

- [ ] **Step 1: Write failing component tests**

```ts
const wrapper = shallowMount(LatestLearningResult, { props: { recording } })
expect(wrapper.text()).toContain('API Skill 已生成')
expect(wrapper.text()).toContain('查询采购申请列表')
expect(wrapper.text()).toContain('等待业务系统配置执行连接')

const history = shallowMount(RecordingHistory, { props: { recordings, selectedId } })
await history.get('[data-recording-id="second"]').trigger('click')
expect(history.emitted('select')).toEqual([['second']])
```

Also cover empty state, failure reasons, selected-row semantics, and source-system visibility.

- [ ] **Step 2: Run focused component tests and verify RED**

Run: `cd frontend && npm test -- --run src/components/__tests__/LatestLearningResult.spec.ts src/components/__tests__/RecordingHistory.spec.ts`

Expected: FAIL because both components are missing.

- [ ] **Step 3: Implement stateless components**

`LatestLearningResult` uses `recordingStatusPresentation` and `extractCandidateSkill`; it renders protocol truth without action buttons. `RecordingHistory` uses native buttons for keyboard access and exposes exact `source_system` values instead of hard-coded MES names.

- [ ] **Step 4: Run focused component tests and verify GREEN**

Run: `cd frontend && npm test -- --run src/components/__tests__/LatestLearningResult.spec.ts src/components/__tests__/RecordingHistory.spec.ts`

Expected: both component suites PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add frontend/src/components/LatestLearningResult.vue frontend/src/components/RecordingHistory.vue frontend/src/components/__tests__
git commit -m "feat: add Skill learning result console"
```

### Task 3: Single-page console orchestration

**Files:**
- Create: `frontend/src/pages/TestConsolePage.vue`
- Create: `frontend/src/pages/__tests__/TestConsolePage.spec.ts`
- Modify: `frontend/src/api/commandCenter.ts`
- Modify: `frontend/src/components/NaturalLanguageTaskPanel.vue`

**Interfaces:**
- Consumes: `listRecordings(limit)` and `getRecording(recordingId)` from the existing command-center API.
- Produces: a page that loads the newest 8 extension recordings, selects the newest by default, fetches its detail, polls only non-terminal status every 3000 ms, and preserves the last visible result on refresh errors.

- [ ] **Step 1: Write failing page orchestration tests**

Mock `listRecordings` and `getRecording`, then assert:

```ts
expect(listRecordings).toHaveBeenCalledWith(8)
expect(getRecording).toHaveBeenCalledWith('latest')
expect(wrapper.text()).toContain('浏览器演示')
expect(wrapper.text()).toContain('API Skill')
expect(wrapper.text()).toContain('中控执行')
```

With fake timers, verify `analyzing` triggers another fetch after 3000 ms and `api_candidate` does not. Verify selecting a history row fetches that recording and that a rejected refresh displays “无法连接中控” without clearing the previous detail.

- [ ] **Step 2: Run the page test and verify RED**

Run: `cd frontend && npm test -- --run src/pages/__tests__/TestConsolePage.spec.ts`

Expected: FAIL because `TestConsolePage` is missing.

- [ ] **Step 3: Implement the page and preserve existing task-run behavior**

Use `onMounted`, `onBeforeUnmount`, and one bounded `setTimeout` loop. Do not use overlapping `setInterval` requests. The page header derives its online/offline indicator from recording API success. Update `NaturalLanguageTaskPanel` copy to “输入任务” and “交给中控执行”, but retain `createTaskRun` and `selectTaskObject` unchanged.

- [ ] **Step 4: Run page and natural-language component tests**

Run: `cd frontend && npm test -- --run src/pages/__tests__/TestConsolePage.spec.ts src/components/__tests__/NaturalLanguageTaskPanel.spec.ts`

Expected: orchestration and task execution tests PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add frontend/src/pages/TestConsolePage.vue frontend/src/pages/__tests__/TestConsolePage.spec.ts frontend/src/api/commandCenter.ts frontend/src/components/NaturalLanguageTaskPanel.vue frontend/src/components/__tests__/NaturalLanguageTaskPanel.spec.ts
git commit -m "feat: add minimal CommandCenter test console"
```

### Task 4: Replace the legacy application shell

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles/global.css`
- Create: `frontend/src/__tests__/App.spec.ts`
- Delete: `frontend/src/pages/AiConfigGeneratorPage.vue`
- Delete: `frontend/src/pages/DemonstrationWorkbenchPage.vue`
- Delete: `frontend/src/pages/ExternalSystemsPage.vue`
- Delete: `frontend/src/pages/TaskCenterPage.vue`
- Delete: `frontend/src/pages/__tests__/DemonstrationWorkbenchPage.spec.ts`
- Delete: `frontend/src/pages/__tests__/TaskCenterPage.spec.ts`
- Delete: `frontend/src/components/DynamicForm.vue`
- Delete: `frontend/src/components/JsonPreview.vue`
- Delete: `frontend/src/components/KeyValueList.vue`
- Delete unused component tests that only protect the removed form UI.

**Interfaces:**
- Consumes: `TestConsolePage` from Task 3.
- Produces: the only mounted frontend application shell and the final global token system.

- [ ] **Step 1: Write the failing application-shell test**

```ts
const wrapper = shallowMount(App)
expect(wrapper.findComponent(TestConsolePage).exists()).toBe(true)
expect(wrapper.text()).not.toContain('AI 生成配置')
expect(wrapper.text()).not.toContain('外部业务系统')
expect(wrapper.text()).not.toContain('任务中心')
expect(wrapper.find('aside').exists()).toBe(false)
```

- [ ] **Step 2: Run the shell test and verify RED**

Run: `cd frontend && npm test -- --run src/__tests__/App.spec.ts`

Expected: FAIL because `App.vue` still mounts legacy navigation.

- [ ] **Step 3: Replace the shell and global visual system**

Mount only `TestConsolePage`. Define the six design tokens from the spec, a centered maximum-width console, visible `:focus-visible` outlines, responsive two-column collapse, and a reduced-motion rule. Remove legacy files only after `rg` confirms no imports remain.

- [ ] **Step 4: Run full frontend verification**

Run: `cd frontend && npm test -- --run`

Expected: all remaining tests PASS.

Run: `cd frontend && npm run build`

Expected: `vue-tsc -b` and Vite production build PASS without missing imports.

- [ ] **Step 5: Commit Task 4**

```powershell
git add -A frontend
git commit -m "refactor: replace legacy frontend with test console"
```

### Task 5: Live data and visual acceptance

**Files:**
- Modify only if verification exposes a defect in the files created above.
- Document: `docs/testing/2026-08-09-minimal-test-console-acceptance.md`

**Interfaces:**
- Consumes: running backend at `http://127.0.0.1:8000`, Vite frontend at `http://127.0.0.1:5173`, and saved real MES recording `f72598a0-6766-4bd2-9bbb-4c15d39519fb`.
- Produces: verified responsive UI and a concise acceptance record.

- [ ] **Step 1: Start or verify both local services**

Verify `/docs` on port 8000 and `/` on port 5173 return HTTP 200. Start only missing services using the project commands.

- [ ] **Step 2: Inspect the rendered page**

Open the frontend, confirm the latest real MES recording shows `api_candidate`, the generated Skill name, `yifeng_mes`, and no legacy navigation. Inspect desktop and narrow viewport screenshots.

- [ ] **Step 3: Exercise error and loading states with automated tests**

Re-run `npm test -- --run` after any visual correction. Do not simulate success by changing backend data.

- [ ] **Step 4: Write the acceptance note**

Record test counts, build result, live recording ID/status, service URLs, and the explicit limitation that MES execution still awaits a safe execution connection.

- [ ] **Step 5: Final verification and commit**

Run:

```powershell
git diff --check
git status --short
```

Commit only verified acceptance changes:

```powershell
git add frontend docs/testing/2026-08-09-minimal-test-console-acceptance.md
git commit -m "docs: verify minimal test console"
```
