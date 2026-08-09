import { describe, expect, it } from 'vitest'
import type { ExtensionRecordingDetail } from '../api/types'
import {
  extractCandidateSkill,
  isRecordingTerminal,
  recordingStatusPresentation,
} from '../recordingPresentation'

const recording: ExtensionRecordingDetail = {
  recording_id: 'recording-1',
  status: 'api_candidate',
  objective: '查询采购申请列表',
  source_system: 'yifeng_mes',
  capture_source: 'browser_extension',
  failure_reasons: [],
  learning_result: {
    final_status: 'api_candidate',
    execution_verification: 'pending_system_connection',
    candidate_skill: {
      name: '查询采购申请列表',
      status: 'candidate',
    },
  },
}

describe('recording presentation', () => {
  it('describes an API candidate as learned but waiting for execution connection', () => {
    expect(recordingStatusPresentation('api_candidate')).toEqual({
      label: 'API Skill 已生成',
      detail: '等待业务系统配置执行连接',
      tone: 'waiting',
    })
  })

  it('distinguishes processing statuses from terminal statuses', () => {
    expect(isRecordingTerminal('analyzing')).toBe(false)
    expect(isRecordingTerminal('recorded')).toBe(false)
    expect(isRecordingTerminal('api_candidate')).toBe(true)
    expect(isRecordingTerminal('rejected')).toBe(true)
  })

  it('extracts only an explicitly generated candidate Skill', () => {
    expect(extractCandidateSkill(recording)).toEqual({
      name: '查询采购申请列表',
      status: 'candidate',
      executionVerification: 'pending_system_connection',
    })

    expect(extractCandidateSkill({
      ...recording,
      learning_result: { candidate_skill: { status: 'candidate' } },
    })).toBeNull()
  })
})
