import { request } from './client'
import type { SubmitFormRequest, TaskListResponse } from './types'

export function listTasks(operatorId = 'u001', status: 'pending' | 'completed' = 'pending') {
  const query = new URLSearchParams({ operator_id: operatorId, status })
  return request<TaskListResponse>(`/tasks?${query.toString()}`)
}

export function completeTask(
  systemCode: string,
  taskId: string,
  body: SubmitFormRequest,
) {
  return request<Record<string, unknown>>(
    `/tasks/${encodeURIComponent(systemCode)}/${encodeURIComponent(taskId)}/complete`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}
