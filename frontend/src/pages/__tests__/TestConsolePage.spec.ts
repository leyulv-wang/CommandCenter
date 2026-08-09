import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExtensionRecordingDetail, RecordingSummary } from '../../api/types'
import LatestLearningResult from '../../components/LatestLearningResult.vue'
import RecordingHistory from '../../components/RecordingHistory.vue'
import SystemConnectionStatus from '../../components/SystemConnectionStatus.vue'
import TestConsolePage from '../TestConsolePage.vue'

const api = vi.hoisted(() => ({
  listRecordings: vi.fn(),
  getRecording: vi.fn(),
}))

vi.mock('../../api/commandCenter', () => api)

const latest: RecordingSummary = {
  recording_id: 'latest',
  status: 'api_candidate',
  objective: '查询采购申请列表',
  source_system: 'yifeng_mes',
  capture_source: 'browser_extension',
  failure_reasons: [],
}

const detail: ExtensionRecordingDetail = {
  ...latest,
  learning_result: {
    execution_verification: 'pending_system_connection',
    candidate_skill: { name: '查询采购申请列表', status: 'candidate' },
  },
}

describe('TestConsolePage', () => {
  beforeEach(() => {
    api.listRecordings.mockReset().mockResolvedValue([latest])
    api.getRecording.mockReset().mockResolvedValue(detail)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads the latest recording into the single workflow page', async () => {
    const wrapper = shallowMount(TestConsolePage)
    await flushPromises()

    expect(api.listRecordings).toHaveBeenCalledWith(8)
    expect(api.getRecording).toHaveBeenCalledWith('latest')
    expect(wrapper.text()).toContain('浏览器演示')
    expect(wrapper.text()).toContain('API Skill')
    expect(wrapper.text()).toContain('中控执行')
    expect(wrapper.findComponent(SystemConnectionStatus).exists()).toBe(true)
    expect(wrapper.findComponent(LatestLearningResult).props('recording')).toEqual(detail)
  })

  it('polls while analysis is active and stops after a terminal result', async () => {
    vi.useFakeTimers()
    const analyzing = { ...latest, status: 'analyzing' as const }
    const analyzingDetail = { ...detail, status: 'analyzing' as const }
    api.listRecordings.mockResolvedValue([analyzing])
    api.getRecording
      .mockResolvedValueOnce(analyzingDetail)
      .mockResolvedValueOnce(detail)

    shallowMount(TestConsolePage)
    await flushPromises()
    expect(api.getRecording).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(api.getRecording).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(api.getRecording).toHaveBeenCalledTimes(2)
  })

  it('loads a selected history item and preserves visible data on refresh failure', async () => {
    const second = { ...latest, recording_id: 'second', source_system: 'connected_system' }
    api.listRecordings.mockResolvedValue([latest, second])
    const wrapper = shallowMount(TestConsolePage)
    await flushPromises()

    api.getRecording.mockResolvedValueOnce({ ...detail, ...second })
    wrapper.findComponent(RecordingHistory).vm.$emit('select', 'second')
    await flushPromises()
    expect(api.getRecording).toHaveBeenLastCalledWith('second')

    api.listRecordings.mockRejectedValueOnce(new Error('network down'))
    await wrapper.get('[data-testid="refresh-recordings"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('无法连接中控')
    expect(wrapper.findComponent(LatestLearningResult).props('recording')).toMatchObject({
      recording_id: 'second',
    })
  })
})
