<template>
  <dl v-if="entries.length" class="key-value-list">
    <div v-for="([key, value]) in entries" :key="key" class="key-value-row">
      <dt>{{ key }}</dt>
      <dd>{{ displayValue(value) }}</dd>
    </div>
  </dl>
  <span v-else class="empty-value">{{ emptyText }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values?: Record<string, unknown> | null
    emptyText?: string
  }>(),
  { emptyText: '-' },
)

const entries = computed(() => Object.entries(props.values ?? {}))

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<style scoped>
.key-value-list {
  display: grid;
  gap: 5px;
  margin: 0;
}

.key-value-row {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(72px, 0.45fr) minmax(90px, 1fr);
}

dt {
  color: #64748b;
  overflow-wrap: anywhere;
}

dd {
  color: #172033;
  margin: 0;
  overflow-wrap: anywhere;
}

.empty-value {
  color: #94a3b8;
}
</style>
