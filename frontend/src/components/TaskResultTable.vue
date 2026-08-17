<template>
  <section class="task-result">
    <template v-if="rows !== null">
      <div v-if="rows.length" class="result-heading">
        <strong>查询结果</strong>
        <span data-testid="result-count">{{ rows.length }} 条记录</span>
      </div>
      <div v-if="rows.length" class="result-table-scroll">
        <table>
          <thead>
            <tr>
              <th v-for="column in columns" :key="column">{{ column }}</th>
              <th v-if="hasRowActions">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, rowIndex) in rows"
              :key="rowKey(row, rowIndex)"
              :data-record-id="detailRecordId(row) || undefined"
            >
              <td v-for="column in columns" :key="column">
                {{ formatValue(row[column]) }}
              </td>
              <td v-if="hasRowActions" class="action-cell">
                <button
                  v-if="detailRecordId(row)"
                  type="button"
                  data-testid="view-detail"
                  @click="emit('view-detail', detailRecordId(row)!)"
                >
                  查看详情
                </button>
                <button
                  v-if="progressRecordId(row)"
                  type="button"
                  data-testid="track-progress"
                  @click="emit('track-progress', progressRecordId(row)!)"
                >
                  追踪采购进度
                </button>
                <button
                  v-for="action in actionsForRow(row)"
                  :key="action.action_id"
                  type="button"
                  data-testid="execute-action"
                  @click="emit('execute-action', { action, record: row })"
                >
                  {{ action.label }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-result">查询成功，暂无记录</p>
    </template>

    <dl v-else data-testid="object-result" class="object-result">
      <template v-for="(value, key) in displayObject" :key="key">
        <dt>{{ key }}</dt>
        <dd>{{ formatValue(value) }}</dd>
      </template>
    </dl>

    <details class="raw-result">
      <summary>查看原始返回内容</summary>
      <pre>{{ rawOutput }}</pre>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AvailableTaskAction, TaskActionInvocation } from '../api/types'

type Row = Record<string, unknown>

const props = withDefaults(
  defineProps<{
    outputs: Record<string, unknown>
    allowDetails?: boolean
    allowProgress?: boolean
    actions?: AvailableTaskAction[]
  }>(),
  { allowDetails: false, allowProgress: false, actions: () => [] },
)
const emit = defineEmits<{
  'view-detail': [recordId: string]
  'track-progress': [recordId: string]
  'execute-action': [invocation: TaskActionInvocation]
}>()

const rows = computed(() => findRecordArray(props.outputs))
const displayObject = computed(() => findDisplayObject(props.outputs))
const columns = computed(() => {
  const result: string[] = []
  for (const row of rows.value || []) {
    for (const key of Object.keys(row)) {
      if (!result.includes(key)) result.push(key)
    }
  }
  return result
})
const hasDetailActions = computed(
  () => props.allowDetails && Boolean(rows.value?.some(detailRecordId)),
)
const hasProgressActions = computed(
  () => props.allowProgress && Boolean(rows.value?.some(progressRecordId)),
)
const hasRowActions = computed(
  () =>
    hasDetailActions.value ||
    hasProgressActions.value ||
    Boolean(rows.value?.some((row) => actionsForRow(row).length)),
)
const rawOutput = computed(() => JSON.stringify(props.outputs, null, 2))

function findRecordArray(root: unknown): Row[] | null {
  const queue: Array<{ value: unknown; depth: number }> = [{ value: root, depth: 0 }]
  let emptyArrayFound = false
  let visited = 0

  while (queue.length && visited < 250) {
    const current = queue.shift()!
    visited += 1
    if (Array.isArray(current.value)) {
      if (!current.value.length) {
        emptyArrayFound = true
      } else if (current.value.every(isPlainObject)) {
        return current.value as Row[]
      }
      continue
    }
    if (current.depth >= 6 || !isPlainObject(current.value)) continue
    for (const child of Object.values(current.value)) {
      queue.push({ value: child, depth: current.depth + 1 })
    }
  }
  return emptyArrayFound ? [] : null
}

function isPlainObject(value: unknown): value is Row {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function findDisplayObject(root: unknown): Row {
  let current: unknown = root
  for (let depth = 0; depth <= 6 && isPlainObject(current); depth += 1) {
    const entries = Object.entries(current)
    if (entries.length === 1 && isPlainObject(entries[0][1])) {
      current = entries[0][1]
      continue
    }
    if (isPlainObject(current.result)) {
      current = current.result
      continue
    }
    return current
  }
  return isPlainObject(current) ? current : { value: current }
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function rowKey(row: Row, index: number): string {
  const identity = row.id ?? row.task_id ?? row.applyNo
  return identity === undefined ? String(index) : String(identity)
}

function detailRecordId(row: Row): string | null {
  return typeof row.id === 'string' && row.id.trim() ? row.id : null
}

function progressRecordId(row: Row): string | null {
  const recordId = detailRecordId(row)
  return recordId && typeof row.applyNo === 'string' && row.applyNo.trim()
    ? recordId
    : null
}

function actionsForRow(row: Row): AvailableTaskAction[] {
  const identities = new Set(
    [row.id, row.task_id, row.applyNo]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(String),
  )
  return props.actions.filter((action) => identities.has(action.record_id))
}
</script>

<style scoped>
.task-result { margin-top: 16px; min-width: 0; }
.result-heading { align-items: center; display: flex; justify-content: space-between; margin-bottom: 10px; }
.result-heading span { color: var(--muted); font-size: 13px; }
.result-table-scroll { border: 1px solid var(--border); border-radius: 9px; max-height: 460px; overflow: auto; }
table { border-collapse: collapse; font-size: 13px; min-width: 100%; width: max-content; }
th, td { border-bottom: 1px solid var(--border); max-width: 260px; padding: 10px 12px; text-align: left; vertical-align: top; white-space: nowrap; }
th { background: color-mix(in srgb, var(--surface) 88%, var(--ink)); color: var(--muted); font-size: 12px; font-weight: 700; position: sticky; top: 0; z-index: 1; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: color-mix(in srgb, var(--signal-soft) 52%, transparent); }
.action-cell { display: flex; gap: 6px; }
.action-cell button { background: transparent; border: 1px solid var(--signal); border-radius: 6px; color: var(--signal); cursor: pointer; padding: 5px 9px; white-space: nowrap; }
.empty-result { background: var(--signal-soft); border-radius: 8px; color: var(--muted); padding: 14px; }
.object-result { display: grid; grid-template-columns: minmax(100px, auto) 1fr; margin: 0; }
.object-result dt, .object-result dd { border-bottom: 1px solid var(--border); margin: 0; padding: 9px 6px; }
.object-result dt { color: var(--muted); font-family: var(--font-mono); }
.object-result dd { min-width: 0; overflow-wrap: anywhere; white-space: normal; }
.raw-result { border-top: 1px solid var(--border); margin-top: 14px; padding-top: 12px; }
.raw-result summary { color: var(--muted); cursor: pointer; font-size: 13px; }
.raw-result pre { background: var(--ink); border-radius: 8px; color: #dff7fa; font: 12px/1.55 var(--font-mono); max-height: 300px; overflow: auto; padding: 14px; white-space: pre-wrap; word-break: break-word; }
</style>
