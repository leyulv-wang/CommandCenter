import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DynamicSchemaForm from '../DynamicSchemaForm.vue'


describe('DynamicSchemaForm', () => {
  it('submits an object array as one structured input payload', async () => {
    const wrapper = mount(DynamicSchemaForm, {
      props: {
        schema: {
          type: 'object',
          required: ['items'],
          properties: {
            items: {
              type: 'array',
              items: {
                type: 'object',
                required: ['category', 'amount'],
                properties: {
                  category: { type: 'string', title: '类别' },
                  amount: { type: 'number', title: '金额' },
                },
              },
            },
          },
        },
        modelValue: {},
      },
    })

    await wrapper.get('[data-testid="add-items-row"]').trigger('click')
    await wrapper.get('[data-path="items.0.category"]').setValue('差旅')
    await wrapper.get('[data-path="items.0.amount"]').setValue('88')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toEqual({
      items: [{ category: '差旅', amount: 88 }],
    })
  })

  it('shows a visible error for unsupported schema composition', () => {
    const wrapper = mount(DynamicSchemaForm, {
      props: {
        schema: { type: 'object', oneOf: [{ type: 'object' }] },
        modelValue: {},
      },
    })

    expect(wrapper.text()).toContain('当前表单结构暂不支持')
  })
})
