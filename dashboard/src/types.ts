// 공유 타입 정의

export interface Agent {
  agent_id: string
  status: 'idle' | 'working' | 'done' | 'error' | 'waiting' | 'meeting' | string
  model?: string
  work_started_at?: string
  current_task_id?: string
  current_phase?: string
  active_project_title?: string
}

export interface Task {
  task_id: string
  state: string
  instruction?: string
  attachments?: string
  created_at?: string
}

export interface LogEntry {
  id: string
  agent_id: string
  event_type: string
  message: string
  data: Record<string, unknown>
  timestamp: string
}

// 채널 타입
export type ChannelId = 'all' | 'jobs' | 'gates' | 'components' | 'workreport'

// 컴포넌트 라이브러리 타입
export interface PersonaItem {
  id: string
  display_name: string
  description: string
  identity?: string
  traits?: string[]
  voice?: string
  category?: string
  tags?: string[]
  usage_count: number
  usages?: Array<{ spec_id: string; step_id: string }>
}

export interface SkillItem {
  id: string
  display_name: string
  description: string
  thinking_frame?: string
  output_checklist?: string[]
  category?: string
  tags?: string[]
  usage_count: number
  usages?: Array<{ spec_id: string; step_id: string }>
}

export interface ToolItem {
  id: string
  name: string
  description: string
  category: string
  enabled: boolean
  is_async: boolean
  params: string[]
  env_var: string
  token_set: boolean
  usage_count: number
}

// Job 파이프라인 타입
export interface JobStepMeta {
  parallel?: boolean
  when?: string
  optional?: boolean
  tier?: string
}

export interface JobStep extends JobStepMeta {
  step_id: string
  status: 'queued' | 'running' | 'done' | 'failed' | string
  output: string
  error: string
  started_at: string
  finished_at: string
  model_used: string
  cost_usd: number
  revised: number
  revision_feedback: string
  persona?: string
  skills?: string[]
  tools?: string[]
}

export interface JobGate {
  gate_id: string
  after_step: string
  prompt: string
  status: 'not_reached' | 'pending' | 'approved' | 'rejected' | string
  decision: string
  feedback: string
  opened_at: string
  // W1-3 Gate AI 대리 판단
  ai_suggestion?: '' | 'approve' | 'revise' | 'reject' | string
  ai_confidence?: number
  ai_model?: string
  ai_reason?: string
}

export interface Job {
  id: string
  spec_id: string
  title: string
  status: 'queued' | 'running' | 'waiting_gate' | 'done' | 'failed' | 'cancelled' | string
  input: Record<string, string>
  current_step: string
  error: string
  created_at: string
  started_at: string
  finished_at: string
  artifacts: Record<string, string>
  artifact_kinds?: Record<string, string>  // key → kind ('markdown'|'html'|'mermaid'|'svg'|'image'|'zip'|'json')
  total_cost_usd: number
  planned_steps?: string[]
  steps?: JobStep[]
  gates?: JobGate[]
}

export interface ToolParam {
  param: string
  tool_id: string
  tool_name: string
  env_var: string
}

export interface JobSpec {
  id: string
  title: string
  description: string
  input_fields: string[]
  required_fields: string[]
  step_count: number
  tool_params: ToolParam[]
}
