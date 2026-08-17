import { request } from './client'
import type {
  ExtensionRecordingDetail,
  RecordingSummary,
  RecordingView,
  TaskRunView,
  SystemConnectionView,
  SystemSkillVerificationView,
  TaskSessionHint,
  TaskSessionView,
} from './types'


export function createRecording(payload: {
  objective: string
  source_system: string
  source_task_id: string
}) {
  return request<RecordingView>('/recordings', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function startRecording(recordingId: string) {
  return request<RecordingView>(`/recordings/${recordingId}/start`, { method: 'POST' })
}

export function stopRecording(recordingId: string) {
  return request<RecordingView>(`/recordings/${recordingId}/stop`, { method: 'POST' })
}

export function getRecording(recordingId: string) {
  return request<ExtensionRecordingDetail>(`/recordings/${recordingId}`)
}

export function listRecordings(limit = 1) {
  return request<RecordingSummary[]>(
    `/recordings?capture_source=browser_extension&limit=${limit}`,
  )
}

export function createTaskRun(userRequest: string) {
  return request<TaskRunView>('/task-runs', {
    method: 'POST',
    body: JSON.stringify({ user_request: userRequest }),
  })
}

export function createTaskDetailRun(parentRunId: string, recordId: string) {
  return request<TaskRunView>(`/task-runs/${parentRunId}/details`, {
    method: 'POST',
    body: JSON.stringify({ record_id: recordId }),
  })
}

export function createPurchaseProgressRun(parentRunId: string, recordId: string) {
  return request<TaskRunView>(`/task-runs/${parentRunId}/purchase-progress`, {
    method: 'POST',
    body: JSON.stringify({ record_id: recordId }),
  })
}

export function createPurchaseFollowUpRun(
  parentRunId: string,
  recordId: string,
  instruction = '为这条采购申请创建采购跟进任务',
) {
  return request<TaskRunView>(`/task-runs/${parentRunId}/purchase-follow-up`, {
    method: 'POST',
    body: JSON.stringify({ record_id: recordId, instruction }),
  })
}

export function executeTaskAction(
  parentRunId: string,
  actionId: string,
  recordId: string,
) {
  return request<TaskRunView>(
    `/task-runs/${parentRunId}/actions/${encodeURIComponent(actionId)}/execute`,
    {
      method: 'POST',
      body: JSON.stringify({ record_id: recordId }),
    },
  )
}

export function selectTaskObject(runId: string, objectId: string) {
  return request<TaskRunView>(`/task-runs/${runId}/select-object`, {
    method: 'POST',
    body: JSON.stringify({ object_id: objectId }),
  })
}

export function getTaskRun(runId: string) {
  return request<TaskRunView>(`/task-runs/${runId}`)
}

export function createTaskSession(payload: { goal: string; hint?: TaskSessionHint }) {
  return request<TaskSessionView>('/task-sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendTaskSessionMessage(sessionId: string, version: number, message: string) {
  return request<TaskSessionView>(`/task-sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ version, message }),
  })
}

export function submitTaskSessionInputs(
  sessionId: string,
  version: number,
  values: Record<string, unknown>,
) {
  return request<TaskSessionView>(`/task-sessions/${sessionId}/inputs`, {
    method: 'POST',
    body: JSON.stringify({ version, values }),
  })
}

export function confirmTaskSession(
  sessionId: string,
  payload: {
    version: number
    plan_revision: number
    plan_hash: string
    confirmation_token: string
    approved: boolean
  },
) {
  return request<TaskSessionView>(`/task-sessions/${sessionId}/confirmations`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getTaskSession(sessionId: string) {
  return request<TaskSessionView>(`/task-sessions/${sessionId}`)
}

export function getSystemConnection(systemCode: string) {
  return request<SystemConnectionView>(`/system-connections/${systemCode}`)
}

export function disconnectSystem(systemCode: string) {
  return request<SystemConnectionView>(`/system-connections/${systemCode}`, {
    method: 'DELETE',
  })
}

export function verifyLatestSystemSkill(systemCode: string) {
  return request<SystemSkillVerificationView>(
    `/system-connections/${systemCode}/verify-latest-skill`,
    { method: 'POST' },
  )
}
