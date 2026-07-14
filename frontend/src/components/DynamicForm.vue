<template>
  <el-form label-position="top" class="dynamic-form" @submit.prevent>
    <el-form-item v-if="showOperator" label="操作人 ID" required>
      <el-input v-model="operatorId" />
    </el-form-item>

    <template v-for="field in template.fields" :key="field.key">
      <fieldset v-if="field.type === 'list'" class="list-field">
        <legend>{{ field.label }} <span v-if="field.required" class="required">*</span></legend>
        <div v-for="(row, rowIndex) in listValues(field.key)" :key="rowIndex" class="list-row">
          <el-form-item
            v-for="itemField in field.item_fields"
            :key="itemField.key"
            :label="itemField.label"
            :required="itemField.required"
          >
            <el-input v-model="row[itemField.key]" />
          </el-form-item>
          <el-button type="danger" plain @click="removeListRow(field.key, rowIndex)">删除</el-button>
        </div>
        <el-button @click="addListRow(field)">添加一行</el-button>
      </fieldset>

      <el-form-item v-else :label="field.label" :required="field.required">
        <el-input-number
          v-if="field.type === 'number'"
          v-model="formValues[field.key]"
          :min="0"
          controls-position="right"
        />
        <el-input
          v-else-if="field.type === 'textarea'"
          v-model="formValues[field.key]"
          type="textarea"
          :rows="4"
        />
        <el-date-picker
          v-else-if="field.type === 'datetime'"
          v-model="formValues[field.key]"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
        />
        <el-input v-else v-model="formValues[field.key]" />
      </el-form-item>
    </template>

    <div class="form-actions">
      <el-button type="primary" :loading="submitting" @click="submit">{{ submitButtonText }}</el-button>
      <el-button @click="reset">重置</el-button>
    </div>
  </el-form>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormField, FormTemplate } from '../api/types'

const props = withDefaults(defineProps<{
  template: FormTemplate
  submitting?: boolean
  operatorId?: string
  showOperator?: boolean
  submitText?: string
}>(), {
  operatorId: 'demo-user-001',
  showOperator: true,
  submitText: '',
})

const emit = defineEmits<{
  submit: [payload: { operator_id: string; values: Record<string, unknown> }]
}>()

const operatorId = ref(props.operatorId)
const formValues = reactive<Record<string, unknown>>({})
const submitButtonText = computed(() =>
  props.submitText
  || (props.template.endpoint.submit_mode === 'http' ? '提交到真实接口' : '提交到模拟接口'),
)

watch(
  () => props.operatorId,
  (value) => {
    operatorId.value = value
  },
)

watch(
  () => props.template,
  () => reset(),
  { immediate: true },
)

function reset() {
  for (const key of Object.keys(formValues)) {
    delete formValues[key]
  }
  for (const field of props.template.fields) {
    if (field.type === 'number') {
      formValues[field.key] = 0
    } else if (field.type === 'list') {
      formValues[field.key] = [createListRow(field)]
    } else {
      formValues[field.key] = ''
    }
  }
}

function listValues(key: string): Record<string, string>[] {
  const value = formValues[key]
  if (!Array.isArray(value)) {
    formValues[key] = []
    return formValues[key] as Record<string, string>[]
  }
  return value as Record<string, string>[]
}

function createListRow(field: FormField): Record<string, string> {
  return Object.fromEntries(field.item_fields.map((itemField) => [itemField.key, '']))
}

function addListRow(field: FormField) {
  listValues(field.key).push(createListRow(field))
}

function removeListRow(key: string, index: number) {
  listValues(key).splice(index, 1)
}

function submit() {
  emit('submit', {
    operator_id: operatorId.value,
    values: JSON.parse(JSON.stringify(formValues)),
  })
}
</script>
