<template>
  <section class="history" aria-labelledby="history-title">
    <div class="history-heading">
      <div>
        <p class="section-label">录制记录</p>
        <h2 id="history-title">最近测试</h2>
      </div>
      <span>{{ recordings.length }} 条</span>
    </div>

    <div v-if="recordings.length" class="history-list">
      <button
        v-for="recording in recordings"
        :key="recording.recording_id"
        type="button"
        class="history-row"
        :class="{ selected: recording.recording_id === selectedId }"
        :data-recording-id="recording.recording_id"
        :aria-current="recording.recording_id === selectedId ? 'true' : undefined"
        @click="$emit('select', recording.recording_id)"
      >
        <span class="history-main">
          <strong>{{ recording.objective }}</strong>
          <small class="mono">{{ recording.source_system }}</small>
        </span>
        <span class="history-meta">
          <span class="status-dot" :class="`is-${status(recording.status).tone}`"></span>
          <span>{{ status(recording.status).label }}</span>
          <time class="mono">{{ formatTime(recording.updated_at) }}</time>
        </span>
      </button>
    </div>

    <div v-else class="empty-history">
      <strong>还没有浏览器录制</strong>
      <p>打开演示观察器录制一次只读业务操作。</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ExtensionRecordingStatus, RecordingSummary } from '../api/types'
import { recordingStatusPresentation } from '../recordingPresentation'

defineProps<{ recordings: RecordingSummary[]; selectedId: string }>()
defineEmits<{ select: [recordingId: string] }>()

const status = (value: ExtensionRecordingStatus) => recordingStatusPresentation(value)
const formatTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '时间未知'
</script>

<style scoped>
.history { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 24px; }
.history-heading { align-items: flex-end; display: flex; justify-content: space-between; }
.history-heading h2 { font-size: 20px; margin: 5px 0 0; }
.history-heading > span { color: var(--muted); font: 12px var(--font-mono); }
.section-label { color: var(--signal); font-size: 12px; font-weight: 700; letter-spacing: .09em; margin: 0; text-transform: uppercase; }
.history-list { border-top: 1px solid var(--border); margin-top: 18px; }
.history-row { align-items: center; background: transparent; border: 0; border-bottom: 1px solid var(--border); color: inherit; cursor: pointer; display: grid; font: inherit; gap: 18px; grid-template-columns: minmax(0, 1fr) auto; padding: 15px 12px; text-align: left; transition: background-color .18s ease, transform .18s ease; width: 100%; }
.history-row:hover, .history-row.selected { background: var(--signal-soft); }
.history-row.selected { box-shadow: inset 3px 0 var(--signal); }
.history-main { display: grid; gap: 5px; min-width: 0; }
.history-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-main small { color: var(--muted); }
.history-meta { align-items: center; display: grid; gap: 8px; grid-template-columns: 8px minmax(128px, auto) minmax(150px, auto); }
.history-meta time { color: var(--muted); text-align: right; }
.status-dot { background: var(--muted); border-radius: 50%; height: 8px; width: 8px; }
.status-dot.is-running { background: var(--signal); }
.status-dot.is-success { background: var(--success); }
.status-dot.is-waiting { background: var(--waiting); }
.status-dot.is-danger { background: var(--danger); }
.mono { font-family: var(--font-mono); font-size: 12px; }
.empty-history { color: var(--muted); padding: 42px 10px 22px; text-align: center; }
.empty-history strong { color: var(--ink); }
.empty-history p { margin: 7px 0 0; }
@media (max-width: 720px) {
  .history { padding: 19px; }
  .history-row { align-items: start; grid-template-columns: 1fr; }
  .history-meta { grid-template-columns: 8px 1fr auto; }
}
@media (prefers-reduced-motion: reduce) {
  .history-row { transition: none; }
}
</style>
