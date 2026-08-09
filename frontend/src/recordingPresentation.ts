import type {
  CandidateSkillSummary,
  ExtensionRecordingDetail,
  ExtensionRecordingStatus,
} from './api/types'

export type RecordingTone = 'neutral' | 'running' | 'success' | 'waiting' | 'danger'

export interface RecordingStatusPresentation {
  label: string
  detail: string
  tone: RecordingTone
}

const presentations: Record<ExtensionRecordingStatus, RecordingStatusPresentation> = {
  created: { label: '等待录制', detail: '请在浏览器扩展中开始演示', tone: 'neutral' },
  recording: { label: '正在录制', detail: '观察器正在记录页面操作和 API', tone: 'running' },
  recorded: { label: '录制已提交', detail: '等待中控开始分析', tone: 'running' },
  upload_failed: { label: '录制上传失败', detail: '证据仍保存在浏览器本地', tone: 'danger' },
  analyzing: { label: '智能体分析中', detail: '正在对齐页面操作与 API', tone: 'running' },
  api_candidate: {
    label: 'API Skill 已生成',
    detail: '等待业务系统配置执行连接',
    tone: 'waiting',
  },
  verified_candidate: { label: 'Skill 已完成验证', detail: '候选能力已通过无害测试', tone: 'success' },
  browser_candidate: { label: '浏览器 Skill 待验证', detail: '需要隔离环境验证浏览器执行', tone: 'waiting' },
  rejected: { label: 'Skill 学习失败', detail: '请查看失败原因后重新演示', tone: 'danger' },
}

export function recordingStatusPresentation(
  status: ExtensionRecordingStatus,
): RecordingStatusPresentation {
  return presentations[status]
}

export function isRecordingTerminal(status: ExtensionRecordingStatus): boolean {
  return !['created', 'recording', 'recorded', 'analyzing'].includes(status)
}

export function extractCandidateSkill(
  recording: ExtensionRecordingDetail,
): CandidateSkillSummary | null {
  const candidate = recording.learning_result?.candidate_skill
  if (!candidate?.name) return null
  return {
    name: candidate.name,
    status: candidate.status ?? 'candidate',
    executionVerification: recording.learning_result?.execution_verification,
  }
}
