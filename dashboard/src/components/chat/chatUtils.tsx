import { AGENT_IDS } from '../../config/team'
import type { LogEntry, ChannelId } from '../../types'

export const AVATAR_IMG: Record<string, string> = Object.fromEntries(
  AGENT_IDS.map((id) => [id, `/avatars/${id}.png`])
)

export const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'])
export const AGENT_IDS_SET = new Set(['planner', 'designer', 'developer', 'qa'])

export interface FileInfo {
  name: string
  url: string
  size: number
  isImage: boolean
}

export function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

export function isSystemEvent(e: LogEntry): boolean {
  const hidden = [
    'status_change', 'meeting_start', 'meeting_end',
    'task_start', 'task_end', 'internal',
    'reaction_update',
  ]
  if (hidden.includes(e.event_type)) return true
  if (!e.message || e.message.trim() === '') return true
  return false
}

export function fileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (['pdf'].includes(ext)) return 'picture_as_pdf'
  if (['doc', 'docx'].includes(ext)) return 'article'
  if (['xls', 'xlsx', 'csv'].includes(ext)) return 'table_chart'
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (['zip', 'tar', 'gz'].includes(ext)) return 'folder_zip'
  return 'description'
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

export function isImageFile(name: string): boolean {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return IMAGE_EXTS.has(ext)
}

export function linkify(text: string) {
  const combinedRegex = /(https?:\/\/[^\s<]+|@[가-힣A-Za-z]+(?:님)?)/g
  const parts = text.split(combinedRegex)
  return parts.map((part, i) => {
    if (/^https?:\/\//.test(part)) {
      return (
        <a key={i} href={part} target="_blank" rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 underline break-all">
          {part.length > 60 ? part.slice(0, 60) + '...' : part}
        </a>
      )
    }
    if (/^@/.test(part)) {
      return (
        <span key={i} className="mention-highlight font-semibold rounded px-0.5">{part}</span>
      )
    }
    return <span key={i}>{part}</span>
  })
}

export function filterLogs(logs: LogEntry[], channel: ChannelId): LogEntry[] {
  if (channel === 'all') {
    return logs.filter((log) => !log.data?.dm && !AGENT_IDS_SET.has(log.data?.to as string))
  }
  return logs.filter((log) => {
    if (log.agent_id === channel && log.data?.dm) return true
    if (log.agent_id === 'user' && log.data?.to === channel) return true
    if (log.agent_id === channel && ['typing', 'autonomous', 'system_notice', 'autonomous_pass', 'autonomous_stuck'].includes(log.event_type)) return true
    return false
  })
}
