import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PurchaseProgress from '../PurchaseProgress.vue'


const progress = {
  status: 'complete' as const,
  summary: '采购订单已生成并找到收货记录',
  stages: [
    {
      stage: 'application' as const,
      status: 'completed' as const,
      summary: '采购申请已审核',
      record_count: 1,
      records: [{ applyNo: 'CGSQ01' }],
      evidence_step_ids: [],
    },
    {
      stage: 'order' as const,
      status: 'completed' as const,
      summary: '已生成采购订单',
      record_count: 1,
      records: [{ orderNumber: 'CGDD01' }],
      evidence_step_ids: ['tool_01'],
    },
    {
      stage: 'receiving' as const,
      status: 'completed' as const,
      summary: '已找到两次收货',
      record_count: 2,
      records: [{ receiptNo: 'SH01' }, { receiptNo: 'SH02' }],
      evidence_step_ids: ['tool_02'],
    },
  ],
}


describe('PurchaseProgress', () => {
  it('renders every returned stage and record count', () => {
    const wrapper = mount(PurchaseProgress, { props: { progress } })

    expect(wrapper.text()).toContain('采购申请')
    expect(wrapper.text()).toContain('采购订单')
    expect(wrapper.text()).toContain('收货')
    expect(wrapper.text()).toContain('2 条记录')
    expect(wrapper.findAll('[data-testid="progress-stage"]')).toHaveLength(3)
  })

  it('keeps raw stage records collapsed by default', () => {
    const wrapper = mount(PurchaseProgress, { props: { progress } })

    expect(wrapper.get('details').attributes('open')).toBeUndefined()
    expect(wrapper.get('details').text()).toContain('查看阶段数据')
  })
})
