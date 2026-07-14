import { request } from './client'
import type {
  ExternalInterfaceSpec,
  ExternalSubmissionResponse,
  ExternalSystem,
  ExternalSystemDataResponse,
  FormTemplate,
} from './types'

export function listExternalSystems() {
  return request<ExternalSystem[]>('/external-systems')
}

export function listExternalSubmissions(systemCode: string) {
  return request<ExternalSubmissionResponse>(`/external-systems/${systemCode}/submissions`)
}

export function getExternalSystemData(systemCode: string) {
  return request<ExternalSystemDataResponse>(
    `/external-systems/${encodeURIComponent(systemCode)}/data`,
  )
}

export function listExternalSystemForms(systemCode: string) {
  return request<FormTemplate[]>(`/external-systems/${encodeURIComponent(systemCode)}/forms`)
}

export function getExternalInterfaceSpec(systemCode: string) {
  return request<ExternalInterfaceSpec>(`/external-systems/${systemCode}/interface-spec`)
}

export function resetOnboardingDemo() {
  return request<Record<string, unknown>>('/demo/reset-onboarding', {
    method: 'POST',
  })
}

export function resetDemoSystem(systemCode: string) {
  return request<Record<string, unknown>>(`/demo/reset/${encodeURIComponent(systemCode)}`, {
    method: 'POST',
  })
}
