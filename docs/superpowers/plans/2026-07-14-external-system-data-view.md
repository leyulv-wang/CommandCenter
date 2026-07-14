# External System Data View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the central application retrieve and tabulate all tasks and submissions from a selected connected external system through HTTP APIs.

**Architecture:** External systems extend their existing task endpoint so `operator_id` is optional. The central backend adds one system-scoped aggregate endpoint that validates connection state, calls both external APIs, and returns one normalized response. The Vue page consumes only that central endpoint and renders separate task and submission tables.

**Tech Stack:** FastAPI, httpx, SQLite, Pydantic, Vue 3, TypeScript, Element Plus.

## Global Constraints

- Use conda environment `langgraph` for Python commands.
- Do not add account or permission handling.
- Do not make the browser call external-system ports directly.
- Preserve the task center's existing operator-scoped behavior.
- Do not add pagination or export in this version.

---

### Task 1: External all-task query

**Files:**
- Modify: `external_systems/common.py`
- Test: `tests/test_external_systems.py`

**Interfaces:**
- Produces: `GET /api/tasks?status=pending|completed` with optional `operator_id`.

- [x] Add a test proving omission of `operator_id` returns tasks for different assignees.
- [x] Run the focused test and confirm it fails because `operator_id` is required.
- [x] Make `operator_id` optional and conditionally build the SQLite query.
- [x] Run the external-system tests and confirm existing filtered behavior still passes.

### Task 2: Central aggregate data API

**Files:**
- Modify: `app/external_systems.py`
- Modify: `app/main.py`
- Test: `tests/test_external_data_api.py`

**Interfaces:**
- Produces: `ExternalSystemClient.get_system_data(system_code: str) -> dict[str, object]`.
- Produces: `GET /external-systems/{system_code}/data` returning `system`, `tasks`, and `submissions`.

- [x] Add failing tests for two unfiltered task calls, one submission call, response normalization, and rejection of onboarding systems.
- [x] Run the focused tests and confirm the aggregate method/route is missing.
- [x] Implement connected-system validation and the three HTTP reads.
- [x] Map external HTTP failures to status `502` and unknown/unconnected systems to `404`.
- [x] Run all central external-data API tests.

### Task 3: Vue tabular data page

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/externalSystems.ts`
- Modify: `frontend/src/pages/ExternalSystemsPage.vue`

**Interfaces:**
- Consumes: `GET /external-systems/{system_code}/data`.
- Produces: typed `ExternalSystemDataResponse` and two Element Plus data tables.

- [x] Add response and row types for tasks and submissions.
- [x] Replace the submissions-only request with the aggregate request.
- [x] Render task and application tabs with status/type/source tags.
- [x] Render dynamic dictionaries as escaped key/value rows instead of JSON text.
- [x] Keep interface-spec behavior for onboarding systems and clear stale data when selection changes.
- [x] Run `npm run build` and resolve TypeScript or template errors.

### Task 4: Verification and documentation

- [x] Run `conda run --no-capture-output -n langgraph python -m pytest -q`.
- [x] Run `npm run build` in `frontend/`.
- [x] Restart ports `8000`, `8101`, `8102`, and `5174`.
- [x] Verify the connected-system table on desktop and mobile widths.
- [x] Change the Spec status to `已实现` and mark this plan complete.
