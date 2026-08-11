<template>
  <section class="command-panel">
    <div class="command-copy">
      <p class="command-kicker">中控执行</p>
      <h2>输入任务</h2>
      <p>用一句话描述要查询或处理的业务工作。</p>
    </div>
    <div class="command-input">
      <el-input
        v-model="userRequest"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="输入一项明确的业务任务"
        @keydown.ctrl.enter="submit"
      />
      <el-button type="primary" :loading="running" @click="submit">交给中控执行</el-button>
    </div>

    <div v-if="run" class="run-state">
      <div class="run-state-heading">
        <span class="pulse" :class="{ finished: terminal }"></span>
        <strong>{{ statusLabel }}</strong>
      </div>
      <p v-if="run.final_response">{{ run.final_response.summary }}</p>
      <p v-else-if="run.errors?.length" class="run-error">{{ run.errors.join('；') }}</p>
      <TaskResultTable
        v-if="run.final_response?.outputs"
        :outputs="run.final_response.outputs"
        :allow-details="canViewDetails"
        :allow-progress="canTrackProgress"
        @view-detail="viewDetails"
        @track-progress="trackProgress"
      />

      <div v-if="run.status === 'needs_object_selection'" class="object-choice">
        <p>找到多条可能的任务，请选择本次要处理的一条：</p>
        <button
          v-for="item in run.candidate_objects || []"
          :key="item.task_id"
          type="button"
          @click="chooseObject(item.task_id)"
        >
          <strong>{{ item.title }}</strong>
          <small>{{ item.task_id }}</small>
        </button>
      </div>
    </div>

    <section v-if="detailRunning || detailRun || detailError" class="detail-state">
      <h3>所选采购申请详情</h3>
      <p v-if="detailRunning" data-testid="detail-loading">正在查询详情…</p>
      <p v-if="detailError" data-testid="detail-error" class="run-error">
        {{ detailError }}
      </p>
      <template v-if="detailRun?.final_response">
        <p>{{ detailRun.final_response.summary }}</p>
        <div
          v-for="(output, stepId) in detailRun.final_response.outputs || {}"
          :key="stepId"
          class="detail-output"
        >
          <strong>{{ stepId }}</strong>
          <TaskResultTable :outputs="{ [stepId]: output }" />
        </div>
      </template>
    </section>

    <section v-if="progressRunning || progressRun || progressError" class="progress-state">
      <p v-if="progressRunning" data-testid="progress-loading">正在追踪采购进度…</p>
      <p v-if="progressError" data-testid="progress-error" class="run-error">
        {{ progressError }}
      </p>
      <PurchaseProgress
        v-if="progressRun?.final_response?.progress"
        :progress="progressRun.final_response.progress"
      />
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createPurchaseProgressRun,
  createTaskDetailRun,
  createTaskRun,
  selectTaskObject,
} from '../api/commandCenter'
import type { TaskRunView } from '../api/types'
import TaskResultTable from './TaskResultTable.vue'
import PurchaseProgress from './PurchaseProgress.vue'

const userRequest = ref('')
const running = ref(false)
const run = ref<TaskRunView | null>(null)
const detailRunning = ref(false)
const detailRun = ref<TaskRunView | null>(null)
const detailError = ref('')
const progressRunning = ref(false)
const progressRun = ref<TaskRunView | null>(null)
const progressError = ref('')
const terminal = computed(() => ['succeeded', 'failed'].includes(run.value?.status || ''))
const canViewDetails = computed(
  () => run.value?.status === 'succeeded' && run.value.execution_mode === 'tool',
)
const canTrackProgress = computed(
  () => run.value?.status === 'succeeded' && run.value.execution_mode === 'tool',
)
const statusLabel = computed(() => ({
  matching: '正在理解任务',
  needs_input: '需要补充任务信息',
  needs_object_selection: '需要选择业务对象',
  executing: '正在执行 Skill',
  verifying: '正在核对业务结果',
  succeeded: '任务已完成',
  failed: '任务执行失败',
}[run.value?.status || 'matching']))

async function submit() {
  if (!userRequest.value.trim()) {
    ElMessage.warning('请输入要完成的任务')
    return
  }
  running.value = true
  detailRun.value = null
  detailError.value = ''
  progressRun.value = null
  progressError.value = ''
  try {
    run.value = await createTaskRun(userRequest.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '任务发起失败')
  } finally {
    running.value = false
  }
}

async function trackProgress(recordId: string) {
  if (!run.value) return
  progressRunning.value = true
  progressRun.value = null
  progressError.value = ''
  try {
    progressRun.value = await createPurchaseProgressRun(run.value.run_id, recordId)
  } catch (error) {
    progressError.value = error instanceof Error ? error.message : '采购进度追踪失败'
    ElMessage.error(progressError.value)
  } finally {
    progressRunning.value = false
  }
}

async function viewDetails(recordId: string) {
  if (!run.value) return
  detailRunning.value = true
  detailRun.value = null
  detailError.value = ''
  try {
    detailRun.value = await createTaskDetailRun(run.value.run_id, recordId)
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '详情查询失败'
    ElMessage.error(detailError.value)
  } finally {
    detailRunning.value = false
  }
}

async function chooseObject(objectId: string) {
  if (!run.value) return
  running.value = true
  try {
    run.value = await selectTaskObject(run.value.run_id, objectId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '任务选择失败')
  } finally {
    running.value = false
  }
}
</script>

<style scoped>
.command-panel { display: grid; gap: 22px; min-height: 100%; }
.command-copy h2 { font-size: 21px; margin: 5px 0 8px; }
.command-copy p { color: var(--muted); line-height: 1.5; margin: 0; }
.command-kicker { color: var(--signal) !important; font: 700 12px var(--font-mono); letter-spacing: .09em; text-transform: uppercase; }
.command-input { align-items: stretch; display: grid; gap: 10px; }
.command-input :deep(textarea) { border: 1px solid var(--border); border-radius: 10px; box-shadow: none; min-height: 104px !important; padding: 14px; }
.command-input :deep(.el-button) { border-radius: 9px; font-weight: 700; height: 44px; margin: 0; }
.run-state { border-top: 1px solid var(--border); min-width: 0; padding-top: 18px; }
.run-state-heading { align-items: center; display: flex; gap: 9px; }
.pulse { background: var(--signal); border-radius: 50%; box-shadow: 0 0 0 5px var(--signal-soft); height: 9px; width: 9px; }
.pulse.finished { background: var(--success); box-shadow: none; }
.run-state p { color: var(--muted); margin-bottom: 0; }
.run-error { color: var(--danger) !important; }
.object-choice { display: grid; gap: 8px; margin-top: 14px; }
.object-choice button { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; color: var(--ink); cursor: pointer; display: flex; justify-content: space-between; padding: 12px 14px; text-align: left; }
.object-choice small { color: var(--muted); }
.detail-state { border-top: 1px solid var(--border); min-width: 0; padding-top: 18px; }
.detail-state h3 { font-size: 18px; margin: 0 0 10px; }
.detail-state > p { color: var(--muted); }
.detail-output { border-top: 1px dashed var(--border); margin-top: 14px; padding-top: 12px; }
.detail-output > strong { color: var(--muted); font: 700 12px var(--font-mono); }
.progress-state { border-top: 1px solid var(--border); min-width: 0; padding-top: 18px; }
.progress-state > p { color: var(--muted); }
@media (max-width: 760px) {
  .command-panel { grid-template-columns: 1fr; }
  .command-input { flex-direction: column; }
}
</style>
