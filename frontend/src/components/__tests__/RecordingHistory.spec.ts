import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { RecordingSummary } from '../../api/types'
import RecordingHistory from '../RecordingHistory.vue'

const recordings: RecordingSummary[] = [
  {
    recording_id: 'first',
    status: 'api_candidate',
    objective: '查询采购申请列表',
    source_system: 'yifeng_mes',
    capture_source: 'browser_extension',
    updated_at: '2026-08-09T12:29:48.644948+00:00',
    failure_reasons: [],
  },
  {
    recording_id: 'second',
    status: 'verified_candidate',
    objective: '刷新申请记录',
    source_system: 'connected_system',
    capture_source: 'browser_extension',
    updated_at: '2026-08-07T07:15:28.889073+00:00',
    failure_reasons: [],
  },
]

describe('RecordingHistory', () => {
  it('shows exact source systems and emits the selected recording', async () => {
    const wrapper = shallowMount(RecordingHistory, {
      props: { recordings, selectedId: 'first' },
    })

    expect(wrapper.text()).toContain('yifeng_mes')
    expect(wrapper.text()).toContain('connected_system')
    expect(wrapper.get('[data-recording-id="first"]').attributes('aria-current')).toBe('true')

    await wrapper.get('[data-recording-id="second"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['second']])
  })

  it('invites the user to record when history is empty', () => {
    const wrapper = shallowMount(RecordingHistory, {
      props: { recordings: [], selectedId: '' },
    })
    expect(wrapper.text()).toContain('还没有浏览器录制')
  })

  it('keeps the history visible when the backend returns a retry status', () => {
    const retryRecording = {
      ...recordings[0],
      recording_id: 'retry',
      status: 'needs_reteach',
    } satisfies RecordingSummary

    const wrapper = shallowMount(RecordingHistory, {
      props: { recordings: [retryRecording], selectedId: 'retry' },
    })

    expect(wrapper.text()).toContain('1 条')
    expect(wrapper.text()).toContain('需要重新演示')
    expect(wrapper.get('[data-recording-id="retry"]').text()).toContain('需要重新演示')
  })
})
