# Configurable Form Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal runnable configurable form execution agent that loads form templates, validates submissions, builds `formValues`, and submits to mock external endpoints.

**Architecture:** FastAPI exposes form/template and submission endpoints. LangGraph coordinates a small workflow: load config, validate data, build `formValues`, build the endpoint-specific payload, submit via mock adapter, and return the result. Form templates are JSON files for the MVP.

**Tech Stack:** Python 3.12 in conda env `langgraph`, FastAPI, LangGraph, Pydantic, pytest, HTTPX-ready adapter boundary.

---

### Task 1: Core Form Models And Payload Builders

**Files:**
- Create: `app/forms/schemas.py`
- Create: `app/forms/service.py`
- Test: `tests/test_form_execution.py`

- [ ] Write failing tests for workflow and custom URL payload generation.
- [ ] Implement Pydantic form template and field schemas.
- [ ] Implement validation and `formValues` mapping.
- [ ] Implement payload generation for `workflow` and `custom_url` endpoint types.
- [ ] Run `conda run -n langgraph python -m pytest -q`.

### Task 2: Template Repository And Sample Configs

**Files:**
- Create: `app/forms/repository.py`
- Create: `app/data/form_templates/purchase_request.json`
- Create: `app/data/form_templates/after_sales.json`
- Create: `app/data/form_templates/hr_request.json`
- Test: `tests/test_form_execution.py`

- [ ] Write failing tests for loading sample templates.
- [ ] Implement JSON template repository.
- [ ] Add three sample form templates.
- [ ] Run `conda run -n langgraph python -m pytest -q`.

### Task 3: LangGraph Workflow And API

**Files:**
- Create: `app/agent/state.py`
- Create: `app/agent/nodes.py`
- Create: `app/agent/graph.py`
- Create: `app/adapters/mock_flow.py`
- Create: `app/main.py`
- Create: `langgraph.json`
- Test: `tests/test_api.py`

- [ ] Write failing API tests for listing templates and submitting a form.
- [ ] Implement mock external submitter.
- [ ] Implement LangGraph workflow nodes.
- [ ] Implement FastAPI routes.
- [ ] Add `langgraph.json` graph entry.
- [ ] Run `conda run -n langgraph python -m pytest -q`.
