import { request } from './client'
import type { RecordingSummary, RecordingView, TaskRunView } from './types'


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
  return request<RecordingView>(`/recordings/${recordingId}`)
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

export function selectTaskObject(runId: string, objectId: string) {
  return request<TaskRunView>(`/task-runs/${runId}/select-object`, {
    method: 'POST',
    body: JSON.stringify({ object_id: objectId }),
  })
}

export function getTaskRun(runId: string) {
  return request<TaskRunView>(`/task-runs/${runId}`)
}
