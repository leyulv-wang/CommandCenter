<template>
  <main class="console-shell">
    <header class="console-header">
      <div>
        <p class="product-mark">CommandCenter / Test console</p>
        <h1>中控测试台</h1>
        <p>验证一次演示如何成为可复用的 API Skill。</p>
      </div>
      <div class="service-state" :class="{ offline: !serviceOnline }">
        <span></span>
        {{ serviceOnline ? '中控在线' : '中控离线' }}
      </div>
    </header>

    <section class="workflow-thesis" aria-label="当前测试路径">
      <span>浏览器演示</span>
      <i>→</i>
      <span>API Skill</span>
      <i>→</i>
      <span>中控执行</span>
    </section>

    <div v-if="connectionError" class="connection-error" role="alert">
      <div>
        <strong>无法连接中控</strong>
        <p>{{ connectionError }}</p>
      </div>
      <button data-testid="refresh-recordings" type="button" @click="refreshRecordings">
        重新连接
      </button>
    </div>

    <SystemConnectionStatus />

    <div class="console-grid">
      <NaturalLanguageTaskPanel />
      <LatestLearningResult :recording="selectedRecording" />
    </div>

    <div class="history-toolbar">
      <p>录制由浏览器扩展发起，这里只展示学习和执行结果。</p>
      <button
        v-if="!connectionError"
        data-testid="refresh-recordings"
        type="button"
        :disabled="loading"
        @click="refreshRecordings"
      >
        {{ loading ? '刷新中…' : '刷新状态' }}
      </button>
    </div>
    <RecordingHistory
      :recordings="recordings"
      :selected-id="selectedId"
      @select="selectRecording"
    />
  </main>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getRecording, listRecordings } from '../api/commandCenter'
import type { ExtensionRecordingDetail, RecordingSummary } from '../api/types'
import LatestLearningResult from '../components/LatestLearningResult.vue'
import NaturalLanguageTaskPanel from '../components/NaturalLanguageTaskPanel.vue'
import RecordingHistory from '../components/RecordingHistory.vue'
import SystemConnectionStatus from '../components/SystemConnectionStatus.vue'
import { isRecordingTerminal } from '../recordingPresentation'

const POLL_INTERVAL_MS = 3000

const recordings = ref<RecordingSummary[]>([])
const selectedId = ref('')
const selectedRecording = ref<ExtensionRecordingDetail>()
const serviceOnline = ref(false)
const connectionError = ref('')
const loading = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | undefined

function clearPoll() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = undefined
}

function schedulePoll(recording: ExtensionRecordingDetail) {
  clearPoll()
  if (isRecordingTerminal(recording.status)) return
  pollTimer = setTimeout(() => loadRecording(recording.recording_id), POLL_INTERVAL_MS)
}

async function loadRecording(recordingId: string) {
  try {
    const detail = await getRecording(recordingId)
    if (selectedId.value !== recordingId) return
    selectedRecording.value = detail
    serviceOnline.value = true
    connectionError.value = ''
    schedulePoll(detail)
  } catch (error) {
    serviceOnline.value = false
    connectionError.value = error instanceof Error ? error.message : '读取录制详情失败'
    clearPoll()
  }
}

async function refreshRecordings() {
  loading.value = true
  clearPoll()
  try {
    const items = await listRecordings(8)
    recordings.value = items
    serviceOnline.value = true
    connectionError.value = ''
    if (!items.some((item) => item.recording_id === selectedId.value)) {
      selectedId.value = items[0]?.recording_id ?? ''
    }
    if (selectedId.value) await loadRecording(selectedId.value)
    else selectedRecording.value = undefined
  } catch (error) {
    serviceOnline.value = false
    connectionError.value = error instanceof Error ? error.message : '录制列表加载失败'
  } finally {
    loading.value = false
  }
}

async function selectRecording(recordingId: string) {
  selectedId.value = recordingId
  clearPoll()
  await loadRecording(recordingId)
}

onMounted(refreshRecordings)
onBeforeUnmount(clearPoll)
</script>

<style scoped>
.console-shell { margin: 0 auto; max-width: 1180px; padding: 38px 28px 64px; }
.console-header { align-items: flex-start; display: flex; justify-content: space-between; }
.console-header h1 { font-size: clamp(32px, 5vw, 54px); letter-spacing: -.045em; line-height: 1; margin: 10px 0 14px; }
.console-header > div > p:last-child { color: var(--muted); font-size: 16px; margin: 0; }
.product-mark { color: var(--signal); font: 700 12px var(--font-mono); letter-spacing: .08em; margin: 0; text-transform: uppercase; }
.service-state { align-items: center; background: var(--success-soft); border: 1px solid color-mix(in srgb, var(--success) 28%, transparent); border-radius: 999px; color: var(--success); display: flex; font-size: 13px; font-weight: 700; gap: 8px; padding: 8px 12px; }
.service-state span { background: currentColor; border-radius: 50%; box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 13%, transparent); height: 7px; width: 7px; }
.service-state.offline { background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 28%, transparent); color: var(--danger); }
.workflow-thesis { align-items: center; background: var(--ink); border-radius: 16px; color: white; display: grid; font-size: clamp(17px, 2.4vw, 26px); font-weight: 700; gap: 16px; grid-template-columns: 1fr auto 1fr auto 1fr; margin: 34px 0 22px; padding: 22px 28px; text-align: center; }
.workflow-thesis i { color: #78d4df; font-style: normal; }
.console-grid { display: grid; gap: 20px; grid-template-columns: minmax(0, 1fr) minmax(360px, .9fr); }
.console-grid > * { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 26px; }
.connection-error { align-items: center; background: var(--danger-soft); border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); border-radius: 12px; color: var(--danger); display: flex; justify-content: space-between; margin-bottom: 20px; padding: 14px 16px; }
.connection-error p { margin: 4px 0 0; }
.connection-error button, .history-toolbar button { background: transparent; border: 1px solid currentColor; border-radius: 8px; color: inherit; cursor: pointer; font: 700 13px inherit; padding: 9px 12px; }
.history-toolbar { align-items: center; display: flex; justify-content: space-between; margin: 28px 0 10px; }
.history-toolbar p { color: var(--muted); margin: 0; }
.history-toolbar button { color: var(--signal); }
.history-toolbar button:disabled { cursor: wait; opacity: .55; }
@media (max-width: 860px) {
  .console-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .console-shell { padding: 24px 16px 44px; }
  .console-header { gap: 20px; }
  .console-header > div > p:last-child { font-size: 14px; }
  .service-state { font-size: 0; padding: 9px; }
  .workflow-thesis { gap: 7px; padding: 18px 12px; }
  .console-grid > * { padding: 20px; }
  .connection-error, .history-toolbar { align-items: stretch; flex-direction: column; gap: 12px; }
}
</style>
