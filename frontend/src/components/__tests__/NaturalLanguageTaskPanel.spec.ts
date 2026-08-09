import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NaturalLanguageTaskPanel from '../NaturalLanguageTaskPanel.vue'

const api = vi.hoisted(() => ({
  createTaskRun: vi.fn(),
  selectTaskObject: vi.fn(),
}))

vi.mock('../../api/commandCenter', () => api)

describe('NaturalLanguageTaskPanel', () => {
  beforeEach(() => {
    api.createTaskRun.mockReset().mockResolvedValue({
      run_id: 'run-1',
      user_request: '查询采购申请列表',
      status: 'succeeded',
      final_response: {
        summary: '查询完成',
        outputs: { query: { result: { records: [{ id: 'A-1' }] } } },
      },
    })
  })

  it('submits natural language to the existing task-run API and shows the result', async () => {
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })

    expect(wrapper.text()).toContain('输入任务')
    expect(wrapper.text()).toContain('交给中控执行')
    await wrapper.get('textarea').setValue('查询采购申请列表')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(api.createTaskRun).toHaveBeenCalledWith('查询采购申请列表')
    expect(wrapper.text()).toContain('任务已完成')
    expect(wrapper.text()).toContain('查询完成')
    expect(wrapper.get('[data-testid="structured-output"]').text()).toContain('A-1')
  })
})
