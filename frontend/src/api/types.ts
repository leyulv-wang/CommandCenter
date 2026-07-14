export type FieldType = 'text' | 'number' | 'textarea' | 'select' | 'datetime' | 'list'
export type EndpointType = 'workflow' | 'custom_url'
export type SubmitMode = 'mock' | 'http'
export type ContentType = 'json' | 'form'

export interface FormField {
  label: string
  key: string
  type: FieldType
  required: boolean
  item_fields: FormField[]
}

export interface EndpointConfig {
  method: string
  url: string
  fdTemplateId?: string | null
  default_docStatus: string
  operator_param: string
  values_param: string
  submit_mode: SubmitMode
  content_type: ContentType
  timeout_seconds: number
}

export interface FormTemplate {
  form_code: string
  form_name: string
  endpoint_type: EndpointType
  endpoint: EndpointConfig
  fields: FormField[]
}

export interface SubmitFormRequest {
  operator_id: string
  values: Record<string, unknown>
}

export interface GenerateConfigRequest {
  form_name: string
  description: string
}

export interface GenerateConfigResponse {
  draft_config: FormTemplate
  warnings: string[]
}

export type ExternalSystemRole = 'connected' | 'onboarding'

export interface ExternalSystem {
  system_code: string
  system_name: string
  base_url: string
  role: ExternalSystemRole
  form_codes: string[]
}

export interface ExternalSubmission {
  id: number
  ticket_id: string
  operator_id: string
  form_values: Record<string, unknown>
  source: 'seed' | 'submitted'
  endpoint_type?: EndpointType | null
  fd_template_id?: string | null
  created_at: string
}

export interface ExternalSubmissionResponse {
  system_name: string
  items: ExternalSubmission[]
}

export interface ExternalInterfaceSpec {
  system_name: string
  description: string
}

export interface TaskItem {
  task_id: string
  title: string
  task_type: string
  form_code: string
  content: Record<string, unknown>
  status: 'pending' | 'completed'
  assignee_id: string
  created_at: string
  source_system_code: string
  source_system_name: string
  result_values?: Record<string, unknown> | null
  completed_at?: string | null
}

export interface TaskListResponse {
  operator_id: string
  items: TaskItem[]
}

export interface ExternalSystemDataResponse {
  system: Pick<ExternalSystem, 'system_code' | 'system_name'>
  tasks: TaskItem[]
  submissions: ExternalSubmission[]
}
