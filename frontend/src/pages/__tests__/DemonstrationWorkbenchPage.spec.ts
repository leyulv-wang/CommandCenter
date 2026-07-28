import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DemonstrationWorkbenchPage from '../DemonstrationWorkbenchPage.vue'


describe('DemonstrationWorkbenchPage', () => {
  it('presents the employee demonstration sequence and explicit controls', () => {
    const wrapper = shallowMount(DemonstrationWorkbenchPage)

    expect(wrapper.text()).toContain('演示工作台')
    expect(wrapper.text()).toContain('观察')
    expect(wrapper.text()).toContain('学习')
    expect(wrapper.text()).toContain('测试')
    expect(wrapper.text()).toContain('发布')
    expect(wrapper.text()).toContain('开始演示')
    expect(wrapper.text()).toContain('结束演示')
  })
})
