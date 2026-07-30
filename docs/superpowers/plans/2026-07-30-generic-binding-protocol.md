# Generic Binding Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose one generic binding-expression grammar to every relevant agent and enforce the same grammar at runtime.

**Architecture:** A reusable constrained Pydantic string type becomes the machine-readable source of truth for binding expressions in both demonstration analysis and compiled Skills. `AgentSuite` adds one shared, business-neutral protocol explanation to the analysis and compilation prompts. Invalid expressions continue through the existing one-retry structured-output path and are never auto-rewritten.

**Tech Stack:** Python 3.11, Pydantic 2, LangGraph, pytest

## Global Constraints

- Valid sources are exactly `task.<路径>`, `steps.<步骤标识>.output.<路径>`, and `literal.<输入名>`.
- The grammar must not contain procurement-, MES-, ERP-, HR-, field-, or value-specific branches.
- Code validates protocol syntax only; agents retain responsibility for business meaning and source selection.
- Never normalize `literal(value)` or evaluate generated expressions.
- Run Python commands through conda environment `langgraph`.

---

### Task 1: Make the binding grammar visible in JSON Schema

**Files:**
- Modify: `tests/test_command_center_schemas.py`
- Modify: `app/command_center/schemas.py`

**Interfaces:**
- Produces: `BindingExpression`, an `Annotated[str, StringConstraints]` accepted by both `InputBinding.expression` and `SkillStep.input_bindings` values.
- Runtime grammar: `^(task|steps|literal)\..+$`.

- [ ] **Step 1: Write failing schema-contract tests**

Add tests that inspect the runtime schemas sent to models:

```python
def test_demonstration_analysis_exposes_binding_pattern_to_agents():
    schema = DemonstrationAnalysis.model_json_schema()
    expression = schema["$defs"]["InputBinding"]["properties"]["expression"]
    assert expression["pattern"] == r"^(task|steps|literal)\..+$"


def test_skill_definition_exposes_same_binding_pattern_to_agents():
    schema = SkillDefinition.model_json_schema()
    values = schema["$defs"]["SkillStep"]["properties"]["input_bindings"]
    assert values["additionalProperties"]["pattern"] == (
        r"^(task|steps|literal)\..+$"
    )
```

Add a parametrized validation test proving these generic paths pass:

```python
@pytest.mark.parametrize(
    "expression",
    [
        "task.content.quantity",
        "steps.create.output.data.id",
        "literal.item_name",
    ],
)
def test_binding_protocol_accepts_all_generic_sources(expression):
    InputBinding(
        tool_field="body.value",
        expression=expression,
    )
```

Add rejected examples:

```python
@pytest.mark.parametrize(
    "expression",
    ["literal('value')", "raw-value", "python:run()"],
)
def test_binding_protocol_rejects_non_path_expressions(expression):
    with pytest.raises(ValidationError):
        InputBinding(tool_field="body.value", expression=expression)
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_command_center_schemas.py -q
```

Expected: pattern assertions fail because the custom validators are not represented in JSON Schema.

- [ ] **Step 3: Implement the reusable constrained type**

In `app/command_center/schemas.py`:

```python
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

BindingExpression = Annotated[
    str,
    StringConstraints(pattern=r"^(task|steps|literal)\..+$"),
]
```

Use `BindingExpression` for:

```python
class InputBinding(BaseModel):
    tool_field: str
    expression: BindingExpression


class SkillStep(BaseModel):
    input_bindings: dict[str, BindingExpression]
```

Keep the existing target-key check for `body.*` and `path.*`, but remove the
duplicated expression-prefix checks now enforced by the shared type.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_command_center_schemas.py -q
```

Expected: all schema tests pass and both model schemas expose the same pattern.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/schemas.py tests/test_command_center_schemas.py
git commit -m "fix: expose generic binding grammar"
```

### Task 2: Give analysis and compilation agents one shared protocol

**Files:**
- Modify: `tests/test_structured_agents.py`
- Modify: `app/command_center/agents.py`

**Interfaces:**
- Produces: `BINDING_PROTOCOL_PROMPT`, shared by `analyze_demonstration()` and `compile_skill()`.
- Consumes: the same `task.*`, `steps.*`, and `literal.*` grammar enforced by Task 1.

- [ ] **Step 1: Write a failing prompt-contract test**

Create a capturing model whose `generate()` returns valid objects while recording
the supplied prompts. Invoke both relevant agent methods, then assert each prompt
contains all three generic examples and explicitly rejects function syntax:

```python
for prompt in capturing_model.prompts:
    assert "task.content.quantity" in prompt
    assert "steps.create.output.data.id" in prompt
    assert "literal.item_name" in prompt
    assert "不能写成 literal(...)" in prompt
```

The capturing double returns a compilable `DemonstrationAnalysis` and
`valid_skill_payload()` through the real Pydantic models; assertions target the
prompt consumed by the model boundary, not the constant's source text.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_structured_agents.py -q
```

Expected: the analysis prompt lacks the protocol examples and prohibition.

- [ ] **Step 3: Implement one shared business-neutral prompt**

Define in `app/command_center/agents.py`:

```python
BINDING_PROTOCOL_PROMPT = (
    "绑定表达式只能引用数据路径：业务上下文使用 task.content.quantity，"
    "前序步骤输出使用 steps.create.output.data.id，运行时输入使用 "
    "literal.item_name。不能写成 literal(...)、函数调用、代码或直接业务值。"
)
```

Append this string to both the demonstration-analysis and Skill-compilation
system prompts. Do not add any demonstrated values or system-specific field
branches.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
conda run --no-capture-output -n langgraph python -m pytest tests/test_structured_agents.py -q
```

Expected: all structured-agent tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/command_center/agents.py tests/test_structured_agents.py
git commit -m "fix: share binding protocol across agents"
```

### Task 3: Full verification and live reload

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-generic-binding-protocol-design.md`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: tested code, an implemented specification status, and a restarted backend.

- [ ] **Step 1: Run the full backend suite**

```powershell
conda run --no-capture-output -n langgraph python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run frontend regression checks**

```powershell
Set-Location frontend
npm test
npm run build
```

Expected: zero test failures and a successful production build.

- [ ] **Step 3: Mark the design implemented and commit**

Change the design status from `待实施` to `已实施`, then:

```powershell
git add docs/superpowers/specs/2026-07-30-generic-binding-protocol-design.md
git commit -m "docs: mark generic binding protocol implemented"
```

- [ ] **Step 4: Restart and health-check the backend**

Restart only the process listening on port `8000` with:

```powershell
conda run -n langgraph python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verify:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
```

Expected: HTTP 200.

- [ ] **Step 5: Inspect final repository state**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; existing user-owned evidence and research files
remain untracked and untouched.
