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

export interface FileEntry {
  path: string
  type: 'code' | 'doc' | 'design' | 'data' | 'unknown'
  size: number
}

// 채널 타입
export type ChannelId = 'all' | 'jobs' | 'gates'

// Job 파이프라인 타입
export interface JobStep {
  step_id: string
  status: 'queued' | 'running' | 'done' | 'failed' | string
  output: string
  error: string
  started_at: string
  finished_at: string
  model_used: string
  cost_usd: number
  revised: number           // 수정 재실행 횟수 (0 = 최초)
  revision_feedback: string // 마지막 수정 요청 피드백
}

export interface JobGate {
  gate_id: string
  after_step: string
  prompt: string
  status: 'not_reached' | 'pending' | 'approved' | 'rejected' | string
  decision: string
  feedback: string
  opened_at: string
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
  steps?: JobStep[]
  gates?: JobGate[]
}

export interface JobSpec {
  id: string
  title: string
  description: string
  input_fields: string[]
  step_count: number
}
