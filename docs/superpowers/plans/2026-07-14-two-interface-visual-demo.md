# Two Interface Visual Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide two independently resettable external business-system pages and demonstrate real AI onboarding for workflow and custom URL interfaces.

**Architecture:** Each external FastAPI service owns an independent SQLite database and serves a shared lightweight business UI. The purchase service exposes a workflow start endpoint; the office-supply service exposes a custom URL endpoint. The central registry starts with both systems onboarding and promotes either system when an AI-generated form targeting its URL is saved.

**Tech Stack:** FastAPI, SQLite, static HTML/CSS/JavaScript, Vue 3, TypeScript, LangGraph, OpenAI-compatible LLM.

## Global Constraints

- Use conda environment `langgraph` for Python commands.
- Both demo systems start as onboarding with no startable forms.
- Keep internal task-result forms available but hidden from startable forms.
- Reset systems independently; do not add reset-all.
- AI example buttons only populate interface text; generation must still call the configured LLM.

---

### Task 1: Independent SQLite records and real workflow endpoint

**Files:**
- Modify: `external_systems/common.py`
- Modify: `external_systems/connected_system/main.py`
- Modify: `external_systems/onboarding_system/main.py`
- Test: `tests/test_external_systems.py`

- [x] Write failing tests for business-created tasks, workflow submission storage, and interface metadata.
- [x] Add task creation API and workflow start API.
- [x] Extend submissions with `endpoint_type` and `fd_template_id`, including migration for existing SQLite files.
- [x] Return interface-specific descriptions and rerun tests until green.

### Task 2: Two standalone business-system pages

**Files:**
- Create: `external_systems/ui/index.html`
- Create: `external_systems/ui/app.css`
- Create: `external_systems/ui/app.js`
- Modify: `external_systems/common.py`
- Test: `tests/test_external_systems.py`

- [x] Write failing tests for root page and system profile.
- [x] Serve the shared UI and system profile from both external services.
- [x] Implement task creation, pending/completed lists, submission records, interface description, connection status, refresh, and independent reset controls.
- [x] Verify both pages render with different system identity and interface type.

### Task 3: Independent central reset and onboarding baseline

**Files:**
- Modify: `app/data/external_systems.json`
- Modify: `app/external_systems.py`
- Modify: `app/main.py`
- Modify: `frontend/src/api/externalSystems.ts`
- Modify: `frontend/src/pages/ExternalSystemsPage.vue`
- Delete: `app/data/form_templates/purchase_request.json`
- Delete: `app/data/form_templates/office_supplies_apply.json`
- Test: `tests/test_external_data_api.py`
- Test: `tests/test_api.py`
- Test: `tests/test_form_execution.py`

- [x] Write failing tests proving both systems start onboarding and reset independently.
- [x] Add `POST /demo/reset/{system_code}` with per-system protected task forms.
- [x] Set both registry entries to onboarding with empty `form_codes`.
- [x] Remove pre-connected application templates and adapt tests to use inline fixtures.
- [x] Update the central external-systems page to reset the selected demo system.

### Task 4: AI two-interface examples and workflow HTTP default

**Files:**
- Modify: `app/ai_config/generator.py`
- Modify: `frontend/src/pages/AiConfigGeneratorPage.vue`
- Test: `tests/test_ai_form_config.py`

- [x] Write a failing test proving AI-generated workflow configurations default to real HTTP submission.
- [x] Normalize both workflow and custom URL AI drafts to `submit_mode=http`.
- [x] Add workflow purchase and custom URL office-supply example buttons.
- [x] Keep generation behind the existing LLM endpoint and show the chosen example name.

### Task 5: Task-center empty state

**Files:**
- Modify: `frontend/src/pages/TaskCenterPage.vue`

- [x] Keep the task-center page visible when no system is connected.
- [x] Hide task tabs and show the approved empty-state copy until at least one system is connected.
- [x] Preserve existing behavior after one or both systems connect.

### Task 6: Full visual and API verification

- [x] Run the complete Python test suite.
- [x] Run the Vue production build.
- [x] Start ports `8000`, `8101`, `8102`, and `5174`.
- [x] Verify purchase workflow onboarding, task creation, task completion, and workflow submission storage.
- [x] Reset purchase independently and verify office state is unchanged.
- [x] Verify office custom URL onboarding and submission storage.
- [x] Reset office independently and restore both systems to onboarding.
- [x] Mark the Spec implemented.
