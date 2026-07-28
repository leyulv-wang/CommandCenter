import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NaturalLanguageTaskPanel from '../NaturalLanguageTaskPanel.vue'


describe('NaturalLanguageTaskPanel', () => {
  it('presents one plain-language task action for employees', () => {
    const wrapper = shallowMount(NaturalLanguageTaskPanel)

    expect(wrapper.text()).toContain('直接交给中控')
    expect(wrapper.text()).toContain('执行任务')
    expect(wrapper.text()).toContain('例如：处理签字笔库存不足任务')
  })
})
