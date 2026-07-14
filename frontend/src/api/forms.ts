import { request } from './client'
import type { FormTemplate, SubmitFormRequest } from './types'

export function listForms() {
  return request<FormTemplate[]>('/forms')
}

export function getForm(formCode: string) {
  return request<FormTemplate>(`/forms/${formCode}`)
}

export function createForm(template: FormTemplate) {
  return request<FormTemplate>('/forms', {
    method: 'POST',
    body: JSON.stringify(template),
  })
}

export function submitForm(formCode: string, body: SubmitFormRequest) {
  return request<Record<string, unknown>>(`/forms/${encodeURIComponent(formCode)}/submit`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
