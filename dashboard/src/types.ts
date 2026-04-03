// 공유 타입 정의

export interface Agent {
  agent_id: string
  status: 'idle' | 'working' | 'done' | 'error' | string
  current_task_id?: string
}

export interface Task {
  task_id: string
  state: string
}

export interface LogEntry {
  id: string
  agent_id: string
  event_type: string
  message: string
  data: Record<string, unknown>
  timestamp: string
}

export interface DagNodeData {
  label: string
  status: string
  assigned_to: string
  artifact_paths: string[]
}

export interface DagNode {
  id: string
  data: DagNodeData
  position: { x: number; y: number }
}

export interface DagEdge {
  id: string
  source: string
  target: string
}

export interface FileEntry {
  path: string
  type: 'code' | 'doc' | 'design' | 'data' | 'unknown'
  size: number
}
