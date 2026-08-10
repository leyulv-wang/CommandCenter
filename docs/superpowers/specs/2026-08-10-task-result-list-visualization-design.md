# Task Result List Visualization Design

## Goal

Make successful query results readable during MVP testing without turning the test console into a full reporting product.

## Scope

- Increase the task execution panel to approximately 70% of the two-column work area.
- Reduce the latest Skill learning panel to approximately 30%.
- Detect a list of record objects inside the task output and render it as a normal HTML table.
- Derive columns from returned primitive record fields instead of hard-coding MES field names.
- Keep the original JSON available in a collapsed diagnostic section.
- Preserve the existing mobile single-column layout.

Out of scope: field translation, business-specific status labels, sorting, filtering, pagination controls, export, charts, and editable cells.

## Components

Create a focused `TaskResultTable` component. It accepts the existing `outputs` object and has one responsibility: find the first record-array result and present it as a table. `NaturalLanguageTaskPanel` continues to own task submission and status messaging.

The renderer will recursively inspect bounded output objects for the first non-empty array whose items are plain objects. It will use the union of primitive-valued keys as columns, preserve source key names, render null values as `—`, and stringify nested values compactly. This is a deterministic presentation rule, not business interpretation, so it does not replace agent judgment.

## Data Flow

1. The execution graph returns `final_response.outputs`.
2. `NaturalLanguageTaskPanel` passes `outputs` to `TaskResultTable`.
3. `TaskResultTable` derives records and columns without modifying the response.
4. When no record array exists, the component shows a compact object view instead of an empty table.
5. A collapsed details element retains the complete formatted JSON for troubleshooting.

## Layout

Desktop uses a `minmax(0, 7fr) minmax(280px, 3fr)` grid. The table occupies the available execution-panel width and uses contained horizontal scrolling when columns do not fit. At the existing mobile breakpoint, both panels stack vertically.

## Failure and Empty States

- Empty record array: show “查询成功，暂无记录”.
- Unsupported or scalar output: show a compact key-value fallback.
- Missing outputs: keep the current summary-only completed state.
- Rendering failures must not affect task execution state or trigger another API call.

## Testing

- Component test for nested `result.records` extraction and dynamic columns.
- Component test for null and nested values.
- Component test for empty and non-list fallbacks.
- Task panel test proving JSON is no longer the primary result view and remains available in collapsed details.
- Page test for the 70/30 grid classes.
- Full frontend test suite and production build.
