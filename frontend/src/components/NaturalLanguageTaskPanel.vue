<template>
  <section class="command-panel">
    <div class="command-copy">
      <p class="command-kicker">直接交给中控</p>
      <h3>描述要完成的工作</h3>
      <p>例如：处理签字笔库存不足任务</p>
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
      <el-button type="primary" :loading="running" @click="submit">执行任务</el-button>
    </div>

    <div v-if="run" class="run-state">
      <div class="run-state-heading">
        <span class="pulse" :class="{ finished: terminal }"></span>
        <strong>{{ statusLabel }}</strong>
      </div>
      <p v-if="run.final_response">{{ run.final_response.summary }}</p>
      <p v-else-if="run.errors?.length" class="run-error">{{ run.errors.join('；') }}</p>

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
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createTaskRun, selectTaskObject } from '../api/commandCenter'
import type { TaskRunView } from '../api/types'

const userRequest = ref('')
const running = ref(false)
const run = ref<TaskRunView | null>(null)
const terminal = computed(() => ['succeeded', 'failed'].includes(run.value?.status || ''))
const statusLabel = computed(() => ({
  matching: '正在理解任务',
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
  try {
    run.value = await createTaskRun(userRequest.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '任务发起失败')
  } finally {
    running.value = false
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
.command-panel { background: #14213d; color: #fff; display: grid; gap: 18px; grid-template-columns: 260px 1fr; margin-bottom: 22px; padding: 24px; }
.command-copy h3 { font-size: 21px; margin: 6px 0; }
.command-copy p { color: #b9c5d6; line-height: 1.5; margin: 0; }
.command-kicker { color: #67d4e5 !important; font: 700 12px Bahnschrift, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.command-input { align-items: stretch; display: flex; gap: 10px; }
.command-input :deep(textarea) { border: 0; border-radius: 2px; }
.run-state { border-top: 1px solid #52617a; grid-column: 1 / -1; padding-top: 16px; }
.run-state-heading { align-items: center; display: flex; gap: 9px; }
.pulse { background: #67d4e5; border-radius: 50%; box-shadow: 0 0 0 5px rgb(103 212 229 / 18%); height: 9px; width: 9px; }
.pulse.finished { background: #4ade80; box-shadow: none; }
.run-state p { color: #d7e0ec; margin-bottom: 0; }
.run-error { color: #fecaca !important; }
.object-choice { display: grid; gap: 8px; margin-top: 14px; }
.object-choice button { background: #fff; border: 0; color: #14213d; cursor: pointer; display: flex; justify-content: space-between; padding: 12px 14px; text-align: left; }
.object-choice small { color: #64748b; }
@media (max-width: 760px) {
  .command-panel { grid-template-columns: 1fr; }
  .command-input { flex-direction: column; }
}
</style>
