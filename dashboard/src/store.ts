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
  showSuggestions: boolean
  searchQuery: string
  setAgents: (agents: Agent[]) => void
  setTasks: (tasks: Task[]) => void
  addLog: (log: LogEntry) => void
  setLogs: (logs: LogEntry[]) => void
  toggleTheme: () => void
  setSelectedTaskId: (id: string) => void
  setActiveChannel: (channel: ChannelId) => void
  toggleArtifacts: () => void
  setShowSuggestions: (show: boolean) => void
  setSearchQuery: (query: string) => void
  updateLogReactions: (logId: string, reactions: Record<string, string[]>) => void
}

const savedTheme = localStorage.getItem('ai-office-theme') as 'dark' | 'light' | null
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
const initialTheme = savedTheme || (prefersDark ? 'dark' : 'light')

export const useStore = create<DashboardState>((set) => ({
  agents: [],
  tasks: [],
  logs: [],
  theme: initialTheme,
  selectedTaskId: '',
  activeChannel: 'all',
  showArtifacts: false,
  showSuggestions: false,
  searchQuery: '',

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
    set((state) => {
      const next = state.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem('ai-office-theme', next)
      return { theme: next }
    }),
  setSelectedTaskId: (selectedTaskId) => set({ selectedTaskId }),
  setActiveChannel: (activeChannel) => set({ activeChannel }),
  toggleArtifacts: () => set((state) => ({ showArtifacts: !state.showArtifacts })),
  setShowSuggestions: (showSuggestions) => set({ showSuggestions }),
  setSearchQuery: (searchQuery) => set({ searchQuery }),
  updateLogReactions: (logId, reactions) =>
    set((state) => ({
      logs: state.logs.map((l) =>
        l.id === logId ? { ...l, data: { ...l.data, reactions } } : l
      ),
    })),
}))
