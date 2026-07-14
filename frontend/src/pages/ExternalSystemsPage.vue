<template>
  <section class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">External Systems</p>
        <h2>外部业务系统</h2>
      </div>
      <div class="header-tags">
        <el-button
          v-if="isDemoSystem"
          type="warning"
          plain
          :loading="resetting"
          @click="resetDemo"
        >
          重置当前系统演示
        </el-button>
        <el-button
          :disabled="selectedSystem?.role !== 'connected'"
          :loading="loadingData"
          @click="refreshData"
        >
          刷新数据
        </el-button>
      </div>
    </div>

    <div class="two-column">
      <el-card class="panel" shadow="never">
        <template #header>接入对象</template>
        <el-skeleton v-if="loadingSystems" :rows="3" animated />
        <el-empty v-else-if="systems.length === 0" description="暂无外部系统" />
        <el-menu v-else :default-active="selectedSystemCode" @select="selectSystem">
          <div v-if="connectedSystems.length > 0" class="menu-group-title">已接入系统</div>
          <el-menu-item v-for="system in connectedSystems" :key="system.system_code" :index="system.system_code">
            <span>{{ system.system_name }}</span>
            <el-tag class="form-mode-tag" size="small" type="success">已接入</el-tag>
          </el-menu-item>

          <div v-if="onboardingSystems.length > 0" class="menu-group-title">快速接入演示</div>
          <el-menu-item v-for="system in onboardingSystems" :key="system.system_code" :index="system.system_code">
            <span>{{ onboardingDisplayName(system) }}</span>
            <el-tag class="form-mode-tag" size="small" type="warning">
              接口说明
            </el-tag>
          </el-menu-item>
        </el-menu>
      </el-card>

      <div class="stack">
        <el-card class="panel" shadow="never">
          <template #header>
            <div class="card-header-row">
              <span>{{ selectedTitle }}</span>
              <el-tag v-if="selectedSystem" :type="selectedSystem.role === 'connected' ? 'success' : 'warning'">
                {{ selectedSystem.role === 'connected' ? '已接入系统' : '接口说明样例' }}
              </el-tag>
            </div>
          </template>

          <el-alert
            v-if="selectedSystem?.role === 'connected'"
            title="这个系统用于演示：中控可以读取旧数据，也可以提交新表单到外部系统。"
            type="success"
            show-icon
            :closable="false"
            class="page-alert"
          />
          <el-alert
            v-else-if="selectedSystem?.role === 'onboarding'"
            title="这不是已经接入的系统，只是一份客户接口说明样例。复制到 AI 配置页，生成并保存配置后，才算接入中控。"
            type="warning"
            show-icon
            :closable="false"
            class="page-alert"
          />

          <el-tabs v-if="selectedSystem?.role === 'connected'" v-model="activeDataTab">
            <el-tab-pane :label="`全部任务 ${tasks.length}`" name="tasks">
              <el-table v-loading="loadingData" :data="tasks" border empty-text="暂无任务数据">
                <el-table-column prop="task_id" label="任务编号" min-width="170" />
                <el-table-column prop="title" label="任务标题" min-width="180" />
                <el-table-column label="状态" width="100">
                  <template #default="{ row }">
                    <el-tag :type="row.status === 'completed' ? 'success' : 'warning'">
                      {{ row.status === 'completed' ? '已完成' : '待处理' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="assignee_id" label="处理人" width="110" />
                <el-table-column prop="created_at" label="创建时间" min-width="170" />
                <el-table-column prop="completed_at" label="完成时间" min-width="170">
                  <template #default="{ row }">{{ row.completed_at || '-' }}</template>
                </el-table-column>
                <el-table-column label="任务内容" min-width="240">
                  <template #default="{ row }">
                    <KeyValueList :values="row.content" />
                  </template>
                </el-table-column>
                <el-table-column label="处理结果" min-width="220">
                  <template #default="{ row }">
                    <KeyValueList :values="row.result_values" empty-text="尚未处理" />
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane :label="`全部申请 ${submissions.length}`" name="submissions">
              <el-table
                v-loading="loadingData"
                :data="submissions"
                border
                empty-text="暂无申请数据"
              >
                <el-table-column prop="ticket_id" label="单据号" min-width="170" />
                <el-table-column prop="operator_id" label="操作人" width="110" />
                <el-table-column label="来源" width="100">
                  <template #default="{ row }">
                    <el-tag :type="row.source === 'seed' ? 'info' : 'success'">
                      {{ row.source === 'seed' ? '历史数据' : '中控提交' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="接口类型" width="120">
                  <template #default="{ row }">
                    <el-tag effect="plain">
                      {{ row.endpoint_type === 'workflow' ? '流程类' : '独立 URL' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="fd_template_id" label="流程模板" min-width="160">
                  <template #default="{ row }">{{ row.fd_template_id || '-' }}</template>
                </el-table-column>
                <el-table-column prop="created_at" label="创建时间" min-width="170" />
                <el-table-column label="表单字段" min-width="280">
                  <template #default="{ row }">
                    <KeyValueList :values="row.form_values" />
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-card>

        <el-card v-if="selectedSystem?.role === 'onboarding'" class="panel" shadow="never">
          <template #header>
            <div class="card-header-row">
              <span>客户提供的接口说明</span>
              <el-button size="small" :loading="loadingSpec" @click="loadInterfaceSpec">读取说明</el-button>
            </div>
          </template>
          <el-empty v-if="!interfaceSpec" description="点击读取说明后，复制到 AI 生成配置页面" />
          <pre v-else class="plain-preview">{{ interfaceSpec.description }}</pre>
        </el-card>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import KeyValueList from '../components/KeyValueList.vue'
import {
  getExternalSystemData,
  getExternalInterfaceSpec,
  listExternalSystems,
  resetDemoSystem,
} from '../api/externalSystems'
import type { ExternalInterfaceSpec, ExternalSystem, ExternalSystemDataResponse } from '../api/types'

const systems = ref<ExternalSystem[]>([])
const selectedSystemCode = ref('')
const systemData = ref<ExternalSystemDataResponse | null>(null)
const interfaceSpec = ref<ExternalInterfaceSpec | null>(null)
const loadingSystems = ref(false)
const loadingData = ref(false)
const loadingSpec = ref(false)
const resetting = ref(false)
const activeDataTab = ref('tasks')

const selectedSystem = computed(() =>
  systems.value.find((system) => system.system_code === selectedSystemCode.value),
)
const isDemoSystem = computed(
  () => ['connected_system', 'onboarding_system'].includes(selectedSystem.value?.system_code ?? ''),
)
const connectedSystems = computed(() => systems.value.filter((system) => system.role === 'connected'))
const onboardingSystems = computed(() => systems.value.filter((system) => system.role === 'onboarding'))
const tasks = computed(() => systemData.value?.tasks ?? [])
const submissions = computed(() => systemData.value?.submissions ?? [])
const selectedTitle = computed(() => {
  if (!selectedSystem.value) return '请选择对象'
  return selectedSystem.value.role === 'onboarding'
    ? onboardingDisplayName(selectedSystem.value)
    : selectedSystem.value.system_name
})

onMounted(async () => {
  loadingSystems.value = true
  try {
    await loadSystems()
    selectedSystemCode.value = systems.value[0]?.system_code ?? ''
    await refreshData()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '外部系统加载失败')
  } finally {
    loadingSystems.value = false
  }
})

async function loadSystems() {
  systems.value = await listExternalSystems()
}

async function selectSystem(systemCode: string) {
  selectedSystemCode.value = systemCode
  systemData.value = null
  interfaceSpec.value = null
  activeDataTab.value = 'tasks'
  await refreshData()
}

async function refreshData() {
  if (!selectedSystemCode.value || selectedSystem.value?.role !== 'connected') {
    systemData.value = null
    return
  }
  loadingData.value = true
  try {
    systemData.value = await getExternalSystemData(selectedSystemCode.value)
  } catch (error) {
    systemData.value = null
    ElMessage.error(error instanceof Error ? error.message : '业务数据读取失败')
  } finally {
    loadingData.value = false
  }
}

async function loadInterfaceSpec() {
  if (!selectedSystemCode.value) return
  loadingSpec.value = true
  try {
    interfaceSpec.value = await getExternalInterfaceSpec(selectedSystemCode.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '接口说明读取失败')
  } finally {
    loadingSpec.value = false
  }
}

async function resetDemo() {
  resetting.value = true
  try {
    if (!selectedSystem.value) return
    const systemCode = selectedSystem.value.system_code
    await resetDemoSystem(systemCode)
    interfaceSpec.value = null
    await loadSystems()
    selectedSystemCode.value = systemCode
    await refreshData()
    ElMessage.success('快速接入演示已重置')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重置失败')
  } finally {
    resetting.value = false
  }
}

function onboardingDisplayName(system: ExternalSystem) {
  return system.system_name.replace('待接入', '').replace('系统', '接口说明样例')
}
</script>

<style scoped>
.card-header-row {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.page-alert {
  margin-bottom: 16px;
}

.menu-group-title {
  color: #64748b;
  font-size: 12px;
  line-height: 1;
  padding: 16px 20px 8px;
}

.plain-preview {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  line-height: 1.7;
  margin: 0;
  padding: 14px;
  white-space: pre-wrap;
}

:deep(.el-table .cell) {
  line-height: 1.5;
}
</style>
