import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemConnectionStatus from '../SystemConnectionStatus.vue'

const api = vi.hoisted(() => ({
  getSystemConnection: vi.fn(),
  disconnectSystem: vi.fn(),
  verifyLatestSystemSkill: vi.fn(),
}))

vi.mock('../../api/commandCenter', () => api)

describe('SystemConnectionStatus', () => {
  beforeEach(() => {
    api.getSystemConnection.mockReset().mockResolvedValue({
      system_code: 'yifeng_mes',
      display_name: '益丰 MES',
      status: 'connected',
      credential_source: 'windows_keyring',
    })
    api.verifyLatestSystemSkill.mockReset().mockResolvedValue({
      system_code: 'yifeng_mes',
      status: 'verified_candidate',
      test_results: [],
    })
    api.disconnectSystem.mockReset().mockResolvedValue({
      system_code: 'yifeng_mes',
      display_name: '益丰 MES',
      status: 'disconnected',
      credential_source: 'windows_keyring',
    })
  })

  it('shows a secret-free connected state and verifies the latest Skill', async () => {
    const wrapper = mount(SystemConnectionStatus)
    await flushPromises()

    expect(wrapper.text()).toContain('益丰 MES 已连接')
    expect(wrapper.text()).not.toMatch(/token/i)
    await wrapper.get('[data-testid="verify-system-skill"]').trigger('click')
    await flushPromises()
    expect(api.verifyLatestSystemSkill).toHaveBeenCalledWith('yifeng_mes')
    expect(wrapper.text()).toContain('最新 API Skill 已通过只读验证')
  })

  it('directs a disconnected user back to the browser extension', async () => {
    api.getSystemConnection.mockResolvedValueOnce({
      system_code: 'yifeng_mes',
      display_name: '益丰 MES',
      status: 'disconnected',
      credential_source: 'windows_keyring',
    })
    const wrapper = mount(SystemConnectionStatus)
    await flushPromises()

    expect(wrapper.text()).toContain('等待浏览器连接')
    expect(wrapper.text()).toContain('在 MES 页面打开扩展并点击“连接中控”')
  })

  it('can remove the saved browser session', async () => {
    const wrapper = mount(SystemConnectionStatus)
    await flushPromises()
    await wrapper.get('[data-testid="disconnect-system"]').trigger('click')
    await flushPromises()

    expect(api.disconnectSystem).toHaveBeenCalledWith('yifeng_mes')
    expect(wrapper.text()).toContain('等待浏览器连接')
  })
})
