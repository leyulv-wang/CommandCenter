import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TaskInteractionRenderer from '../TaskInteractionRenderer.vue'
import type { TaskSessionView } from '../../api/types'


describe('TaskInteractionRenderer', () => {
  it('renders every write step before confirmation', () => {
    const session: TaskSessionView = {
      session_id: 'session-1',
      state: 'awaiting_confirmation',
      version: 4,
      goal: '创建报销',
      plan_revision: 1,
      plan_hash: 'a'.repeat(64),
      next_interaction: {
        type: 'confirmation',
        title: '确认提交',
        summary: '创建报销记录',
        plan_revision: 1,
        plan_hash: 'a'.repeat(64),
        confirmation_token: 'token'.repeat(8),
        systems: ['finance'],
        target_objects: ['expense-42'],
        write_steps: [
          {
            step_id: 'create',
            name: '创建记录',
            system: 'finance',
            arguments: { body: { amount: 88 } },
          },
        ],
      },
    }

    const wrapper = mount(TaskInteractionRenderer, { props: { session } })

    expect(wrapper.get('[data-testid="confirmation-summary"]').text())
      .toContain('创建报销记录')
    expect(wrapper.findAll('[data-testid="write-step"]')).toHaveLength(1)
  })

  it('emits the complete bound confirmation identity', async () => {
    const session = {
      session_id: 'session-1', state: 'awaiting_confirmation', version: 4,
      goal: '创建报销', plan_revision: 1, plan_hash: 'a'.repeat(64),
      next_interaction: {
        type: 'confirmation', title: '确认', summary: '写入', plan_revision: 1,
        plan_hash: 'a'.repeat(64), confirmation_token: 'token'.repeat(8),
        systems: ['finance'], target_objects: ['expense-42'],
        write_steps: [{ step_id: 'create', name: '创建', system: 'finance', arguments: {} }],
      },
    } as TaskSessionView
    const wrapper = mount(TaskInteractionRenderer, { props: { session } })

    await wrapper.get('[data-testid="approve-plan"]').trigger('click')

    expect(wrapper.emitted('confirm')?.[0]?.[0]).toEqual({
      plan_revision: 1,
      plan_hash: 'a'.repeat(64),
      confirmation_token: 'token'.repeat(8),
      approved: true,
    })
  })
})
