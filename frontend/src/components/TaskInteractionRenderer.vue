<script setup lang="ts">
import { reactive } from 'vue'
import DynamicSchemaForm from './DynamicSchemaForm.vue'
import type { TaskSessionView } from '../api/types'

const props = defineProps<{ session: TaskSessionView }>()
const emit = defineEmits<{
  'submit-message': [message: string]
  'submit-inputs': [values: Record<string, unknown>]
  'submit-selection': [values: Record<string, unknown>]
  confirm: [payload: { plan_revision: number; plan_hash: string; confirmation_token: string; approved: boolean }]
}>()

const answer = reactive<Record<string, unknown>>({})

function confirmation(approved: boolean) {
  const interaction = props.session.next_interaction
  if (interaction.type !== 'confirmation') return
  emit('confirm', {
    plan_revision: interaction.plan_revision,
    plan_hash: interaction.plan_hash,
    confirmation_token: interaction.confirmation_token,
    approved,
  })
}
</script>

<template>
  <section class="task-interaction">
    <p v-if="session.next_interaction.type === 'message'">{{ session.next_interaction.message }}</p>

    <form
      v-else-if="session.next_interaction.type === 'question'"
      @submit.prevent="emit('submit-inputs', { ...answer })"
    >
      <p>{{ session.next_interaction.prompt }}</p>
      <label v-for="field in session.next_interaction.field_names" :key="field">
        {{ field }}
        <input v-model="answer[field]" :data-path="field" />
      </label>
      <button type="submit">继续</button>
    </form>

    <div v-else-if="session.next_interaction.type === 'selection'">
      <p>{{ session.next_interaction.prompt }}</p>
      <button
        v-for="option in session.next_interaction.options"
        :key="option.value"
        type="button"
        @click="emit('submit-selection', { [session.next_interaction.field_name]: option.value })"
      >
        {{ option.label }}
      </button>
    </div>

    <DynamicSchemaForm
      v-else-if="session.next_interaction.type === 'form'"
      :schema="session.next_interaction.schema"
      :model-value="session.next_interaction.values"
      @submit="emit('submit-inputs', $event)"
    />

    <div v-else-if="session.next_interaction.type === 'confirmation'">
      <h3>{{ session.next_interaction.title }}</h3>
      <p data-testid="confirmation-summary">{{ session.next_interaction.summary }}</p>
      <p>系统：{{ session.next_interaction.systems.join('、') }}</p>
      <p>对象：{{ session.next_interaction.target_objects.join('、') }}</p>
      <article v-for="step in session.next_interaction.write_steps" :key="step.step_id" data-testid="write-step">
        <strong>{{ step.name }}</strong>
        <span>{{ step.system }}</span>
        <pre>{{ JSON.stringify(step.arguments, null, 2) }}</pre>
      </article>
      <button data-testid="approve-plan" type="button" @click="confirmation(true)">确认执行</button>
      <button data-testid="decline-plan" type="button" @click="confirmation(false)">取消</button>
    </div>

    <div v-else-if="session.next_interaction.type === 'result'">
      <h3>{{ session.next_interaction.status }}</h3>
      <p>{{ session.next_interaction.summary }}</p>
      <ul>
        <li v-for="step in session.next_interaction.steps" :key="step.step_id">
          {{ step.step_id }}：{{ step.status }} {{ step.summary }}
        </li>
      </ul>
    </div>
  </section>
</template>
