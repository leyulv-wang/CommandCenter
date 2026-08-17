import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NaturalLanguageTaskPanel from '../NaturalLanguageTaskPanel.vue'

const api = vi.hoisted(() => ({
  createTaskRun: vi.fn(),
  createTaskDetailRun: vi.fn(),
  createPurchaseProgressRun: vi.fn(),
  executeTaskAction: vi.fn(),
  selectTaskObject: vi.fn(),
}))

vi.mock('../../api/commandCenter', () => api)

describe('NaturalLanguageTaskPanel', () => {
  beforeEach(() => {
    api.createTaskRun.mockReset().mockResolvedValue({
      run_id: 'run-1',
      user_request: '查询采购申请列表',
      status: 'succeeded',
      execution_mode: 'tool',
      available_actions: [
        {
          action_id: 'create-purchase-follow-up',
          label: '创建采购跟进任务',
          record_id: 'A-1',
          skill_id: 'skill-1',
          skill_version: 1,
          confirmation: 'required',
        },
      ],
      final_response: {
        summary: '查询完成',
        outputs: {
          query: { result: { records: [{ id: 'A-1', applyNo: 'CGSQ01' }] } },
        },
      },
    })
    api.createTaskDetailRun.mockReset().mockResolvedValue({
      run_id: 'detail-1',
      parent_run_id: 'run-1',
      user_request: '查看所选采购申请详情',
      status: 'succeeded',
      execution_mode: 'tool',
      final_response: {
        summary: '详情查询完成',
        outputs: { main: { result: { id: 'A-1', applyNo: 'CGSQ01' } } },
      },
    })
    api.createPurchaseProgressRun.mockReset().mockResolvedValue({
      run_id: 'progress-1',
      parent_run_id: 'run-1',
      user_request: '追踪所选采购申请进度',
      status: 'succeeded',
      final_response: {
        summary: '采购订单已生成并找到收货记录',
        progress: {
          status: 'complete',
          summary: '采购订单已生成并找到收货记录',
          stages: [
            {
              stage: 'application',
              status: 'completed',
              summary: '采购申请已找到',
              record_count: 1,
              records: [{ id: 'A-1', applyNo: 'CGSQ01' }],
              evidence_step_ids: [],
            },
            {
              stage: 'order',
              status: 'completed',
              summary: '采购订单已生成',
              record_count: 1,
              records: [{ orderNumber: 'CGDD01' }],
              evidence_step_ids: ['tool_01'],
            },
          ],
        },
      },
    })
    api.executeTaskAction.mockReset().mockResolvedValue({
      run_id: 'follow-up-1',
      parent_run_id: 'run-1',
      selected_record_id: 'A-1',
      status: 'succeeded',
      final_response: {
        summary: '已在采购业务系统创建跟进任务',
        outputs: { create: { follow_up_id: 'FOLLOW-UP-0001', mes_apply_no: 'CGSQ01' } },
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
    expect(wrapper.get('table').text()).toContain('A-1')
    expect(wrapper.get('details').attributes('open')).toBeUndefined()
  })

  it('keeps the list visible while loading and then renders selected details', async () => {
    let resolveDetail!: (value: unknown) => void
    api.createTaskDetailRun.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDetail = resolve
      }),
    )
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('查询采购申请列表')
    await wrapper.get('.command-input button').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="view-detail"]').trigger('click')

    expect(api.createTaskDetailRun).toHaveBeenCalledWith('run-1', 'A-1')
    expect(wrapper.get('table').text()).toContain('A-1')
    expect(wrapper.get('[data-testid="detail-loading"]').text()).toContain('正在查询详情')

    resolveDetail({
      run_id: 'detail-1',
      parent_run_id: 'run-1',
      user_request: '查看所选采购申请详情',
      status: 'succeeded',
      execution_mode: 'tool',
      final_response: {
        summary: '详情查询完成',
        outputs: { main: { result: { id: 'A-1', applyNo: 'CGSQ01' } } },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('所选采购申请详情')
    expect(wrapper.text()).toContain('详情查询完成')
    expect(wrapper.findAll('table')).toHaveLength(1)
    expect(wrapper.get('[data-testid="object-result"]').text()).toContain('CGSQ01')
  })

  it('shows a detail error without erasing the list result', async () => {
    api.createTaskDetailRun.mockRejectedValueOnce(new Error('详情服务暂不可用'))
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('查询采购申请列表')
    await wrapper.get('.command-input button').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="view-detail"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="detail-error"]').text()).toContain('详情服务暂不可用')
    expect(wrapper.get('table').text()).toContain('A-1')
  })

  it('keeps the query result visible and renders purchase progress', async () => {
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('查询孟明佳的采购申请')
    await wrapper.get('.command-input button').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="track-progress"]').trigger('click')
    await flushPromises()

    expect(api.createPurchaseProgressRun).toHaveBeenCalledWith('run-1', 'A-1')
    expect(wrapper.get('table').text()).toContain('CGSQ01')
    expect(wrapper.get('[data-testid="purchase-progress"]').text()).toContain(
      '采购订单已生成',
    )
  })

  it('shows a progress error without erasing the query result', async () => {
    api.createPurchaseProgressRun.mockRejectedValueOnce(new Error('追踪服务暂不可用'))
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('查询孟明佳的采购申请')
    await wrapper.get('.command-input button').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="track-progress"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="progress-error"]').text()).toContain(
      '追踪服务暂不可用',
    )
    expect(wrapper.get('table').text()).toContain('CGSQ01')
  })

  it('creates a cross-system follow-up from the trusted selected row', async () => {
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('查询采购申请列表')
    await wrapper.get('.command-input button').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="execute-action"]').trigger('click')
    await flushPromises()

    expect(api.executeTaskAction).toHaveBeenCalledWith(
      'run-1',
      'create-purchase-follow-up',
      'A-1',
    )
    expect(wrapper.text()).toContain('已在采购业务系统创建跟进任务')
    expect(wrapper.text()).toContain('FOLLOW-UP-0001')
  })

  it('shows a failed cross-system follow-up returned in a successful HTTP response', async () => {
    api.executeTaskAction.mockResolvedValueOnce({
      run_id: 'follow-up-failed',
      parent_run_id: 'run-1',
      selected_record_id: 'A-1',
      status: 'failed',
      errors: ['Skill 必填输入不完整'],
    })
    const wrapper = mount(NaturalLanguageTaskPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('查询采购申请列表')
    await wrapper.get('.command-input button').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="execute-action"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="action-error"]').text()).toContain(
      'Skill 必填输入不完整',
    )
  })
})
