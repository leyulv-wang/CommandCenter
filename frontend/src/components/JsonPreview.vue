<template>
  <pre class="json-preview">{{ formatted }}</pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  value: unknown
  emptyText?: string
}>()

const formatted = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') {
    return props.emptyText ?? '暂无数据'
  }
  if (typeof props.value === 'string') {
    return props.value
  }
  return JSON.stringify(props.value, null, 2)
})
</script>
