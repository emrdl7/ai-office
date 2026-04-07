// Zustand 전역 상태 스토어
import { create } from 'zustand'
import type { Agent, Task, LogEntry } from './types'

const MAX_LOGS = 1000

interface DashboardState {
  agents: Agent[]
  tasks: Task[]
  logs: LogEntry[]
  theme: 'dark' | 'light'
  selectedTaskId: string  // 현재 산출물을 볼 태스크
  setAgents: (agents: Agent[]) => void
  setTasks: (tasks: Task[]) => void
  addLog: (log: LogEntry) => void
  setLogs: (logs: LogEntry[]) => void
  toggleTheme: () => void
  setSelectedTaskId: (id: string) => void
}

const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

export const useStore = create<DashboardState>((set) => ({
  agents: [],
  tasks: [],
  logs: [],
  theme: prefersDark ? 'dark' : 'light',
  selectedTaskId: '',

  setAgents: (agents) => set({ agents }),
  setTasks: (tasks) => set({ tasks }),
  addLog: (log) =>
    set((state) => {
      const last = state.logs[state.logs.length - 1]
      if (last && last.timestamp === log.timestamp && last.message === log.message) {
        return state
      }
      return { logs: [...state.logs.slice(-(MAX_LOGS - 1)), log] }
    }),
  setLogs: (logs) => set({ logs: logs.slice(-MAX_LOGS) }),
  toggleTheme: () =>
    set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
  setSelectedTaskId: (selectedTaskId) => set({ selectedTaskId }),
}))
