import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  listExternalSystemForms,
  listExternalSystems,
} from '../../api/externalSystems'
import { listTasks } from '../../api/tasks'
import TaskCenterPage from '../TaskCenterPage.vue'

vi.mock('../../api/externalSystems', () => ({
  listExternalSystems: vi.fn(),
  listExternalSystemForms: vi.fn(),
}))
vi.mock('../../api/tasks', () => ({
  listTasks: vi.fn(),
  completeTask: vi.fn(),
}))
vi.mock('../../api/forms', () => ({
  getForm: vi.fn(),
  submitForm: vi.fn(),
}))

describe('TaskCenterPage demo user', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    window.history.replaceState({}, '', '/?user=u002')
    vi.mocked(listExternalSystems).mockResolvedValue([])
    vi.mocked(listExternalSystemForms).mockResolvedValue([])
    vi.mocked(listTasks).mockResolvedValue({
      operator_id: 'u002',
      items: [],
    })
  })

  it('loads and labels the u002 task center', async () => {
    const wrapper = mount(TaskCenterPage, {
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('采购审批人')
    expect(wrapper.text()).toContain('u002')
    expect(listTasks).toHaveBeenCalledWith('u002', 'pending')
    expect(listTasks).toHaveBeenCalledWith('u002', 'completed')
  })
})
