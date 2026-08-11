<template>
  <section data-testid="purchase-progress" class="purchase-progress">
    <div class="progress-heading">
      <div>
        <p>采购进度</p>
        <h3>{{ progress.summary }}</h3>
      </div>
      <span :class="['progress-status', progress.status]">{{ statusLabel }}</span>
    </div>

    <ol class="progress-stages">
      <li
        v-for="stage in progress.stages"
        :key="stage.stage"
        data-testid="progress-stage"
        :class="stage.status"
      >
        <div class="stage-mark"></div>
        <div class="stage-content">
          <div class="stage-title">
            <strong>{{ stageLabel(stage.stage) }}</strong>
            <span>{{ stage.record_count }} 条记录</span>
          </div>
          <p>{{ stage.summary }}</p>
          <details v-if="stage.records.length">
            <summary>查看阶段数据</summary>
            <TaskResultTable :outputs="{ records: stage.records }" />
          </details>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PurchaseProgressResult, PurchaseProgressStage } from '../api/types'
import TaskResultTable from './TaskResultTable.vue'

const props = defineProps<{ progress: PurchaseProgressResult }>()

const statusLabel = computed(() => ({
  complete: '追踪完成',
  business_pending: '业务待推进',
  incomplete: '证据不完整',
  failed: '追踪失败',
}[props.progress.status]))

function stageLabel(stage: PurchaseProgressStage['stage']): string {
  return {
    application: '采购申请',
    order: '采购订单',
    receiving: '收货',
    warehouse: '入库',
  }[stage]
}
</script>

<style scoped>
.purchase-progress { border-top: 1px solid var(--border); display: grid; gap: 18px; margin-top: 18px; padding-top: 18px; }
.progress-heading { align-items: flex-start; display: flex; gap: 16px; justify-content: space-between; }
.progress-heading p { color: var(--signal); font: 700 12px var(--font-mono); margin: 0 0 5px; }
.progress-heading h3 { font-size: 18px; margin: 0; }
.progress-status { border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 12px; padding: 5px 9px; white-space: nowrap; }
.progress-status.complete { border-color: var(--success); color: var(--success); }
.progress-stages { display: grid; gap: 0; list-style: none; margin: 0; padding: 0; }
.progress-stages li { display: grid; gap: 12px; grid-template-columns: 14px 1fr; min-width: 0; padding-bottom: 18px; position: relative; }
.progress-stages li:not(:last-child)::before { background: var(--border); content: ''; height: 100%; left: 6px; position: absolute; top: 12px; width: 2px; }
.stage-mark { background: var(--surface); border: 2px solid var(--muted); border-radius: 50%; height: 10px; margin-top: 4px; width: 10px; z-index: 1; }
li.completed .stage-mark { background: var(--success); border-color: var(--success); }
li.failed .stage-mark { background: var(--danger); border-color: var(--danger); }
.stage-content { min-width: 0; }
.stage-title { align-items: center; display: flex; gap: 10px; justify-content: space-between; }
.stage-title span { color: var(--muted); font-size: 12px; }
.stage-content > p { color: var(--muted); margin: 5px 0 0; }
.stage-content details { margin-top: 9px; }
.stage-content summary { color: var(--signal); cursor: pointer; font-size: 13px; }
</style>
