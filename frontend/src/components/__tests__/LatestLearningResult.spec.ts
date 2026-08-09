import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ExtensionRecordingDetail } from '../../api/types'
import LatestLearningResult from '../LatestLearningResult.vue'

const recording: ExtensionRecordingDetail = {
  recording_id: 'recording-1',
  status: 'api_candidate',
  objective: '查询采购申请列表',
  source_system: 'yifeng_mes',
  capture_source: 'browser_extension',
  updated_at: '2026-08-09T12:29:48.644948+00:00',
  failure_reasons: [],
  learning_result: {
    execution_verification: 'pending_system_connection',
    candidate_skill: { name: '查询采购申请列表', status: 'candidate' },
  },
}

describe('LatestLearningResult', () => {
  it('shows the generated Skill and its real execution readiness', () => {
    const wrapper = shallowMount(LatestLearningResult, { props: { recording } })

    expect(wrapper.text()).toContain('API Skill 已生成')
    expect(wrapper.text()).toContain('查询采购申请列表')
    expect(wrapper.text()).toContain('等待业务系统配置执行连接')
    expect(wrapper.text()).toContain('yifeng_mes')
  })

  it('shows failure reasons and an actionable empty state', () => {
    const failed = shallowMount(LatestLearningResult, {
      props: {
        recording: {
          ...recording,
          status: 'rejected',
          failure_reasons: ['没有捕获到 API 请求'],
        },
      },
    })
    expect(failed.text()).toContain('没有捕获到 API 请求')

    const empty = shallowMount(LatestLearningResult)
    expect(empty.text()).toContain('请先使用浏览器扩展完成一次录制')
  })
})
