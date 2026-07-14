# Automatic Demo System Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make saving an AI-generated office-supply form automatically connect the demo system, expose it in the task center, and support a complete one-click reset for repeat demonstrations.

**Architecture:** External-system connection state is stored in a small JSON registry. Saving a form matches its endpoint URL to a registered system and promotes that system to connected. The onboarding demo system uses the existing SQLite task API pattern, while reset restores its data and registry state without deleting its internal task-result template.

**Tech Stack:** FastAPI, JSON state, SQLite, LangGraph, Vue 3, TypeScript.

## Global Constraints

- Use conda environment `langgraph` for Python commands.
- Do not change AI model prompting or model configuration.
- Connection must happen automatically after successful form save.
- Connection state must survive backend restart.
- Reset must make the same system and form identifiers reusable.

---

### Task 1: Persistent external-system connection registry

**Files:**
- Modify: `app/external_systems.py`
- Create: `app/data/external_systems.json`
- Test: `tests/test_external_data_api.py`

- [ ] Write failing tests for endpoint-based form registration, persistence after reload, and reset to onboarding.
- [ ] Add JSON-backed registry loading and saving.
- [ ] Add `connect_form_by_endpoint()` and `reset_onboarding()` methods.
- [ ] Rerun registry tests until green.

### Task 2: Office-supply task loop

**Files:**
- Modify: `external_systems/onboarding_system/main.py`
- Create: `app/data/form_templates/office_supply_task_result.json`
- Modify: `tests/test_external_systems.py`

- [ ] Write a failing test proving the onboarding system has pending tasks and can complete one.
- [ ] Add seeded office-supply tasks using the shared SQLite task API.
- [ ] Add the internal processing-form template targeting port `8102`.
- [ ] Rerun external-system tests until green.

### Task 3: Save and reset lifecycle integration

**Files:**
- Modify: `app/main.py`
- Modify: `app/forms/repository.py`
- Modify: `tests/test_external_data_api.py`

- [ ] Write a failing API test proving form save promotes the matching onboarding system and associates the form code.
- [ ] Register the saved form after repository persistence succeeds.
- [ ] Write a failing reset test proving generated forms are removed, internal task form is preserved, and role returns to onboarding.
- [ ] Extend repository deletion exclusions and implement full reset ordering.
- [ ] Rerun API tests until green.

### Task 4: End-to-end repeatability verification

- [ ] Run the full Python test suite.
- [ ] Run the Vue production build.
- [ ] Reset, save an office-supply configuration, verify the system appears in task-center APIs, complete one office task, then reset again.
- [ ] Verify the second reset returns the system to onboarding and restores its pending tasks.
- [ ] Mark the Spec implemented.
