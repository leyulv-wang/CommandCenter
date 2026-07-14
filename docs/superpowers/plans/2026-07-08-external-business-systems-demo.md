# External Business Systems Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two small local external business systems so the central control app can read existing external records and submit new records through real HTTP APIs.

**Architecture:** Add two independent FastAPI demo services under `external_systems/`, each backed by SQLite. Keep the central control system as the orchestrator: it lists external records, submits configured forms through HTTP, and leaves AI-generated onboarding configs as the way to connect the second system.

**Tech Stack:** FastAPI, SQLite via Python standard library, httpx, Vue 3, TypeScript, Element Plus.

## Global Constraints

- Use the local conda environment named `langgraph`.
- Do not hard-code API keys.
- Keep old sample forms unless they actively block the new demo.
- Use SQLite only for the demo business systems.
- Keep this phase focused on external system demo behavior, not auth, approval flow, or natural-language form filling.

---

### Task 1: External Demo Systems

**Files:**
- Create: `external_systems/common.py`
- Create: `external_systems/connected_system/main.py`
- Create: `external_systems/onboarding_system/main.py`
- Create: `tests/test_external_systems.py`

**Interfaces:**
- Produces: `create_external_app(system_name, database_path, seed_records)` returning a FastAPI app.
- Produces: `GET /health`, `GET /api/submissions`, `POST /api/forms/submit`, `GET /api/interface-spec`.

- [ ] Create tests that submit records and verify SQLite-backed listing.
- [ ] Implement shared SQLite helpers and FastAPI routes.
- [ ] Seed connected system with historical records.
- [ ] Seed onboarding system with no default central-control config but provide interface spec text.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_external_systems.py -q`.

### Task 2: Central Control External Data API

**Files:**
- Create: `app/external_systems.py`
- Modify: `app/main.py`
- Create: `tests/test_external_data_api.py`

**Interfaces:**
- Produces: `GET /external-systems`, listing configured demo systems.
- Produces: `GET /external-systems/{system_code}/submissions`, proxying external records.

- [ ] Test configured system listing.
- [ ] Test submissions proxy with `httpx.MockTransport`.
- [ ] Implement the external system client and FastAPI routes.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_external_data_api.py -q`.

### Task 3: Central Form Config Cleanup For Demo

**Files:**
- Modify: `app/data/form_templates/purchase_request.json`
- Modify: `app/data/form_templates/tower_order.json` if needed.

**Interfaces:**
- `purchase_request` should represent the already-connected demo system.
- `onboarding_system` should not be preconfigured in central control.

- [ ] Point `purchase_request` to the local connected system HTTP endpoint.
- [ ] Keep old forms available but secondary.
- [ ] Run existing API and form execution tests.

### Task 4: Frontend External Records View

**Files:**
- Create: `frontend/src/api/externalSystems.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/App.vue`
- Create: `frontend/src/pages/ExternalSystemsPage.vue`

**Interfaces:**
- Adds a page that lists external systems and shows records returned by central control.
- Keeps the existing form submission and AI config pages.

- [ ] Add TypeScript API helpers.
- [ ] Add a simple records page with refresh behavior.
- [ ] Add navigation entry.
- [ ] Run `npm run build`.

### Task 5: Verification And Service Startup

**Files:**
- No new files expected.

**Interfaces:**
- Central backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`
- Connected system: `http://127.0.0.1:8101`
- Onboarding system: `http://127.0.0.1:8102`

- [ ] Run all backend tests.
- [ ] Run frontend build.
- [ ] Start or restart the three backend services and frontend dev server.
- [ ] Verify central control can see connected system records.
