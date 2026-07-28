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
        <div v-if="errorMessage" class="error-note">{{ errorMessage }}</div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createRecording, startRecording, stopRecording } from '../api/commandCenter'
import type { RecordingStatus } from '../api/types'

const objective = ref('创建采购申请')
const recordingId = ref('')
const status = ref<RecordingStatus>('created')
const busy = ref(false)
const errorMessage = ref('')

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
const operatorTitle = computed(() =>
  status.value === 'recording' ? '请在弹出的采购系统窗口完成操作' : '演示一个最简单的采购操作',
)
const operatorMessage = computed(() => {
  if (status.value === 'recording') return '在采购系统填写并提交一条采购申请，然后回到这里结束演示。'
  if (status.value === 'published') return '能力已通过自动测试，可以到任务中心用自然语言调用。'
  if (status.value === 'needs_reteach') return '自动测试没有通过，请查看原因后重新演示一次。'
  return '在采购系统填写并提交一条采购申请。中控只记录本次主动开始和结束之间的操作。'
})

function stepState(step: string) {
  const order = { observe: 0, learn: 1, test: 2, publish: 3 }
  const current = {
    created: -1,
    recording: 0,
    analyzing: 1,
    testing: 2,
    published: 3,
    needs_reteach: 2,
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
    if (result.status === 'published') ElMessage.success('Skill 已通过测试并发布')
  } catch (error) {
    status.value = 'needs_reteach'
    errorMessage.value = error instanceof Error ? error.message : '演示分析失败'
  } finally {
    busy.value = false
  }
}
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
.operator-label { color: var(--process) !important; font: 700 12px Bahnschrift, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.error-note { background: #fff1f2; border: 1px solid #fecdd3; color: #be123c; margin-top: 18px; padding: 12px; }
@media (max-width: 900px) {
  .process-rail { grid-template-columns: 1fr 1fr; row-gap: 18px; }
  .workbench-grid { grid-template-columns: 1fr; }
}
</style>
