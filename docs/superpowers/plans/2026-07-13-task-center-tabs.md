# Task Center Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the task center into three employee workflows: start an application, process pending tasks, and review completed tasks.

**Architecture:** External systems remain the source of truth and expose task queries filtered by status. The central system aggregates tasks and explicitly maps each connected system to the forms it allows employees to start. The Vue task center uses three tabs while reusing the existing dynamic form component.

**Tech Stack:** FastAPI, SQLite, httpx, LangGraph, Pydantic, Vue 3, TypeScript, Vite, Element Plus.

## Global Constraints

- Use conda environment `langgraph` for Python commands.
- Use fixed demo operator `u001`; do not add accounts or permissions.
- Do not modify the AI fast-configuration module.
- Do not infer form ownership from URL strings; configure connected-system form codes explicitly.
- Keep external systems as the source of truth for pending and completed tasks.

---

### Task 1: Completed task query in the external system

**Files:**
- Modify: `external_systems/common.py`
- Test: `tests/test_external_systems.py`

**Interfaces:**
- Extends: `GET /api/tasks?operator_id=u001&status=pending|completed`
- Completed item fields: `result_values`, `completed_at`

- [ ] Write a failing test that completes a task and queries it with `status=completed`.
- [ ] Run the external-system test file and confirm the completed query fails.
- [ ] Add validated status filtering and completed-result fields to the task query.
- [ ] Rerun the external-system tests until green.

### Task 2: Central completed aggregation and startable forms

**Files:**
- Modify: `app/external_systems.py`
- Modify: `app/main.py`
- Test: `tests/test_external_data_api.py`

**Interfaces:**
- Extends: `GET /tasks?operator_id=u001&status=pending|completed`
- Adds: `GET /external-systems/{system_code}/forms`
- Adds registry field: `form_codes: list[str]`

- [ ] Write failing tests proving task status is forwarded and completed results are normalized.
- [ ] Write a failing test proving connected purchase system returns only its configured startable forms.
- [ ] Add explicit form-code mappings to the external-system registry.
- [ ] Implement filtered aggregation and the system-forms endpoint with 404 handling.
- [ ] Rerun central API tests until green.

### Task 3: Three-tab Vue task center

**Files:**
- Modify: `frontend/src/pages/TaskCenterPage.vue`
- Modify: `frontend/src/api/tasks.ts`
- Modify: `frontend/src/api/externalSystems.ts`
- Modify: `frontend/src/api/forms.ts`
- Modify: `frontend/src/api/types.ts`

**Interfaces:**
- Consumes: `GET /external-systems`
- Consumes: `GET /external-systems/{system_code}/forms`
- Consumes: existing `POST /forms/{form_code}/submit`
- Consumes: `GET /tasks?status=pending|completed`

- [ ] Add frontend API methods and types for filtered tasks and system forms.
- [ ] Add “发起申请” tab with system selection, form selection, dynamic form, and submit result handling.
- [ ] Keep the existing task flow under “待办任务”.
- [ ] Add read-only “已完成任务” with source, original content, result, and completion time.
- [ ] Run `npm run build` and resolve all type/build errors.

### Task 4: Full verification

**Files:**
- Modify only if verification exposes a defect in files above.

- [ ] Run `conda run -n langgraph python -m pytest -q` and require zero failures.
- [ ] Run `npm run build` in `frontend` and require exit code 0.
- [ ] Restart services and verify start-application submission still reaches the purchase system.
- [ ] Complete one pending task and verify it moves from pending to completed with its result visible.
- [ ] Reset the connected demo system and verify repeatable demo data is restored.
