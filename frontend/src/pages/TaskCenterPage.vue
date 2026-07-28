<template>
  <section class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">Task Center</p>
        <h2>任务中心</h2>
      </div>
      <el-tag>演示用户：{{ operatorId }}</el-tag>
    </div>

    <NaturalLanguageTaskPanel />

    <el-skeleton v-if="systemsLoading" :rows="5" animated />
    <el-empty
      v-else-if="connectedSystems.length === 0"
      description="暂无已接入业务系统，请先在 AI 生成配置中完成系统接入"
    />
    <el-tabs v-else v-model="activeTab" class="task-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="发起申请" name="application">
        <div class="two-column">
          <el-card class="panel" shadow="never">
            <template #header>选择申请</template>
            <el-form label-position="top">
              <el-form-item label="业务系统">
                <el-select
                  v-model="selectedSystemCode"
                  placeholder="请选择业务系统"
                  @change="loadStartableForms"
                >
                  <el-option
                    v-for="system in connectedSystems"
                    :key="system.system_code"
                    :label="system.system_name"
                    :value="system.system_code"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="申请表单">
                <el-select
                  v-model="selectedApplicationFormCode"
                  placeholder="请选择申请表单"
                  :loading="applicationFormsLoading"
                >
                  <el-option
                    v-for="form in applicationForms"
                    :key="form.form_code"
                    :label="form.form_name"
                    :value="form.form_code"
                  />
                </el-select>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card class="panel" shadow="never">
            <template #header>{{ selectedApplicationForm?.form_name ?? '填写申请' }}</template>
            <DynamicForm
              v-if="selectedApplicationForm"
              :template="selectedApplicationForm"
              :operator-id="operatorId"
              :show-operator="false"
              :submitting="applicationSubmitting"
              submit-text="提交申请"
              @submit="handleApplicationSubmit"
            />
            <el-empty v-else description="请选择业务系统和申请表单" />
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="`待办任务（${pendingTasks.length}）`" name="pending">
        <div class="tab-toolbar">
          <el-button :loading="pendingLoading" @click="loadPendingTasks">刷新待办</el-button>
        </div>
        <div class="two-column">
          <el-card class="panel task-list" shadow="never">
            <template #header>待办任务</template>
            <el-skeleton v-if="pendingLoading" :rows="4" animated />
            <el-empty v-else-if="pendingTasks.length === 0" description="暂无待办任务" />
            <el-menu v-else :default-active="selectedPendingTaskId" @select="selectPendingTask">
              <el-menu-item
                v-for="task in pendingTasks"
                :key="task.task_id"
                :index="task.task_id"
              >
                <TaskMenuItem :task="task" />
              </el-menu-item>
            </el-menu>
          </el-card>

          <div class="stack">
            <TaskDetailCard :task="selectedPendingTask" />
            <el-card class="panel" shadow="never">
              <template #header>处理结果</template>
              <el-skeleton v-if="taskFormLoading" :rows="3" animated />
              <DynamicForm
                v-else-if="selectedPendingTask && taskForm"
                :template="taskForm"
                :operator-id="operatorId"
                :show-operator="false"
                :submitting="taskSubmitting"
                submit-text="提交处理结果"
                @submit="handleTaskComplete"
              />
              <el-empty v-else description="请选择任务" />
            </el-card>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="`已完成（${completedTasks.length}）`" name="completed">
        <div class="tab-toolbar">
          <el-button :loading="completedLoading" @click="loadCompletedTasks">刷新已完成</el-button>
        </div>
        <div class="two-column">
          <el-card class="panel task-list" shadow="never">
            <template #header>已完成任务</template>
            <el-skeleton v-if="completedLoading" :rows="4" animated />
            <el-empty v-else-if="completedTasks.length === 0" description="暂无已完成任务" />
            <el-menu
              v-else
              :default-active="selectedCompletedTaskId"
              @select="selectedCompletedTaskId = $event"
            >
              <el-menu-item
                v-for="task in completedTasks"
                :key="task.task_id"
                :index="task.task_id"
              >
                <TaskMenuItem :task="task" />
              </el-menu-item>
            </el-menu>
          </el-card>

          <div class="stack">
            <TaskDetailCard :task="selectedCompletedTask" />
            <el-card class="panel" shadow="never">
              <template #header>处理记录</template>
              <template v-if="selectedCompletedTask">
                <el-descriptions :column="1" border>
                  <el-descriptions-item label="完成时间">
                    {{ selectedCompletedTask.completed_at || '-' }}
                  </el-descriptions-item>
                  <el-descriptions-item
                    v-for="(value, key) in selectedCompletedTask.result_values || {}"
                    :key="key"
                    :label="String(key)"
                  >
                    {{ formatValue(value) }}
                  </el-descriptions-item>
                </el-descriptions>
              </template>
              <el-empty v-else description="请选择已完成任务" />
            </el-card>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, type PropType } from 'vue'
import { ElCard, ElDescriptions, ElDescriptionsItem, ElEmpty, ElMessage, ElTag } from 'element-plus'
import { listExternalSystemForms, listExternalSystems } from '../api/externalSystems'
import { getForm, submitForm } from '../api/forms'
import { completeTask, listTasks } from '../api/tasks'
import type {
  ExternalSystem,
  FormTemplate,
  SubmitFormRequest,
  TaskItem,
} from '../api/types'
import DynamicForm from '../components/DynamicForm.vue'
import NaturalLanguageTaskPanel from '../components/NaturalLanguageTaskPanel.vue'

const operatorId = 'u001'
const activeTab = ref('application')

const connectedSystems = ref<ExternalSystem[]>([])
const systemsLoading = ref(false)
const selectedSystemCode = ref('')
const applicationForms = ref<FormTemplate[]>([])
const selectedApplicationFormCode = ref('')
const applicationFormsLoading = ref(false)
const applicationSubmitting = ref(false)

const pendingTasks = ref<TaskItem[]>([])
const selectedPendingTaskId = ref('')
const pendingLoading = ref(false)
const taskForm = ref<FormTemplate | null>(null)
const taskFormLoading = ref(false)
const taskSubmitting = ref(false)

const completedTasks = ref<TaskItem[]>([])
const selectedCompletedTaskId = ref('')
const completedLoading = ref(false)

const selectedApplicationForm = computed(() =>
  applicationForms.value.find((form) => form.form_code === selectedApplicationFormCode.value),
)
const selectedPendingTask = computed(() =>
  pendingTasks.value.find((task) => task.task_id === selectedPendingTaskId.value),
)
const selectedCompletedTask = computed(() =>
  completedTasks.value.find((task) => task.task_id === selectedCompletedTaskId.value),
)

const TaskMenuItem = defineComponent({
  props: { task: { type: Object as PropType<TaskItem>, required: true } },
  setup(props) {
    return () => h('div', { class: 'task-menu-item' }, [
      h('span', props.task.title),
      h('small', props.task.source_system_name),
    ])
  },
})

const TaskDetailCard = defineComponent({
  props: { task: { type: Object as PropType<TaskItem | undefined>, default: undefined } },
  setup(props) {
    return () => {
      const task = props.task
      return h(ElCard, { class: 'panel', shadow: 'never' }, {
        header: () => task?.title ?? '请选择任务',
        default: () => task
          ? h(ElDescriptions, { column: 1, border: true }, () => [
              h(ElDescriptionsItem, { label: '来源系统' }, () => task.source_system_name),
              h(ElDescriptionsItem, { label: '任务编号' }, () => task.task_id),
              h(ElDescriptionsItem, { label: '创建时间' }, () => task.created_at),
              ...Object.entries(task.content).map(([key, value]) =>
                h(ElDescriptionsItem, { label: key }, () => formatValue(value)),
              ),
            ])
          : h(ElEmpty, { description: '请选择左侧任务' }),
      })
    }
  },
})

onMounted(async () => {
  await Promise.all([loadSystems(), loadPendingTasks(), loadCompletedTasks()])
})

async function loadSystems() {
  systemsLoading.value = true
  try {
    connectedSystems.value = (await listExternalSystems()).filter(
      (system) => system.role === 'connected',
    )
    selectedSystemCode.value = connectedSystems.value[0]?.system_code ?? ''
    await loadStartableForms()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '业务系统加载失败')
  } finally {
    systemsLoading.value = false
  }
}

async function loadStartableForms() {
  applicationForms.value = []
  selectedApplicationFormCode.value = ''
  if (!selectedSystemCode.value) return
  applicationFormsLoading.value = true
  try {
    applicationForms.value = await listExternalSystemForms(selectedSystemCode.value)
    selectedApplicationFormCode.value = applicationForms.value[0]?.form_code ?? ''
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '申请表单加载失败')
  } finally {
    applicationFormsLoading.value = false
  }
}

async function handleApplicationSubmit(payload: SubmitFormRequest) {
  if (!selectedApplicationForm.value) return
  applicationSubmitting.value = true
  try {
    const result = await submitForm(selectedApplicationForm.value.form_code, payload)
    if (result.ok === false) throw new Error(String(result.error || '外部系统提交失败'))
    ElMessage.success('申请提交成功')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '申请提交失败')
  } finally {
    applicationSubmitting.value = false
  }
}

async function loadPendingTasks() {
  pendingLoading.value = true
  try {
    pendingTasks.value = (await listTasks(operatorId, 'pending')).items
    if (!pendingTasks.value.some((task) => task.task_id === selectedPendingTaskId.value)) {
      selectedPendingTaskId.value = pendingTasks.value[0]?.task_id ?? ''
    }
    await loadTaskForm()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '待办任务加载失败')
  } finally {
    pendingLoading.value = false
  }
}

async function selectPendingTask(taskId: string) {
  selectedPendingTaskId.value = taskId
  await loadTaskForm()
}

async function loadTaskForm() {
  if (!selectedPendingTask.value) {
    taskForm.value = null
    return
  }
  taskFormLoading.value = true
  try {
    taskForm.value = await getForm(selectedPendingTask.value.form_code)
  } catch (error) {
    taskForm.value = null
    ElMessage.error(error instanceof Error ? error.message : '任务处理表单加载失败')
  } finally {
    taskFormLoading.value = false
  }
}

async function handleTaskComplete(payload: SubmitFormRequest) {
  if (!selectedPendingTask.value) return
  taskSubmitting.value = true
  try {
    await completeTask(
      selectedPendingTask.value.source_system_code,
      selectedPendingTask.value.task_id,
      payload,
    )
    ElMessage.success('任务处理完成')
    await Promise.all([loadPendingTasks(), loadCompletedTasks()])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '任务处理失败')
  } finally {
    taskSubmitting.value = false
  }
}

async function loadCompletedTasks() {
  completedLoading.value = true
  try {
    completedTasks.value = (await listTasks(operatorId, 'completed')).items
    if (!completedTasks.value.some((task) => task.task_id === selectedCompletedTaskId.value)) {
      selectedCompletedTaskId.value = completedTasks.value[0]?.task_id ?? ''
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '已完成任务加载失败')
  } finally {
    completedLoading.value = false
  }
}

async function handleTabChange(tabName: string | number) {
  if (tabName === 'pending') await loadPendingTasks()
  if (tabName === 'completed') await loadCompletedTasks()
}

function formatValue(value: unknown) {
  return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
}
</script>

<style scoped>
.task-tabs {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0 18px 18px;
}

.tab-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 14px;
}

.task-menu-item {
  display: flex;
  flex-direction: column;
  line-height: 1.45;
  min-width: 0;
  padding: 7px 0;
}

.task-menu-item span,
.task-menu-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-menu-item small {
  color: #909399;
}

.task-list :deep(.el-menu-item) {
  height: auto;
}

:deep(.el-select) {
  width: 100%;
}
</style>
