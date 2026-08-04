<template>
  <section class="page demonstration-page">
    <div class="page-header">
      <div>
        <p class="eyebrow">Teach by doing</p>
        <h2>演示工作台</h2>
        <p class="page-intro">完成一次真实业务操作，中控会观察 API、自动测试并发布可复用能力。</p>
      </div>
      <el-tag :type="statusTagType">{{ statusLabel }}</el-tag>
    </div>

    <ol class="process-rail" aria-label="Skill 生成进度">
      <li v-for="step in processSteps" :key="step.key" :class="stepState(step.key)">
        <span class="rail-node">{{ step.mark }}</span>
        <div><strong>{{ step.label }}</strong><small>{{ step.help }}</small></div>
      </li>
    </ol>

    <div class="workbench-grid">
      <el-card class="instruction-panel" shadow="never">
        <template #header>本次演示</template>
        <el-form label-position="top">
          <el-form-item label="演示目标">
            <el-input v-model="objective" placeholder="例如：创建采购申请" />
          </el-form-item>
          <div class="action-row">
            <el-button
              type="primary"
              :disabled="status !== 'created' && status !== 'needs_reteach'"
              :loading="busy"
              @click="handleStart"
            >
              开始演示
            </el-button>
            <el-button
              type="danger"
              plain
              :disabled="status !== 'recording'"
              :loading="busy"
              @click="handleStop"
            >
              结束演示
            </el-button>
          </div>
        </el-form>
      </el-card>

      <section class="operator-note">
        <p class="operator-label">操作提示</p>
        <h3>{{ operatorTitle }}</h3>
        <p>{{ operatorMessage }}</p>
        <ul v-if="failureReasons.length" class="failure-reasons">
          <li v-for="reason in failureReasons" :key="reason">{{ reason }}</li>
        </ul>
        <div v-if="errorMessage" class="error-note">{{ errorMessage }}</div>
      </section>
    </div>

    <el-card class="extension-result" shadow="never">
      <div class="result-header">
        <h3>浏览器扩展录制结果</h3>
        <el-button :loading="extensionBusy" @click="loadExtensionRecording">刷新</el-button>
      </div>
      <div v-if="latestExtensionRecording" class="result-content">
        <div>
          <strong>{{ latestExtensionRecording.objective }}</strong>
          <p>{{ latestExtensionRecording.source_system }} · {{ extensionUpdatedAt }}</p>
        </div>
        <el-tag :type="extensionStatusType">{{ extensionStatusLabel }}</el-tag>
      </div>
      <p v-else-if="!extensionError" class="empty-result">尚无浏览器扩展录制</p>
      <p v-if="extensionError" class="extension-error">{{ extensionError }}</p>
      <ul v-if="latestExtensionRecording?.failure_reasons.length" class="failure-reasons">
        <li v-for="reason in latestExtensionRecording.failure_reasons" :key="reason">{{ reason }}</li>
      </ul>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createRecording, listRecordings, startRecording, stopRecording } from '../api/commandCenter'
import type { RecordingFailureStage, RecordingStatus, RecordingSummary } from '../api/types'

const objective = ref('创建采购申请')
const recordingId = ref('')
const status = ref<RecordingStatus>('created')
const busy = ref(false)
const errorMessage = ref('')
const failureStage = ref<RecordingFailureStage>()
const failureReasons = ref<string[]>([])
const latestExtensionRecording = ref<RecordingSummary>()
const extensionBusy = ref(false)
const extensionError = ref('')

const processSteps = [
  { key: 'observe', mark: '01', label: '观察', help: '记录页面动作和真实 API' },
  { key: 'learn', mark: '02', label: '学习', help: '智能体理解并生成 Skill' },
  { key: 'test', mark: '03', label: '测试', help: '自动完成三类无害测试' },
  { key: 'publish', mark: '04', label: '发布', help: '通过后立即可供员工调用' },
] as const

const statusLabel = computed(() => ({
  created: '等待开始',
  recording: '正在观察',
  analyzing: '正在学习',
  testing: '正在测试',
  published: 'Skill 已发布',
  needs_reteach: '需要重新演示',
}[status.value]))
const statusTagType = computed(() =>
  status.value === 'published' ? 'success' : status.value === 'needs_reteach' ? 'danger' : 'primary',
)
const operatorTitle = computed(() => {
  if (status.value === 'recording') return '请在弹出的采购系统窗口完成操作'
  if (status.value === 'published') return 'Skill 已通过测试并发布'
  if (status.value !== 'needs_reteach') return '演示一个最简单的采购操作'
  if (failureStage.value === 'analysis') return '演示内容无法生成 Skill'
  if (failureStage.value === 'testing') return '自动测试没有通过'
  if (failureStage.value === 'system') return '系统处理失败'
  return '本次演示未能发布 Skill'
})
const operatorMessage = computed(() => {
  if (status.value === 'recording') return '在采购系统填写并提交一条采购申请，然后回到这里结束演示。'
  if (status.value === 'published') return '能力已通过自动测试，可以到任务中心用自然语言调用。'
  if (status.value === 'needs_reteach') {
    if (failureStage.value === 'analysis') return '智能体无法将本次演示编译为可复用能力，请根据原因重新演示。'
    if (failureStage.value === 'testing') return '候选 Skill 已生成，但无害测试没有全部通过。'
    if (failureStage.value === 'system') return '系统未能完成本次演示处理，请根据提示检查服务。'
    return '本次演示未能发布 Skill，请重新演示一次。'
  }
  return '在采购系统填写并提交一条采购申请。中控只记录本次主动开始和结束之间的操作。'
})
const extensionStatusLabel = computed(() => ({
  created: '等待录制',
  recording: '正在录制',
  upload_failed: '上传失败',
  analyzing: '智能体分析中',
  verified_candidate: 'Skill 验证成功',
  rejected: 'Skill 验证失败',
  recorded: '录制完成',
}[latestExtensionRecording.value?.status ?? 'created']))
const extensionStatusType = computed(() => {
  const status = latestExtensionRecording.value?.status
  if (status === 'verified_candidate') return 'success'
  if (status === 'upload_failed' || status === 'rejected') return 'danger'
  return 'primary'
})
const extensionUpdatedAt = computed(() => {
  const value = latestExtensionRecording.value?.updated_at
  return value ? new Date(value).toLocaleString('zh-CN') : '时间未知'
})

function stepState(step: string) {
  const order = { observe: 0, learn: 1, test: 2, publish: 3 }
  const reteachStep = failureStage.value === 'testing' ? 2 : 1
  const current = {
    created: -1,
    recording: 0,
    analyzing: 1,
    testing: 2,
    published: 3,
    needs_reteach: reteachStep,
  }[status.value]
  return { active: order[step as keyof typeof order] === current, done: order[step as keyof typeof order] < current }
}

async function handleStart() {
  if (!objective.value.trim()) {
    ElMessage.warning('请填写演示目标')
    return
  }
  busy.value = true
  errorMessage.value = ''
  failureStage.value = undefined
  failureReasons.value = []
  try {
    const created = await createRecording({
      objective: objective.value,
      source_system: 'connected_system',
      source_task_id: 'purchase-demonstration',
    })
    recordingId.value = created.recording_id
    const started = await startRecording(recordingId.value)
    status.value = started.status
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '演示启动失败'
  } finally {
    busy.value = false
  }
}

async function handleStop() {
  if (!recordingId.value) return
  busy.value = true
  errorMessage.value = ''
  status.value = 'analyzing'
  try {
    const result = await stopRecording(recordingId.value)
    status.value = result.status
    failureStage.value = result.failure_stage
    failureReasons.value = result.failure_reasons ?? []
    if (result.status === 'published') ElMessage.success('Skill 已通过测试并发布')
  } catch (error) {
    status.value = 'needs_reteach'
    failureStage.value = 'system'
    failureReasons.value = []
    errorMessage.value = error instanceof Error ? error.message : '演示分析失败'
  } finally {
    busy.value = false
  }
}

async function loadExtensionRecording() {
  extensionBusy.value = true
  extensionError.value = ''
  try {
    const recordings = await listRecordings(1)
    latestExtensionRecording.value = recordings[0]
  } catch (error) {
    extensionError.value = error instanceof Error ? error.message : '读取录制结果失败'
  } finally {
    extensionBusy.value = false
  }
}

onMounted(loadExtensionRecording)
</script>

<style scoped>
.demonstration-page { --signal: #2563eb; --process: #0e7490; --safe: #15803d; }
.page-intro { color: #64748b; margin: 8px 0 0; }
.process-rail { background: #14213d; color: #fff; display: grid; grid-template-columns: repeat(4, 1fr); list-style: none; margin: 0 0 22px; padding: 22px; }
.process-rail li { align-items: center; display: flex; gap: 12px; opacity: .42; position: relative; }
.process-rail li:not(:last-child)::after { background: #52617a; content: ''; height: 1px; position: absolute; right: 12px; top: 20px; width: 24%; }
.process-rail li.active, .process-rail li.done { opacity: 1; }
.process-rail li.active .rail-node { background: var(--process); box-shadow: 0 0 0 5px rgb(14 116 144 / 25%); }
.process-rail li.done .rail-node { background: var(--safe); }
.rail-node { align-items: center; background: #52617a; border-radius: 50%; display: flex; font: 700 12px Bahnschrift, sans-serif; height: 40px; justify-content: center; width: 40px; }
.process-rail strong, .process-rail small { display: block; }
.process-rail small { color: #b9c5d6; margin-top: 4px; }
.workbench-grid { display: grid; gap: 20px; grid-template-columns: minmax(0, 1.3fr) minmax(280px, .7fr); }
.instruction-panel { border-top: 3px solid var(--signal); }
.action-row { display: flex; gap: 10px; }
.operator-note { background: #e8f3f6; border-left: 4px solid var(--process); padding: 28px; }
.operator-note h3 { color: #14213d; font-size: 21px; margin: 8px 0 12px; }
.operator-note p { color: #475569; line-height: 1.7; }
.failure-reasons { color: #9f1239; line-height: 1.7; margin: 14px 0 0; padding-left: 20px; }
.operator-label { color: var(--process) !important; font: 700 12px Bahnschrift, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.error-note { background: #fff1f2; border: 1px solid #fecdd3; color: #be123c; margin-top: 18px; padding: 12px; }
.extension-result { margin-top: 20px; }
.result-header, .result-content { align-items: center; display: flex; justify-content: space-between; }
.result-header { margin-bottom: 16px; }
.result-header h3 { margin: 0; }
.result-content p, .empty-result { color: #64748b; margin: 6px 0 0; }
.extension-error { color: #be123c; margin: 0; }
@media (max-width: 900px) {
  .process-rail { grid-template-columns: 1fr 1fr; row-gap: 18px; }
  .workbench-grid { grid-template-columns: 1fr; }
}
</style>
