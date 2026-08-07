# Skill Test Binding Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure generated harmless test cases satisfy every Skill binding and turn unresolved test bindings into structured test failures instead of background system crashes.

**Architecture:** Strengthen the test-design agent contract around the three binding namespaces, then add a deterministic preflight boundary to the read-only tester using the production `BindingResolver`. Re-run the saved MES trace through the same learning graph after automated regressions pass.

**Tech Stack:** Python, Pydantic, LangGraph, pytest, FastAPI

## Global Constraints

- Do not add `purchaseDepartment`, `applyBy`, MES path, or button-specific rules.
- Agents generate semantic test values; code only verifies resolvability and isolates failures.
- Never execute a Tool after binding preflight fails.
- Never expose binding exception values, credentials, or model raw output in API failure summaries.
- Use `conda run -n langgraph` for Python tests and work directly on `main` without subagents.

---

### Task 1: Complete test-design agent contract

**Files:**
- Modify: `app/command_center/agents.py`
- Modify: `tests/test_structured_agents.py`

**Interfaces:**
- Consumes: complete `SkillDefinition`, including every step `input_bindings` expression.
- Produces: `TestPlan` cases whose `fixture.source_task`, `invocation`, and prior-step assumptions satisfy `task.*`, `literal.*`, and `steps.*` bindings.

- [ ] Write a failing prompt test asserting all three namespaces and the required output locations are described.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_structured_agents.py -q` and verify the new assertion fails.
- [ ] Extend `AgentSuite.design_tests` so every case supplies all required `task.*` values in `fixture.source_task`, all `literal.*` values in `invocation`, and rejects an impossible `steps.*` dependency rather than inventing data.
- [ ] Re-run the selected test and verify it passes.
- [ ] Commit with `git commit -m "fix: require complete generated test bindings"`.

### Task 2: Read-only binding preflight and failure isolation

**Files:**
- Modify: `app/command_center/readonly_testing.py`
- Modify: `tests/test_real_mes_readonly_loop.py`

**Interfaces:**
- Consumes: candidate `SkillDefinition`, test-case fixture, and invocation.
- Produces: a normal read-only test result or `status=failed` with summary `test data does not satisfy Skill bindings`, without calling the Tool.

- [ ] Add a failing test with `query.department -> task.content.department`, an empty source task, and an executor that fails if called. Assert `run()` returns structured failure and does not raise.
- [ ] Run `conda run -n langgraph python -m pytest tests/test_real_mes_readonly_loop.py -q`; expected failure is the current `KeyError`.
- [ ] Add `_external_bindings_resolve(skill, task, literals)` that invokes `BindingResolver.resolve` for every `task.*` and `literal.*` expression before execution. `steps.*` values depend on real prior outputs and remain the runner's responsibility. Catch binding/protocol exceptions at the test boundary and return the safe failure summary; unresolved external bindings must fail before any Tool execution.
- [ ] Add a passing fixture case proving `task.content.department` reaches the real `SkillRunner` command arguments.
- [ ] Re-run the selected test file and commit with `git commit -m "fix: isolate incomplete readonly test bindings"`.

### Task 3: Regression and saved MES reanalysis

**Files:**
- Modify: `docs/testing/2026-08-07-http-mes-network-fallback.md`

**Interfaces:**
- Consumes: saved recording `68f5c5bc-607e-47a5-9c91-3cae8df4f19f`.
- Produces: a persisted non-system analysis result and exact regression evidence.

- [ ] Run backend full tests with `conda run -n langgraph python -m pytest -q`.
- [ ] Run extension tests/typecheck/build and frontend tests/build.
- [ ] Restart the local backend so the running process uses the new code.
- [ ] Invoke `CommandCenterService.analyze_extension_recording` for the saved recording through a one-shot project script using the same app configuration; do not touch MES or replay a browser action.
- [ ] Inspect the recording and require `failure_stage != system`; if tests pass, require `verified_candidate` or `published`, otherwise preserve the structured testing failure reason.
- [ ] Record exact outcomes in the testing document and commit with `git commit -m "docs: verify complete Skill test bindings"`.
