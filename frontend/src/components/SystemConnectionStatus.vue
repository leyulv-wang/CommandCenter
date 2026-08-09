<template>
  <section class="system-connection" :class="connection?.status || 'loading'">
    <div class="connection-rail" aria-hidden="true"><span></span></div>
    <div class="connection-copy">
      <p class="connection-label">真实系统连接</p>
      <strong>{{ headline }}</strong>
      <p>{{ guidance }}</p>
      <p v-if="feedback" class="connection-feedback" :class="{ failed: feedbackFailed }">
        {{ feedback }}
      </p>
    </div>
    <div v-if="connection?.status === 'connected'" class="connection-actions">
      <button
        data-testid="verify-system-skill"
        type="button"
        :disabled="busy"
        @click="verify"
      >
        {{ busy ? '验证中…' : '验证最新 Skill' }}
      </button>
      <button
        data-testid="disconnect-system"
        class="quiet"
        type="button"
        :disabled="busy"
        @click="disconnect"
      >
        断开
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  disconnectSystem,
  getSystemConnection,
  verifyLatestSystemSkill,
} from '../api/commandCenter'
import type { SystemConnectionView } from '../api/types'

const props = withDefaults(defineProps<{ systemCode?: string }>(), {
  systemCode: 'yifeng_mes',
})

const connection = ref<SystemConnectionView>()
const busy = ref(false)
const feedback = ref('')
const feedbackFailed = ref(false)

const headline = computed(() => {
  if (!connection.value) return '正在读取连接状态'
  return connection.value.status === 'connected'
    ? `${connection.value.display_name} 已连接`
    : '等待浏览器连接'
})

const guidance = computed(() => connection.value?.status === 'connected'
  ? '中控可使用当前浏览器会话执行已验证的只读 API Skill。'
  : '在 MES 页面打开扩展并点击“连接中控”，再执行一次普通查询。')

async function load() {
  try {
    connection.value = await getSystemConnection(props.systemCode)
  } catch (error) {
    feedbackFailed.value = true
    feedback.value = error instanceof Error ? error.message : '连接状态读取失败'
  }
}

async function verify() {
  busy.value = true
  feedback.value = ''
  feedbackFailed.value = false
  try {
    const result = await verifyLatestSystemSkill(props.systemCode)
    feedback.value = result.status === 'verified_candidate'
      ? '最新 API Skill 已通过只读验证。'
      : '只读验证未通过，Skill 仍保留为候选。'
    feedbackFailed.value = result.status !== 'verified_candidate'
  } catch (error) {
    feedbackFailed.value = true
    feedback.value = error instanceof Error ? error.message : 'Skill 验证失败'
  } finally {
    busy.value = false
  }
}

async function disconnect() {
  busy.value = true
  feedback.value = ''
  try {
    connection.value = await disconnectSystem(props.systemCode)
  } catch (error) {
    feedbackFailed.value = true
    feedback.value = error instanceof Error ? error.message : '断开连接失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.system-connection { align-items: center; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; display: grid; gap: 18px; grid-template-columns: 14px minmax(0, 1fr) auto; margin: 0 0 20px; padding: 16px 18px; }
.connection-rail { align-self: stretch; background: var(--border); border-radius: 999px; display: flex; justify-content: center; min-height: 58px; width: 4px; }
.connection-rail span { background: var(--muted); border: 3px solid var(--surface); border-radius: 50%; box-shadow: 0 0 0 1px var(--border); height: 10px; margin-top: 7px; width: 10px; }
.system-connection.connected .connection-rail { background: color-mix(in srgb, var(--success) 35%, var(--border)); }
.system-connection.connected .connection-rail span { background: var(--success); box-shadow: 0 0 0 4px var(--success-soft); }
.connection-copy strong { color: var(--ink); display: block; font-size: 16px; }
.connection-copy p { color: var(--muted); font-size: 13px; margin: 5px 0 0; }
.connection-label { color: var(--signal) !important; font: 700 11px var(--font-mono); letter-spacing: .08em; margin: 0 0 5px !important; text-transform: uppercase; }
.connection-feedback { color: var(--success) !important; font-weight: 700; }
.connection-feedback.failed { color: var(--danger) !important; }
.connection-actions { display: flex; gap: 8px; }
.connection-actions button { background: var(--ink); border: 1px solid var(--ink); border-radius: 8px; color: white; cursor: pointer; font: 700 13px inherit; padding: 9px 12px; }
.connection-actions button.quiet { background: transparent; color: var(--muted); }
.connection-actions button:disabled { cursor: wait; opacity: .55; }
@media (max-width: 680px) {
  .system-connection { align-items: stretch; grid-template-columns: 8px 1fr; }
  .connection-actions { grid-column: 2; }
}
</style>
