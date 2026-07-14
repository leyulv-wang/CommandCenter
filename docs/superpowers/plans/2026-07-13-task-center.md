# Task Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal task center that aggregates pending tasks from connected systems and submits employee processing results back to the task source.

**Architecture:** The connected purchase demo system owns task records in SQLite and exposes one pending-task query endpoint plus one completion endpoint. The central FastAPI service aggregates tasks and reuses the existing LangGraph form execution graph to validate and submit task results. The Vue frontend replaces the form-submission entry with a task-center page driven by the existing dynamic form component.

**Tech Stack:** FastAPI, SQLite, httpx, LangGraph, Pydantic, Vue 3, TypeScript, Vite, Element Plus.

## Global Constraints

- Use the conda environment named `langgraph` for Python commands.
- Use a fixed demo operator `u001`; do not add login or permissions.
- Do not modify the AI fast-configuration flow in this phase.
- The task center aggregates all connected systems without requiring system selection.
- External systems remain the source of truth for task data and status.

---

### Task 1: Purchase-system task API

**Files:**
- Modify: `external_systems/common.py`
- Modify: `external_systems/connected_system/main.py`
- Test: `tests/test_external_systems.py`

**Interfaces:**
- Produces: `GET /api/tasks?operator_id=u001`
- Produces: `POST /api/tasks/complete` accepting form fields `docOperator` and `formValues`
- Produces task fields: `task_id`, `title`, `task_type`, `form_code`, `content`, `status`, `assignee_id`, `created_at`

- [ ] Write a failing test proving the connected system returns only `u001` pending tasks.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_external_systems.py -q` and confirm the task endpoint is missing.
- [ ] Add a `tasks` SQLite table, connected-system seed tasks, and the pending-task endpoint.
- [ ] Add a failing test that submits a processing result and verifies the task becomes completed and disappears from pending results.
- [ ] Implement `/api/tasks/complete`, persist `result_values` and `completed_at`, and rerun the test file until green.

### Task 2: Central task aggregation and completion

**Files:**
- Modify: `app/external_systems.py`
- Modify: `app/main.py`
- Create: `app/data/form_templates/purchase_task_result.json`
- Test: `tests/test_external_data_api.py`

**Interfaces:**
- Produces: `GET /tasks?operator_id=u001`, returning normalized tasks with `source_system_code` and `source_system_name`
- Produces: `POST /tasks/{system_code}/{task_id}/complete` with `operator_id` and `values`
- Consumes: task `form_code` to select the result form template
- Consumes: existing `form_execution_graph` after adding `task_id` to submitted values

- [ ] Write failing tests for aggregation across connected systems while skipping onboarding systems.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_external_data_api.py -q` and confirm failure because task APIs are missing.
- [ ] Add task query support to `ExternalSystemClient` and expose central `GET /tasks`.
- [ ] Write a failing completion test that verifies `task_id` is sent through the configured task-result form.
- [ ] Add the result form template and central completion endpoint that invokes the existing LangGraph graph.
- [ ] Rerun central API tests until green, including 404 and external-system failure paths.

### Task 3: Vue task center

**Files:**
- Create: `frontend/src/pages/TaskCenterPage.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/tasks.ts`
- Modify: `frontend/src/components/DynamicForm.vue`

**Interfaces:**
- Consumes: `GET /tasks?operator_id=u001`
- Consumes: `GET /forms/{form_code}`
- Consumes: `POST /tasks/{system_code}/{task_id}/complete`
- Reuses: `DynamicForm` with configurable submit-button text

- [ ] Add task and completion request TypeScript types plus the task API client.
- [ ] Build the task-center page with aggregated pending list, source-system label, task details, generated processing form, loading, empty, success, and error states.
- [ ] Rename the navigation entry from “表单提交” to “任务中心” and route the default view to the new page.
- [ ] Allow `DynamicForm` to accept optional button text so task processing displays “提交处理结果”.
- [ ] Run `npm run build` in `frontend` and resolve all type/build errors.

### Task 4: Regression and acceptance verification

**Files:**
- Modify only if verification exposes a defect in files above.

**Interfaces:**
- Verifies the full path: external pending task -> central aggregation -> dynamic result form -> LangGraph submission -> external completion.

- [ ] Run `conda run -n langgraph python -m pytest -q` and require zero failures.
- [ ] Run `npm run build` in `frontend` and require exit code 0.
- [ ] Start ports `8101`, `8102`, `8000`, and `5174`, then verify health endpoints and the task-center API.
- [ ] Submit one demo task result and verify it disappears from `GET /tasks?operator_id=u001`.
- [ ] Restore repeatable demo data after the manual acceptance check.
