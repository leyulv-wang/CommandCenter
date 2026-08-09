<template>
  <article class="learning-card" aria-labelledby="learning-title">
    <header class="card-heading">
      <div>
        <p class="section-label">最新学习结果</p>
        <h2 id="learning-title">录制生成的能力</h2>
      </div>
      <span v-if="recording" class="status-pill" :class="`is-${presentation.tone}`">
        {{ presentation.label }}
      </span>
    </header>

    <div v-if="recording" class="learning-content">
      <div class="skill-name">
        <span>Skill</span>
        <strong>{{ candidate?.name ?? '尚未生成 Skill' }}</strong>
      </div>

      <dl class="recording-facts">
        <div>
          <dt>演示目标</dt>
          <dd>{{ recording.objective }}</dd>
        </div>
        <div>
          <dt>业务系统</dt>
          <dd class="mono">{{ recording.source_system }}</dd>
        </div>
        <div>
          <dt>当前阶段</dt>
          <dd>{{ presentation.detail }}</dd>
        </div>
        <div>
          <dt>更新时间</dt>
          <dd class="mono">{{ formattedTime }}</dd>
        </div>
      </dl>

      <div v-if="recording.failure_reasons?.length" class="failure-block" role="alert">
        <strong>需要处理</strong>
        <ul>
          <li v-for="reason in recording.failure_reasons" :key="reason">{{ reason }}</li>
        </ul>
      </div>
    </div>

    <div v-else class="empty-state">
      <strong>还没有学习结果</strong>
      <p>请先使用浏览器扩展完成一次录制。</p>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ExtensionRecordingDetail } from '../api/types'
import { extractCandidateSkill, recordingStatusPresentation } from '../recordingPresentation'

const props = defineProps<{ recording?: ExtensionRecordingDetail }>()

const presentation = computed(() =>
  props.recording
    ? recordingStatusPresentation(props.recording.status)
    : { label: '', detail: '', tone: 'neutral' as const },
)
const candidate = computed(() => props.recording ? extractCandidateSkill(props.recording) : null)
const formattedTime = computed(() => {
  if (!props.recording?.updated_at) return '时间未知'
  return new Date(props.recording.updated_at).toLocaleString('zh-CN', { hour12: false })
})
</script>

<style scoped>
.learning-card { min-height: 100%; }
.card-heading { align-items: flex-start; display: flex; gap: 20px; justify-content: space-between; }
.card-heading h2 { font-size: 21px; margin: 5px 0 0; }
.section-label { color: var(--signal); font-size: 12px; font-weight: 700; letter-spacing: .09em; margin: 0; text-transform: uppercase; }
.status-pill { border: 1px solid currentColor; border-radius: 999px; flex: none; font-size: 12px; font-weight: 700; padding: 6px 10px; }
.is-running { color: var(--signal); }
.is-success { color: var(--success); }
.is-waiting { color: var(--waiting); }
.is-danger { color: var(--danger); }
.is-neutral { color: var(--muted); }
.learning-content { margin-top: 28px; }
.skill-name { border-left: 3px solid var(--signal); display: grid; gap: 7px; padding: 4px 0 4px 16px; }
.skill-name span { color: var(--muted); font: 600 11px var(--font-mono); letter-spacing: .1em; text-transform: uppercase; }
.skill-name strong { font-size: clamp(20px, 2.3vw, 29px); line-height: 1.25; }
.recording-facts { display: grid; gap: 0; grid-template-columns: 1fr 1fr; margin: 26px 0 0; }
.recording-facts div { border-top: 1px solid var(--border); padding: 15px 12px 15px 0; }
.recording-facts div:nth-child(even) { padding-left: 12px; }
.recording-facts dt { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.recording-facts dd { line-height: 1.5; margin: 0; overflow-wrap: anywhere; }
.mono { font-family: var(--font-mono); font-size: 12px; }
.failure-block { background: var(--danger-soft); border-left: 3px solid var(--danger); margin-top: 20px; padding: 14px 16px; }
.failure-block ul { margin: 8px 0 0; padding-left: 18px; }
.empty-state { align-content: center; color: var(--muted); display: grid; min-height: 250px; text-align: center; }
.empty-state strong { color: var(--ink); }
.empty-state p { margin: 7px 0 0; }
@media (max-width: 640px) {
  .card-heading { align-items: stretch; flex-direction: column; }
  .status-pill { align-self: flex-start; }
  .recording-facts { grid-template-columns: 1fr; }
  .recording-facts div:nth-child(even) { padding-left: 0; }
}
</style>
