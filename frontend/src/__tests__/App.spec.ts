import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import App from '../App.vue'
import TestConsolePage from '../pages/TestConsolePage.vue'

describe('App', () => {
  it('mounts only the minimal CommandCenter test console', () => {
    const wrapper = shallowMount(App)

    expect(wrapper.findComponent(TestConsolePage).exists()).toBe(true)
    expect(wrapper.text()).not.toContain('AI 生成配置')
    expect(wrapper.text()).not.toContain('外部业务系统')
    expect(wrapper.text()).not.toContain('任务中心')
    expect(wrapper.find('aside').exists()).toBe(false)
  })
})
