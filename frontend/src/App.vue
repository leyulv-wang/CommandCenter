<template>
  <el-config-provider>
    <div class="app-shell">
      <aside class="sidebar">
        <p class="eyebrow">Agent Form Center</p>
        <h1>配置化表单执行智能体</h1>
        <el-menu :default-active="activePage" @select="activePage = $event">
          <el-menu-item index="tasks">任务中心</el-menu-item>
          <el-menu-item index="demonstration">演示工作台</el-menu-item>
          <el-menu-item index="external">外部业务系统</el-menu-item>
          <el-menu-item index="ai-config">AI 生成配置</el-menu-item>
        </el-menu>
      </aside>

      <main class="content">
        <TaskCenterPage v-if="activePage === 'tasks'" />
        <DemonstrationWorkbenchPage v-else-if="activePage === 'demonstration'" />
        <ExternalSystemsPage v-else-if="activePage === 'external'" />
        <AiConfigGeneratorPage v-else />
      </main>
    </div>
  </el-config-provider>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import TaskCenterPage from './pages/TaskCenterPage.vue'
import AiConfigGeneratorPage from './pages/AiConfigGeneratorPage.vue'
import ExternalSystemsPage from './pages/ExternalSystemsPage.vue'
import DemonstrationWorkbenchPage from './pages/DemonstrationWorkbenchPage.vue'

const activePage = ref('tasks')
</script>
