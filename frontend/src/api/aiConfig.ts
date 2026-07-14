import { request } from './client'
import type { GenerateConfigRequest, GenerateConfigResponse } from './types'

export function generateFormConfig(body: GenerateConfigRequest) {
  return request<GenerateConfigResponse>('/ai/form-config/generate', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
