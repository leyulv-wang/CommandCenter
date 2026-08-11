import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TaskResultTable from '../TaskResultTable.vue'

describe('TaskResultTable', () => {
  it('finds nested records and renders dynamic columns as a table', () => {
    const wrapper = mount(TaskResultTable, {
      props: {
        outputs: {
          query_list: {
            success: true,
            result: {
              records: [
                {
                  applyNo: 'CGSQ26042201',
                  applyBy: '管理员',
                  applyDate: '2026-04-22',
                },
                {
                  applyNo: 'CGSQ26042101',
                  applyBy: '孟明伟',
                  auditStatus: 2,
                },
              ],
              total: 2,
            },
          },
        },
      },
    })

    expect(wrapper.get('table').text()).toContain('applyNo')
    expect(wrapper.get('table').text()).toContain('auditStatus')
    expect(wrapper.get('table').text()).toContain('CGSQ26042201')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.get('[data-testid="result-count"]').text()).toContain('2 条记录')
  })

  it('renders null as a dash and nested values as compact JSON', () => {
    const wrapper = mount(TaskResultTable, {
      props: {
        outputs: {
          records: [{ applyNo: 'CGSQ01', remark: null, owner: { name: '管理员' } }],
        },
      },
    })

    expect(wrapper.get('table').text()).toContain('—')
    expect(wrapper.get('table').text()).toContain('{"name":"管理员"}')
  })

  it('shows an empty result without promoting raw JSON', () => {
    const wrapper = mount(TaskResultTable, {
      props: { outputs: { result: { records: [] } } },
    })

    expect(wrapper.text()).toContain('查询成功，暂无记录')
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.get('details').attributes('open')).toBeUndefined()
  })

  it('uses a compact key-value fallback when there is no record array', () => {
    const wrapper = mount(TaskResultTable, {
      props: { outputs: { success: true, total: 1 } },
    })

    expect(wrapper.get('[data-testid="object-result"]').text()).toContain('success')
    expect(wrapper.get('[data-testid="object-result"]').text()).toContain('true')
  })

  it('unwraps a main-record response instead of rendering one long JSON field', () => {
    const wrapper = mount(TaskResultTable, {
      props: {
        outputs: {
          query_purchase_apply_main: {
            success: true,
            message: '',
            code: 200,
            result: {
              id: '2037430718812770305',
              applyNo: 'CGSQ26032701',
              applyBy: '孟明佳',
              applyDate: '2026-03-27',
            },
          },
        },
      },
    })

    const labels = wrapper.findAll('[data-testid="object-result"] dt').map((item) => item.text())
    expect(labels).toEqual(['id', 'applyNo', 'applyBy', 'applyDate'])
    expect(wrapper.get('[data-testid="object-result"]').text()).toContain('CGSQ26032701')
    expect(wrapper.get('[data-testid="object-result"]').text()).not.toContain(
      'query_purchase_apply_main',
    )
  })

  it('emits the selected saved record id when details are enabled', async () => {
    const wrapper = mount(TaskResultTable, {
      props: {
        outputs: {
          records: [
            { id: 'row-1', applyNo: 'CGSQ01' },
            { id: 'row-2', applyNo: 'CGSQ02' },
          ],
        },
        allowDetails: true,
      },
    })

    expect(wrapper.findAll('[data-testid="view-detail"]')).toHaveLength(2)
    await wrapper
      .get('[data-record-id="row-1"] [data-testid="view-detail"]')
      .trigger('click')

    expect(wrapper.emitted('view-detail')).toEqual([['row-1']])
  })

  it('does not offer details for id-less rows or object-only output', () => {
    const rows = mount(TaskResultTable, {
      props: {
        outputs: { records: [{ applyNo: 'CGSQ01' }] },
        allowDetails: true,
      },
    })
    const object = mount(TaskResultTable, {
      props: { outputs: { success: true }, allowDetails: true },
    })

    expect(rows.find('[data-testid="view-detail"]').exists()).toBe(false)
    expect(object.find('[data-testid="view-detail"]').exists()).toBe(false)
  })
})
