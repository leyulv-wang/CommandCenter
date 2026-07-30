# Codex Project Instructions

## Python Environment

Use the local conda environment named `langgraph` for this project.

Run Python commands through conda unless the user explicitly asks otherwise:

```powershell
conda run -n langgraph python --version
conda run -n langgraph python -m pip install -r requirements.txt
conda run -n langgraph python -m pytest
conda run -n langgraph uvicorn app.main:app --reload
```

The environment path on this machine is:

```text
D:\anaconda3\envs\langgraph
```

## AI Configuration Environment

The AI form-configuration generator module reads model settings from:

```text
.env.ai
```

Expected variables:

```text
AI_CONFIG_MODEL_BASE_URL
AI_CONFIG_MODEL_NAME
AI_CONFIG_API_KEY
AI_CONFIG_TIMEOUT_SECONDS
```

Do not hard-code API keys in source code or specs.

## Project Direction

The MVP is a configurable form execution agent, not a natural-language chat agent.

Core idea:

1. Admin configures form templates and field mappings.
2. User selects a form and fills a generated form page.
3. The LangGraph workflow validates fields, builds `formValues`, calls the target API, and returns the result.
4. New forms should be added by configuration first, not by writing new form-specific code.

## Agent-First Decision Policy

This project treats multi-agent reasoning, collaboration, and judgment as the core product capability.

Prefer agents with sufficient business context and tools for:

1. Semantic and intent understanding.
2. Skill and tool selection.
3. Strategy selection and task decomposition.
4. Parameter extraction and data mapping.
5. Conflict resolution and exception interpretation.
6. Context-sensitive trade-offs and unknown scenarios.

Do not replace these judgments with keyword matching, arbitrary thresholds, sample-specific branches, hard-coded business answers, or special cases merely to implement a feature quickly or satisfy an existing test.

Deterministic code should primarily enforce:

1. Security boundaries.
2. Authentication, authorization, tenant, and permission isolation.
3. API and Tool allowlists.
4. Schema and protocol validation.
5. Idempotency and bounded side effects.
6. Timeouts, retries, concurrency, and resource limits.
7. Published Skill version constraints.
8. Stable business invariants.
9. Logging, evidence, auditability, and observability.

Agents propose judgments and execution intent. Code validates that the intent remains within allowed boundaries. Deterministic validation must not silently become a substitute for business reasoning.

If a judgment currently performed by an agent must be moved into deterministic code, document:

1. Which stable boundary or invariant the rule enforces.
2. Why contextual agent judgment is no longer appropriate.
3. How the rule affects unknown scenarios and agent generalization.
4. How the rule can be configured, revised, or removed when the business changes.

## Test Failure Analysis

When a test fails, first classify the failure:

1. Implementation defect.
2. Missing agent context, evidence, or tools.
3. Prompt, role boundary, or agent collaboration defect.
4. Model output violating an established protocol.
5. Test environment or fixture defect.
6. Test assumptions that do not reflect real business requirements.

Do not add unsupported business rules solely to make an existing test pass. Tests must protect real behavior and stable boundaries rather than retroactively define business truth.

When the fix changes an agent judgment into a code rule, explain why the rule is a deterministic invariant and assess whether it limits the ability to handle unseen scenarios.

## Reuse-First Policy

When a mature tool, official SDK, framework, API, or open-source project satisfies a requirement, prefer adopting or adapting it over reimplementing the same infrastructure.

Evaluate before adoption:

1. Enterprise and commercial license compatibility.
2. Local or private deployment support.
3. External data transfer and credential handling.
4. Permission and security boundaries.
5. API and data-model stability.
6. Replaceability and isolation behind an adapter.
7. Compatibility with the current Python, FastAPI, LangGraph, and frontend stack.
8. Adoption cost compared with long-term custom maintenance.

Prefer this integration order:

1. Official SDK.
2. Stable public API or MCP Server.
3. Independently deployed service adapter.
4. Small, clearly reusable modules.
5. Custom reimplementation only when the earlier options are unsuitable.

Expose third-party capabilities through CommandCenter Tool or Operator interfaces. Do not copy entire third-party repositories into the main project or allow a vendor-specific schema to become the only internal Skill representation.

## Architecture Defaults

Use:

1. FastAPI for the backend API.
2. LangGraph for the form execution workflow.
3. Pydantic for schemas and validation.
4. SQLAlchemy or JSON files for form template storage in the MVP.
5. Mock external APIs until real purchase, after-sales, and HR APIs are available.

## Frontend

The formal frontend lives in:

```text
frontend/
```

Use Vue 3, TypeScript, Vite, and Element Plus. The old FastAPI-served demo page has been removed; future demos and product UI should be built in the formal Vue frontend.

Useful commands:

```powershell
cd frontend
npm install
npm run dev
npm run build
```
