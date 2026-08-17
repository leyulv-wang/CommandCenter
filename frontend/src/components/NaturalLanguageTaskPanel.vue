<template>
  <section class="command-panel">
    <div class="command-copy">
      <p class="command-kicker">中控执行</p>
      <h2>输入任务</h2>
      <p>用一句话描述要查询或处理的业务工作。</p>
    </div>
    <div class="command-input">
      <el-input v-model="userRequest" type="textarea" :rows="2" resize="none"
        placeholder="输入一项明确的业务任务" @keydown.ctrl.enter="submit" />
      <el-button data-testid="start-task-session" type="primary" :loading="running" @click="submit">
        交给中控执行
      </el-button>
    </div>

    <div v-if="session" class="session-state">
      <TaskInteractionRenderer :session="session" @submit-message="submitMessage"
        @submit-inputs="submitInputs" @submit-selection="submitInputs" @confirm="submitConfirmation" />
      <el-button v-if="canUseLegacyFallback" data-testid="legacy-query-fallback"
        :loading="legacyRunning" @click="runLegacyQuery">使用兼容查询</el-button>
    </div>

    <div v-if="run" class="run-state">
      <div class="run-state-heading">
        <span class="pulse" :class="{ finished: terminal }"></span>
        <strong>{{ statusLabel }}</strong>
      </div>
      <p v-if="run.final_response">{{ run.final_response.summary }}</p>
      <p v-else-if="run.errors?.length" class="run-error">{{ run.errors.join('；') }}</p>
      <TaskResultTable v-if="run.final_response?.outputs" :outputs="run.final_response.outputs"
        :allow-details="canViewDetails" :allow-progress="canTrackProgress"
        :actions="run.available_actions || []" @view-detail="viewDetails"
        @track-progress="trackProgress" @execute-action="executeAction" />
    </div>

    <section v-if="detailRunning || detailRun || detailError" class="detail-state">
      <h3>所选采购申请详情</h3>
      <p v-if="detailRunning" data-testid="detail-loading">正在查询详情…</p>
      <p v-if="detailError" data-testid="detail-error" class="run-error">{{ detailError }}</p>
      <template v-if="detailRun?.final_response">
        <p>{{ detailRun.final_response.summary }}</p>
        <div v-for="(output, stepId) in detailRun.final_response.outputs || {}" :key="stepId" class="detail-output">
          <strong>{{ stepId }}</strong>
          <TaskResultTable :outputs="{ [stepId]: output }" />
        </div>
      </template>
    </section>

    <section v-if="progressRunning || progressRun || progressError" class="progress-state">
      <p v-if="progressRunning" data-testid="progress-loading">正在追踪采购进度…</p>
      <p v-if="progressError" data-testid="progress-error" class="run-error">{{ progressError }}</p>
      <PurchaseProgress v-if="progressRun?.final_response?.progress" :progress="progressRun.final_response.progress" />
    </section>

    <section v-if="actionRunning || actionRun || actionError" class="detail-state">
      <h3>{{ activeActionLabel || '跨系统动作执行' }}</h3>
      <p v-if="actionRunning">正在执行跨系统动作…</p>
      <p v-if="actionError" data-testid="action-error" class="run-error">{{ actionError }}</p>
      <template v-if="actionRun?.final_response">
        <p>{{ actionRun.final_response.summary }}</p>
        <TaskResultTable v-if="actionRun.final_response.outputs" :outputs="actionRun.final_response.outputs" />
      </template>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  confirmTaskSession, createPurchaseProgressRun, createTaskDetailRun, createTaskRun,
  createTaskSession, executeTaskAction, getTaskSession, sendTaskSessionMessage,
  submitTaskSessionInputs,
} from '../api/commandCenter'
import type { TaskActionInvocation, TaskRunView, TaskSessionView } from '../api/types'
import PurchaseProgress from './PurchaseProgress.vue'
import TaskInteractionRenderer from './TaskInteractionRenderer.vue'
import TaskResultTable from './TaskResultTable.vue'

const userRequest = ref('')
const running = ref(false)
const session = ref<TaskSessionView | null>(null)
const run = ref<TaskRunView | null>(null)
const legacyRunning = ref(false)
const detailRunning = ref(false)
const detailRun = ref<TaskRunView | null>(null)
const detailError = ref('')
const progressRunning = ref(false)
const progressRun = ref<TaskRunView | null>(null)
const progressError = ref('')
const actionRunning = ref(false)
const actionRun = ref<TaskRunView | null>(null)
const actionError = ref('')
const activeActionLabel = ref('')

const terminal = computed(() => ['succeeded', 'failed'].includes(run.value?.status || ''))
const canViewDetails = computed(() => run.value?.status === 'succeeded' && run.value.execution_mode === 'tool')
const canTrackProgress = computed(() => run.value?.status === 'succeeded' && run.value.execution_mode === 'tool')
const canUseLegacyFallback = computed(() => session.value?.next_interaction.type === 'result'
  && session.value.next_interaction.status === 'failed'
  && session.value.next_interaction.code === 'no_matching_published_skill')
const statusLabel = computed(() => ({
  matching: '正在理解任务', needs_input: '需要补充任务信息',
  needs_object_selection: '需要选择业务对象', executing: '正在执行 Skill',
  verifying: '正在核对业务结果', succeeded: '任务已完成', failed: '任务执行失败',
}[run.value?.status || 'matching']))

function resetSecondaryResults() {
  run.value = null
  detailRun.value = null
  detailError.value = ''
  progressRun.value = null
  progressError.value = ''
  actionRun.value = null
  actionError.value = ''
  activeActionLabel.value = ''
}

async function submit() {
  const goal = userRequest.value.trim()
  if (!goal) return void ElMessage.warning('请输入要完成的任务')
  running.value = true
  resetSecondaryResults()
  try { session.value = await createTaskSession({ goal }) }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '任务发起失败') }
  finally { running.value = false }
}

async function updateSession(operation: () => Promise<TaskSessionView>) {
  if (!session.value) return
  running.value = true
  try { session.value = await operation() }
  catch (error) {
    if (error instanceof Error && /version|conflict|409/i.test(error.message)) {
      session.value = await getTaskSession(session.value.session_id)
      ElMessage.warning('会话已更新，请根据最新状态继续')
    } else ElMessage.error(error instanceof Error ? error.message : '会话处理失败')
  } finally { running.value = false }
}

function submitMessage(message: string) {
  if (!session.value) return
  const current = session.value
  void updateSession(() => sendTaskSessionMessage(current.session_id, current.version, message))
}
function submitInputs(values: Record<string, unknown>) {
  if (!session.value) return
  const current = session.value
  void updateSession(() => submitTaskSessionInputs(current.session_id, current.version, values))
}
function submitConfirmation(payload: { plan_revision: number; plan_hash: string; confirmation_token: string; approved: boolean }) {
  if (!session.value) return
  const current = session.value
  void updateSession(() => confirmTaskSession(current.session_id, { version: current.version, ...payload }))
}

async function runLegacyQuery() {
  legacyRunning.value = true
  try { run.value = await createTaskRun(userRequest.value.trim()) }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '兼容查询发起失败') }
  finally { legacyRunning.value = false }
}

async function trackProgress(recordId: string) {
  if (!run.value) return
  progressRunning.value = true
  progressRun.value = null
  progressError.value = ''
  try { progressRun.value = await createPurchaseProgressRun(run.value.run_id, recordId) }
  catch (error) {
    progressError.value = error instanceof Error ? error.message : '采购进度追踪失败'
    ElMessage.error(progressError.value)
  } finally { progressRunning.value = false }
}

async function viewDetails(recordId: string) {
  if (!run.value) return
  detailRunning.value = true
  detailRun.value = null
  detailError.value = ''
  try { detailRun.value = await createTaskDetailRun(run.value.run_id, recordId) }
  catch (error) {
    detailError.value = error instanceof Error ? error.message : '详情查询失败'
    ElMessage.error(detailError.value)
  } finally { detailRunning.value = false }
}

async function executeAction({ action, record }: TaskActionInvocation) {
  if (!run.value) return
  activeActionLabel.value = action.label
  actionError.value = ''
  actionRun.value = null
  if (action.task_session_eligible) {
    running.value = true
    try {
      session.value = await createTaskSession({
        goal: `为所选业务对象执行${action.label}`,
        hint: {
          action_id: action.action_id, skill_id: action.skill_id,
          skill_version: action.skill_version, parent_run_id: run.value.run_id,
          selected_record_id: action.record_id, selected_object: record,
        },
      })
    } catch (error) { ElMessage.error(error instanceof Error ? error.message : '动作会话发起失败') }
    finally { running.value = false }
    return
  }
  actionRunning.value = true
  try {
    actionRun.value = await executeTaskAction(run.value.run_id, action.action_id, action.record_id)
    if (actionRun.value.status !== 'succeeded') actionError.value = actionRun.value.errors?.join('、') || '跨系统动作未执行成功'
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '跨系统动作执行失败'
    ElMessage.error(actionError.value)
  } finally { actionRunning.value = false }
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
.session-state, .run-state { border-top: 1px solid var(--border); min-width: 0; padding-top: 18px; }
.run-state-heading { align-items: center; display: flex; gap: 9px; }
.pulse { background: var(--signal); border-radius: 50%; box-shadow: 0 0 0 5px var(--signal-soft); height: 9px; width: 9px; }
.pulse.finished { background: var(--success); box-shadow: none; }
.run-state p { color: var(--muted); margin-bottom: 0; }
.run-error { color: var(--danger) !important; }
.detail-state, .progress-state { border-top: 1px solid var(--border); min-width: 0; padding-top: 18px; }
.detail-state h3 { font-size: 18px; margin: 0 0 10px; }
.detail-state > p, .progress-state > p { color: var(--muted); }
.detail-output { border-top: 1px dashed var(--border); margin-top: 14px; padding-top: 12px; }
.detail-output > strong { color: var(--muted); font: 700 12px var(--font-mono); }
@media (max-width: 760px) { .command-panel { grid-template-columns: 1fr; } }
</style>
