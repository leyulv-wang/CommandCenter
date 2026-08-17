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

export type RecordingStatus =
  | 'created'
  | 'recording'
  | 'analyzing'
  | 'testing'
  | 'published'
  | 'needs_reteach'

export type RecordingFailureStage = 'analysis' | 'testing' | 'system'

export interface RecordingView {
  recording_id: string
  status: RecordingStatus
  objective: string
  source_system: string
  source_task_id: string
  failure_stage?: RecordingFailureStage
  failure_reasons?: string[]
  learning_result?: Record<string, unknown>
}

export type ExtensionRecordingStatus =
  | 'created'
  | 'recording'
  | 'upload_failed'
  | 'analyzing'
  | 'api_candidate'
  | 'verified_candidate'
  | 'browser_candidate'
  | 'rejected'
  | 'needs_reteach'
  | 'recorded'

export interface RecordingSummary {
  recording_id: string
  status: ExtensionRecordingStatus
  objective: string
  source_system: string
  capture_source: 'browser_extension' | 'playwright'
  created_at?: string | null
  updated_at?: string | null
  failure_reasons: string[]
  analysis_stage?:
    | 'recorded'
    | 'queued'
    | 'learning'
    | 'completed'
    | 'awaiting_browser_verification'
    | 'failed'
}

export interface CandidateSkillSummary {
  name: string
  status: string
  executionVerification?: string
}

export interface ExtensionRecordingDetail extends RecordingSummary {
  learning_result?: {
    final_status?: string
    execution_verification?: string
    candidate_skill?: {
      name?: string
      status?: string
    }
  }
}

export interface TaskRunView {
  run_id: string
  parent_run_id?: string
  user_request: string
  status:
    | 'matching'
    | 'needs_input'
    | 'needs_object_selection'
    | 'executing'
    | 'verifying'
    | 'succeeded'
    | 'failed'
  execution_mode?: 'tool' | 'skill'
  candidate_objects?: TaskItem[]
  available_actions?: AvailableTaskAction[]
  final_response?: {
    summary: string
    outputs?: Record<string, unknown>
    observed_state?: Record<string, unknown>
    tool_evidence?: Array<Record<string, unknown>>
    verification?: Record<string, unknown>
    progress?: PurchaseProgressResult
  }
  errors?: string[]
}

export interface AvailableTaskAction {
  action_id: string
  label: string
  record_id: string
  skill_id: string
  skill_version: number
  confirmation: 'none' | 'required'
}

export type PurchaseProgressStatus =
  | 'complete'
  | 'business_pending'
  | 'incomplete'
  | 'failed'

export interface PurchaseProgressStage {
  stage: 'application' | 'order' | 'receiving' | 'warehouse'
  status: 'completed' | 'in_progress' | 'pending' | 'not_found' | 'failed'
  summary: string
  record_count: number
  records: Array<Record<string, unknown>>
  evidence_step_ids: string[]
}

export interface PurchaseProgressResult {
  status: PurchaseProgressStatus
  summary: string
  stages: PurchaseProgressStage[]
}

export interface SystemConnectionView {
  system_code: string
  display_name: string
  status: 'connected' | 'disconnected'
  credential_source: 'windows_keyring'
}

export interface SystemSkillVerificationView {
  system_code: string
  recording_id: string
  skill_id: string
  skill_version: number
  status: 'api_candidate' | 'verified_candidate'
  test_results: Array<Record<string, unknown>>
}
