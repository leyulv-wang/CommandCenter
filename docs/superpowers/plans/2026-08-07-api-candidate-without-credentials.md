# API Candidate Without Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a successfully learned API Skill on the API path when live verification is blocked only by missing execution credentials.

**Architecture:** Classify the exact all-`MissingCredential` test outcome in the learning graph, restore the persisted Skill to `candidate`, and expose a distinct recording status. The frontend presents this as learned but not executable.

**Tech Stack:** LangGraph, Pydantic, Vue 3, pytest, Vitest

## Global Constraints

- Never treat mixed failures or non-credential failures as success.
- Never publish or expose an `api_candidate` as employee-executable.
- Never capture browser credentials or add MES-specific rules.
- Work directly on `main` without subagents.

### Task 1: Backend API candidate state

- Modify `app/command_center/learning_graph.py`, `app/command_center/repository.py`, and `tests/test_learning_graph.py`.
- Write a failing test whose three structured test results contain only `MissingCredential`; expect `api_candidate` and persisted Skill status `candidate`.
- Add a mixed-failure test that must remain `rejected`.
- Implement deterministic classification and a graph node that saves the candidate without publication.
- Run selected tests and commit.

### Task 2: Preserve API path and display status

- Modify `app/command_center/service.py`, `tests/test_command_center_service.py`, `frontend/src/api/types.ts`, `frontend/src/pages/DemonstrationWorkbenchPage.vue`, and its test.
- Assert `api_candidate` does not invoke browser distillation and is returned with completed analysis stage.
- Display “API Skill 已生成” and the pending-system-connection explanation.
- Run backend/frontend selected tests and commit.

### Task 3: Regression and saved recording

- Run backend, extension, frontend, and local E2E regressions.
- Restart the backend and reanalyze recording `68f5c5bc-607e-47a5-9c91-3cae8df4f19f`.
- Require `status=api_candidate`, retained API candidate Skill, and no browser fallback.
- Update the testing record and commit.
