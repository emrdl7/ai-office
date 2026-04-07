// Zustand 전역 상태 스토어
import { create } from 'zustand'
import type { Agent, Task, LogEntry, ChannelId } from './types'

const MAX_LOGS = 1000

interface DashboardState {
  agents: Agent[]
  tasks: Task[]
  logs: LogEntry[]
  theme: 'dark' | 'light'
  selectedTaskId: string
  activeChannel: ChannelId
  showArtifacts: boolean
  setAgents: (agents: Agent[]) => void
  setTasks: (tasks: Task[]) => void
  addLog: (log: LogEntry) => void
  setLogs: (logs: LogEntry[]) => void
  toggleTheme: () => void
  setSelectedTaskId: (id: string) => void
  setActiveChannel: (channel: ChannelId) => void
  toggleArtifacts: () => void
}

const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches

export const useStore = create<DashboardState>((set) => ({
  agents: [],
  tasks: [],
  logs: [],
  theme: prefersDark ? 'dark' : 'light',
  selectedTaskId: '',
  activeChannel: 'all',
  showArtifacts: false,

  setAgents: (agents) => set({ agents }),
  setTasks: (tasks) => set({ tasks }),
  addLog: (log) =>
    set((state) => {
      // ID 기반 중복 방지
      if (state.logs.some((l) => l.id === log.id)) return state
      return { logs: [...state.logs.slice(-(MAX_LOGS - 1)), log] }
    }),
  setLogs: (logs) => {
    // ID 기반 중복 제거
    const seen = new Set<string>()
    const unique = logs.filter((l) => {
      if (seen.has(l.id)) return false
      seen.add(l.id)
      return true
    })
    return set({ logs: unique.slice(-MAX_LOGS) })
  },
  toggleTheme: () =>
    set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
  setSelectedTaskId: (selectedTaskId) => set({ selectedTaskId }),
  setActiveChannel: (activeChannel) => set({ activeChannel }),
  toggleArtifacts: () => set((state) => ({ showArtifacts: !state.showArtifacts })),
}))
