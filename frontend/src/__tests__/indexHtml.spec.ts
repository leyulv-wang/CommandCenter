// @vitest-environment node
import { describe, expect, it } from 'vitest'
import html from '../../index.html?raw'

describe('frontend document', () => {
  it('uses the CommandCenter test console product title', () => {
    expect(html).toContain('<title>CommandCenter 测试台</title>')
    expect(html).not.toContain('配置化表单执行智能体')
  })
})
