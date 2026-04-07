// 공유 타입 정의

export interface Agent {
  agent_id: string
  status: 'idle' | 'working' | 'done' | 'error' | 'waiting' | 'meeting' | string
  model?: string
  current_task_id?: string
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
export type ChannelId = 'all' | 'planner' | 'designer' | 'developer' | 'qa'
