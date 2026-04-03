// Zustand 전역 상태 스토어
import { create } from 'zustand'
import type { Agent, Task, LogEntry, DagNode, DagEdge } from './types'

const MAX_LOGS = 1000

interface DashboardState {
  // 데이터
  agents: Agent[]
  tasks: Task[]
  logs: LogEntry[]
  dagNodes: DagNode[]
  dagEdges: DagEdge[]
  // UI
  theme: 'dark' | 'light'
  activeTab: 'logs' | 'artifacts' | 'dag'
  // 액션
  setAgents: (agents: Agent[]) => void
  setTasks: (tasks: Task[]) => void
  addLog: (log: LogEntry) => void
  setLogs: (logs: LogEntry[]) => void
  setDag: (nodes: DagNode[], edges: DagEdge[]) => void
  toggleTheme: () => void
  setActiveTab: (tab: 'logs' | 'artifacts' | 'dag') => void
}

// 시스템 선호 테마 감지
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

export const useStore = create<DashboardState>((set) => ({
  agents: [],
  tasks: [],
  logs: [],
  dagNodes: [],
  dagEdges: [],
  theme: prefersDark ? 'dark' : 'light',
  activeTab: 'logs',

  setAgents: (agents) => set({ agents }),
  setTasks: (tasks) => set({ tasks }),
  addLog: (log) =>
    set((state) => ({
      logs: [...state.logs.slice(-(MAX_LOGS - 1)), log],
    })),
  setLogs: (logs) => set({ logs: logs.slice(-MAX_LOGS) }),
  setDag: (dagNodes, dagEdges) => set({ dagNodes, dagEdges }),
  toggleTheme: () =>
    set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
  setActiveTab: (activeTab) => set({ activeTab }),
}))
