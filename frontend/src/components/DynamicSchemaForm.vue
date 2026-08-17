<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { JsonSchema } from '../api/types'

const props = defineProps<{
  schema: JsonSchema
  modelValue: Record<string, unknown>
}>()
const emit = defineEmits<{
  submit: [values: Record<string, unknown>]
}>()

const cloneJson = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const values = reactive<Record<string, unknown>>(cloneJson(props.modelValue ?? {}))
const error = reactive({ message: '' })

const unsupported = computed(() => {
  const visit = (schema: JsonSchema | undefined): boolean => {
    if (!schema) return true
    if (schema.oneOf || schema.anyOf || schema.allOf || schema.$ref) return true
    if (schema.type === 'object') {
      return Object.values(schema.properties ?? {}).some(visit)
    }
    if (schema.type === 'array') return visit(schema.items)
    return !['string', 'number', 'integer', 'boolean'].includes(schema.type)
  }
  return props.schema.type !== 'object' || visit(props.schema)
})

const properties = computed(() => props.schema.properties ?? {})

function arrayValue(name: string): Array<Record<string, unknown>> {
  if (!Array.isArray(values[name])) values[name] = []
  return values[name] as Array<Record<string, unknown>>
}

function addArrayRow(name: string, schema: JsonSchema) {
  const item = schema.items
  if (item?.type === 'object') {
    arrayValue(name).push(
      Object.fromEntries(Object.keys(item.properties ?? {}).map((key) => [key, ''])),
    )
  } else {
    ;(values[name] as unknown[] | undefined ?? (values[name] = []) as unknown[]).push('')
  }
}

function removeArrayRow(name: string, index: number) {
  ;(values[name] as unknown[]).splice(index, 1)
}

function updateRoot(name: string, schema: JsonSchema, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  values[name] = coerce(target.value, schema)
}

function updateArrayField(name: string, index: number, field: string, schema: JsonSchema, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  arrayValue(name)[index][field] = coerce(target.value, schema)
}

function coerce(value: string, schema: JsonSchema): unknown {
  if (schema.type === 'number') return value === '' ? '' : Number(value)
  if (schema.type === 'integer') return value === '' ? '' : Number.parseInt(value, 10)
  if (schema.type === 'boolean') return value === 'true'
  return value
}

function submit() {
  error.message = ''
  for (const name of props.schema.required ?? []) {
    const value = values[name]
    if (value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) {
      error.message = `请填写 ${properties.value[name]?.title ?? name}`
      return
    }
  }
  emit('submit', cloneJson(values))
}
</script>

<template>
  <div v-if="unsupported" class="schema-error">
    当前表单结构暂不支持，请联系管理员完善 Skill Schema
  </div>
  <form v-else class="dynamic-schema-form" @submit.prevent="submit">
    <section v-for="(fieldSchema, name) in properties" :key="name" class="schema-field">
      <label>{{ fieldSchema.title ?? name }}</label>

      <template v-if="fieldSchema.type === 'array'">
        <div v-for="(row, index) in arrayValue(name)" :key="index" class="array-row">
          <template v-if="fieldSchema.items?.type === 'object'">
            <label v-for="(childSchema, childName) in fieldSchema.items.properties" :key="childName">
              {{ childSchema.title ?? childName }}
              <input
                :type="childSchema.type === 'number' || childSchema.type === 'integer' ? 'number' : childSchema.format === 'date' ? 'date' : 'text'"
                :data-path="`${name}.${index}.${childName}`"
                :value="row[childName]"
                @input="updateArrayField(name, index, childName, childSchema, $event)"
              />
            </label>
          </template>
          <button type="button" @click="removeArrayRow(name, index)">删除</button>
        </div>
        <button type="button" :data-testid="`add-${name}-row`" @click="addArrayRow(name, fieldSchema)">
          添加一项
        </button>
      </template>

      <select v-else-if="fieldSchema.enum" :value="values[name]" @change="updateRoot(name, fieldSchema, $event)">
        <option value="">请选择</option>
        <option v-for="option in fieldSchema.enum" :key="String(option)" :value="String(option)">{{ option }}</option>
      </select>
      <input
        v-else
        :data-path="name"
        :type="fieldSchema.type === 'number' || fieldSchema.type === 'integer' ? 'number' : fieldSchema.format === 'date' ? 'date' : fieldSchema.format === 'date-time' ? 'datetime-local' : fieldSchema.type === 'boolean' ? 'checkbox' : 'text'"
        :value="values[name] as string | number | undefined"
        @input="updateRoot(name, fieldSchema, $event)"
      />
    </section>
    <p v-if="error.message" class="form-error">{{ error.message }}</p>
    <button type="submit">提交信息</button>
  </form>
</template>
