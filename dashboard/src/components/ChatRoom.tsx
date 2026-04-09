// 채팅방 — 메신저 대화 UI + 파일첨부 + 이미지 썸네일 + 링크 프리뷰
import { useEffect, useRef, useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import { AGENT_PROFILE } from './Sidebar'
import type { Agent, LogEntry, Task, ChannelId } from '../types'
import Markdown from 'react-markdown'

// 미생 캐릭터 아바타 이미지
const AVATAR_IMG: Record<string, string> = {
  teamlead: '/avatars/teamlead.png',
  planner: '/avatars/planner.png',
  designer: '/avatars/designer.png',
  developer: '/avatars/developer.png',
  qa: '/avatars/qa.png',
}

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/logs`
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'])

function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

function isSystemEvent(e: LogEntry): boolean {
  return ['status_change', 'meeting_start', 'meeting_end', 'task_start', 'task_end', 'internal'].includes(e.event_type)
}

function fileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (['pdf'].includes(ext)) return '📕'
  if (['doc', 'docx'].includes(ext)) return '📘'
  if (['xls', 'xlsx', 'csv'].includes(ext)) return '📗'
  if (IMAGE_EXTS.has(ext)) return '🖼️'
  if (['zip', 'tar', 'gz'].includes(ext)) return '📦'
  return '📄'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function isImageFile(name: string): boolean {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return IMAGE_EXTS.has(ext)
}

// URL 감지 + 링크화
function linkify(text: string) {
  // URL + @멘션 동시 처리
  const combinedRegex = /(https?:\/\/[^\s<]+|@[가-힣A-Za-z]+(?:님)?)/g
  const parts = text.split(combinedRegex)
  return parts.map((part, i) => {
    if (/^https?:\/\//.test(part)) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 underline break-all"
        >
          {part.length > 60 ? part.slice(0, 60) + '...' : part}
        </a>
      )
    }
    if (/^@/.test(part)) {
      return (
        <span
          key={i}
          className="text-blue-400 font-semibold bg-blue-500/10 rounded px-0.5"
        >
          {part}
        </span>
      )
    }
    return <span key={i}>{part}</span>
  })
}

// 채널별 로그 필터
function filterLogs(logs: LogEntry[], channel: ChannelId): LogEntry[] {
  if (channel === 'all') {
    return logs.filter((log) => !log.data?.dm && log.data?.to !== 'planner' && log.data?.to !== 'designer' && log.data?.to !== 'developer' && log.data?.to !== 'qa')
  }
  return logs.filter((log) => {
    if (log.agent_id === channel && log.data?.dm) return true
    if (log.agent_id === 'user' && log.data?.to === channel) return true
    return false
  })
}

// 첨부파일 정보 타입
interface FileInfo {
  name: string
  url: string
  size: number
  isImage: boolean
}

async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) return []
  return res.json()
}

const REACTION_EMOJIS = ['👍', '❤️', '😂', '🔥', '👀']

export function ChatRoom({ onMenuClick }: { onMenuClick?: () => void }) {
  const { logs, addLog, setLogs, activeChannel, searchQuery, setSearchQuery, updateLogReactions } = useStore()

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: fetchAgents,
    refetchInterval: 2000,
  })
  const workingAgents = agents.filter((a) => a.status === 'working' || a.status === 'meeting')
  const [message, setMessage] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  const [typingAgents, setTypingAgents] = useState<Set<string>>(new Set())
  const [baseTaskId, setBaseTaskId] = useState('')
  const [showTaskPicker, setShowTaskPicker] = useState(false)
  const [completedTasks, setCompletedTasks] = useState<Task[]>([])
  const [activeProject, setActiveProject] = useState<{ id: string; title: string } | null>(null)
  const sendLock = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  // WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      // 재연결 시 누락된 메시지 복구
      fetch('/api/logs/history?limit=200')
        .then((r) => r.json())
        .then((data: LogEntry[]) => {
          if (Array.isArray(data) && data.length > 0) setLogs(data)
        })
        .catch(() => {})
      // 활성 프로젝트 복원
      fetch('/api/project/active')
        .then((r) => r.json())
        .then((data) => {
          if (data.project_id) setActiveProject({ id: data.project_id, title: data.title })
          else setActiveProject(null)
        })
        .catch(() => {})
    }
    ws.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 2000)
    }
    ws.onmessage = (event) => {
      try {
        const log = JSON.parse(event.data) as LogEntry
        if (log.event_type === 'reaction_update') {
          const { log_id, reactions } = log.data ?? {}
          if (log_id && reactions) updateLogReactions(log_id, reactions)
          return
        }
        if (log.event_type === 'project_update') {
          const title = log.message.replace(/^📂\s*(새 프로젝트|프로젝트 이어가기):\s*/, '')
          if (title) setActiveProject({ id: log.agent_id, title })
          addLog(log)
          return
        }
        if (log.event_type === 'project_close') {
          setActiveProject(null)
          return
        }
        if (log.event_type === 'typing') {
          // 입력 중 표시 → 5초 후 자동 해제
          setTypingAgents((prev) => new Set(prev).add(log.agent_id))
          setTimeout(() => {
            setTypingAgents((prev) => {
              const next = new Set(prev)
              next.delete(log.agent_id)
              return next
            })
          }, 15000)
        } else {
          // 실제 메시지 도착 시 typing 해제
          setTypingAgents((prev) => {
            const next = new Set(prev)
            next.delete(log.agent_id)
            return next
          })
          addLog(log)
        }
      } catch { /* 무시 */ }
    }
  }, [addLog])

  useEffect(() => {
    connect()
    return () => { clearTimeout(reconnectTimer.current); wsRef.current?.close() }
  }, [connect])

  // 히스토리 복구는 WebSocket onopen에서 처리 (재연결 시 누락 메시지 자동 복구)

  const isInitialLoad = useRef(true)
  useEffect(() => {
    // 초기 로드 시에는 즉시 스크롤, 이후 새 메시지는 부드럽게
    bottomRef.current?.scrollIntoView({ behavior: isInitialLoad.current ? 'instant' : 'smooth' })
    if (isInitialLoad.current && logs.length > 0) isInitialLoad.current = false
  }, [logs, activeChannel])

  function autoResize(el: HTMLTextAreaElement) {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  // 이전 작업 선택 팝업 열기
  async function openTaskPicker() {
    try {
      const res = await fetch('/api/tasks')
      if (res.ok) {
        const tasks: Task[] = await res.json()
        setCompletedTasks(tasks.filter((t) => t.state === 'completed').reverse().slice(0, 10))
      }
    } catch { /* 무시 */ }
    setShowTaskPicker(true)
  }

  // 파일 선택
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? [])
    if (selected.length === 0) return
    setFiles((prev) => [...prev, ...selected])
    // 이미지 로컬 프리뷰 생성
    const newPreviews = selected.map((f) =>
      isImageFile(f.name) ? URL.createObjectURL(f) : ''
    )
    setPreviews((prev) => [...prev, ...newPreviews])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function removeFile(idx: number) {
    if (previews[idx]) URL.revokeObjectURL(previews[idx])
    setFiles((prev) => prev.filter((_, i) => i !== idx))
    setPreviews((prev) => prev.filter((_, i) => i !== idx))
  }

  // 전송
  async function handleSend() {
    if (sendLock.current) return
    if (!message.trim() && files.length === 0) return
    sendLock.current = true
    setSending(true)
    try {
      const form = new FormData()
      form.append('message', message.trim())
      form.append('to', activeChannel)
      if (baseTaskId) form.append('base_task_id', baseTaskId)
      for (const f of files) form.append('files', f)
      await fetch('/api/chat', { method: 'POST', body: form })
      setMessage('')
      setFiles([])
      previews.forEach((p) => { if (p) URL.revokeObjectURL(p) })
      setPreviews([])
      setBaseTaskId('')
      if (inputRef.current) inputRef.current.style.height = 'auto'
    } catch { /* 에러 */ }
    finally {
      sendLock.current = false
      setSending(false)
      inputRef.current?.focus()
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const [showSearch, setShowSearch] = useState(false)

  const channelLogs = filterLogs(logs, activeChannel).filter(
    (log) => !searchQuery || log.message.toLowerCase().includes(searchQuery.toLowerCase())
  )
  const profile = AGENT_PROFILE[activeChannel]
  const channelTitle = activeChannel === 'all'
    ? '# 팀 채널'
    : `${profile?.character || profile?.name || activeChannel}`

  return (
    <>
      {/* 헤더 */}
      <header className="flex items-center justify-between px-4 md:px-5 py-3
        bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
        <div className="flex items-center gap-3">
          {/* 모바일 햄버거 */}
          <button
            onClick={onMenuClick}
            className="md:hidden p-1.5 rounded-lg text-gray-500 hover:bg-gray-100
              dark:hover:bg-gray-800 cursor-pointer"
            aria-label="메뉴"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          {activeChannel !== 'all' && AVATAR_IMG[activeChannel] && (
            <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${profile?.color}
              flex items-center justify-center overflow-hidden`}>
              <img src={AVATAR_IMG[activeChannel]} alt={profile?.character}
                className="w-full h-full object-cover" />
            </div>
          )}
          <div>
            <h2 className="text-sm font-semibold">{channelTitle}</h2>
            {activeChannel !== 'all' && profile && (
              <p className="text-[11px] text-gray-500">{profile.role}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setShowSearch(!showSearch); if (showSearch) setSearchQuery('') }}
            className={`p-1.5 rounded-lg transition-colors cursor-pointer
              ${showSearch ? 'text-blue-500 bg-blue-50 dark:bg-blue-900/30' : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}`}
            aria-label="검색"
            title="대화 검색"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>
          <button
            onClick={() => setLogs([])}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
              dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="대화 지우기"
            title="대화 지우기"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
          <button
            onClick={() => window.location.reload()}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
              dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="새로고침"
            title="새로고침"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-gray-400'}`} />
        </div>
      </header>

      {/* 활성 프로젝트 표시 */}
      {activeProject && (
        <div className="px-4 py-1.5 bg-blue-50 dark:bg-blue-900/20
          border-b border-blue-100 dark:border-blue-800
          flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400">
          <span>📂</span>
          <span className="font-medium">{activeProject.title}</span>
        </div>
      )}

      {/* 검색 바 */}
      {showSearch && (
        <div className="px-4 py-2 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="대화 검색..."
            className="w-full px-3 py-1.5 text-sm rounded-lg
              bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700
              focus:outline-none focus:ring-2 focus:ring-blue-500
              text-gray-800 dark:text-gray-200 placeholder-gray-400"
            autoFocus
          />
        </div>
      )}

      {/* 대화 영역 */}
      <div
        className="flex-1 overflow-y-auto py-3 min-h-0
          bg-gray-50 dark:bg-gray-900/50"
        role="log" aria-live="polite" aria-label="대화"
      >
        <div className="max-w-3xl mx-auto px-3 md:px-5 space-y-1">
          {channelLogs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-400 py-40">
              <p className="text-sm">
                {activeChannel === 'all'
                  ? '팀 채널입니다. 팀원들과 대화하세요.'
                  : `${profile?.character || profile?.name}에게 메시지를 보내세요.`}
              </p>
            </div>
          ) : (
            <>
              {renderMessages(channelLogs)}
              <WorkingIndicator workingAgents={workingAgents} typingAgents={typingAgents} />
              <div ref={bottomRef} />
            </>
          )}
        </div>
      </div>

      {/* 하단 입력창 */}
      <div className="py-3 md:py-4 bg-white dark:bg-gray-900
        border-t border-gray-200 dark:border-gray-800">
        <div className="max-w-3xl mx-auto px-3 md:px-5">

        {/* 이전 작업 참조 태그 */}
        {baseTaskId && (
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
              bg-purple-100 dark:bg-purple-900/30 border border-purple-300 dark:border-purple-700
              text-xs text-purple-700 dark:text-purple-300">
              🔗 이전 작업: {completedTasks.find((t) => t.task_id === baseTaskId)?.instruction?.slice(0, 30) || baseTaskId.slice(0, 8)}...
              <button onClick={() => setBaseTaskId('')}
                className="ml-1 text-purple-400 hover:text-purple-600 dark:hover:text-purple-200
                  cursor-pointer font-bold">✕</button>
            </span>
          </div>
        )}

        {/* 이전 작업 선택 팝업 */}
        {showTaskPicker && (
          <div className="mb-2 p-2 rounded-xl bg-white dark:bg-gray-800
            border border-gray-200 dark:border-gray-700 shadow-lg max-h-60 overflow-y-auto">
            <div className="flex items-center justify-between mb-2 px-1">
              <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">완료된 작업 선택</span>
              <button onClick={() => setShowTaskPicker(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200
                  cursor-pointer text-sm">✕</button>
            </div>
            {completedTasks.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">완료된 작업이 없습니다</p>
            ) : (
              completedTasks.map((t) => (
                <button key={t.task_id}
                  onClick={() => { setBaseTaskId(t.task_id); setShowTaskPicker(false) }}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs cursor-pointer
                    transition-colors mb-0.5
                    ${baseTaskId === t.task_id
                      ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300'
                      : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300'
                    }`}>
                  <p className="font-medium truncate">{t.instruction?.slice(0, 60) || '(지시 없음)'}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">{t.created_at ? new Date(t.created_at).toLocaleDateString('ko-KR') : ''}</p>
                </button>
              ))
            )}
          </div>
        )}

        {/* 첨부파일 미리보기 */}
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {files.map((f, i) => (
              <div key={`${f.name}-${i}`} className="relative group">
                {isImageFile(f.name) && previews[i] ? (
                  // 이미지 썸네일
                  <div className="w-20 h-20 md:w-24 md:h-24 rounded-lg overflow-hidden
                    border border-gray-200 dark:border-gray-700 relative">
                    <img src={previews[i]} alt={f.name}
                      className="w-full h-full object-cover" />
                    <button onClick={() => removeFile(i)}
                      className="absolute top-1 right-1 w-5 h-5 rounded-full
                        bg-black/60 text-white text-xs flex items-center justify-center
                        opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity"
                      aria-label={`${f.name} 제거`}>✕</button>
                  </div>
                ) : (
                  // 일반 파일
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg
                    bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
                    <span className="text-lg">{fileIcon(f.name)}</span>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate max-w-[120px]">{f.name}</p>
                      <p className="text-[10px] text-gray-400">{formatSize(f.size)}</p>
                    </div>
                    <button onClick={() => removeFile(i)}
                      className="text-gray-400 hover:text-red-400 cursor-pointer text-sm ml-1"
                      aria-label={`${f.name} 제거`}>✕</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 입력 영역 */}
        <div className="relative rounded-2xl bg-gray-100 dark:bg-gray-800
          border border-gray-200 dark:border-gray-700
          focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition-shadow">

          <input ref={fileInputRef} type="file" multiple accept="*/*"
            onChange={handleFileChange} className="hidden" />

          <textarea ref={inputRef} value={message}
            onChange={(e) => { setMessage(e.target.value); autoResize(e.target) }}
            onKeyDown={handleKeyDown}
            placeholder={activeChannel === 'all'
              ? '팀에게 메시지 보내기...'
              : `${profile?.character || profile?.name}에게 메시지 보내기...`}
            rows={1}
            className="w-full px-4 pt-3 pb-10 text-sm resize-none bg-transparent
              text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500
              focus:outline-none min-h-[56px] max-h-[200px]"
            aria-label="메시지 입력" disabled={sending} />

          <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
            <div className="flex items-center gap-0.5">
            <button onClick={() => fileInputRef.current?.click()}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
                dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700
                cursor-pointer transition-colors" aria-label="파일 첨부" disabled={sending}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
              </svg>
            </button>
            <button onClick={openTaskPicker}
              className={`p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700
                cursor-pointer transition-colors ${baseTaskId ? 'text-purple-500' : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}`}
              aria-label="이전 작업 참조" title="이전 작업 참조" disabled={sending}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m9.86-3.06a4.5 4.5 0 00-6.364-6.364L6.2 5.55m11.4 7.459l1.757-1.757" />
              </svg>
            </button>
            </div>
            <button onClick={handleSend}
              disabled={sending || (!message.trim() && files.length === 0)}
              className="p-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-30
                text-white transition-colors cursor-pointer disabled:cursor-not-allowed" aria-label="전송">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            </button>
          </div>
        </div>

        <p className="text-[10px] text-gray-400 text-center mt-1.5 hidden md:block">
          Enter로 전송 · Shift+Enter로 줄바꿈
        </p>
        </div>
      </div>
    </>
  )
}


// --- 메시지 렌더링 ---

function renderMessages(logs: LogEntry[]) {
  const elements: React.ReactNode[] = []
  let prevAgent = ''
  let prevTime = ''
  let prevDate = ''

  for (let i = 0; i < logs.length; i++) {
    const log = logs[i]
    const profile = AGENT_PROFILE[log.agent_id] ?? {
      name: log.agent_id, character: log.agent_id, color: 'from-gray-500 to-gray-600', role: '',
    }
    const time = formatTime(log.timestamp)
    const isNewGroup = log.agent_id !== prevAgent || time !== prevTime

    // 시스템/내부 이벤트 — 숨김
    if (isSystemEvent(log)) {
      continue
    }

    // 날짜 구분선
    const currentDate = new Date(log.timestamp).toLocaleDateString('ko-KR', {
      year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
    })
    if (currentDate !== prevDate) {
      elements.push(
        <div key={`date-${currentDate}`} className="flex items-center gap-3 py-4">
          <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          <span className="text-xs text-gray-400 whitespace-nowrap">{currentDate}</span>
          <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
        </div>
      )
      prevDate = currentDate
    }

    // 사용자 메시지 (오른쪽)
    if (log.agent_id === 'user') {
      elements.push(<UserMessage key={log.id ?? i} log={log} time={time} />)
      prevAgent = log.agent_id
      prevTime = time
      continue
    }

    // 에이전트 메시지 (왼쪽)
    const isResponse = log.event_type === 'response'
    if (isNewGroup) {
      elements.push(
        <div key={log.id ?? i} className="flex gap-2 md:gap-3 py-1.5">
          <div className="flex-shrink-0 mt-0.5">
            <div className={`w-8 h-8 md:w-9 md:h-9 rounded-full bg-gradient-to-br ${profile.color}
              flex items-center justify-center shadow-sm overflow-hidden`}>
              {AVATAR_IMG[log.agent_id]
                ? <img src={AVATAR_IMG[log.agent_id]} alt={profile.character}
                    className="w-full h-full object-cover" loading="lazy" />
                : <span className="text-white text-xs font-bold">{profile.name[0]}</span>}
            </div>
          </div>
          <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[80%]">
            <div className="flex items-baseline gap-2 mb-0.5">
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                {profile.character || profile.name}</span>
              <span className="text-[10px] text-gray-400">{profile.role}</span>
              <span className="text-[10px] text-gray-400">{time}</span>
            </div>
            <MessageBubble log={log} isResponse={isResponse} />
          </div>
        </div>
      )
    } else {
      elements.push(
        <div key={log.id ?? i} className="flex gap-3 py-0.5 pl-10 md:pl-12">
          <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[80%]">
            <MessageBubble log={log} isResponse={isResponse} />
          </div>
        </div>
      )
    }
    prevAgent = log.agent_id
    prevTime = time
  }
  return elements
}

// 사용자 메시지 컴포넌트
function UserMessage({ log, time }: { log: LogEntry; time: string }) {
  const fileInfos = (log.data?.files as FileInfo[]) ?? []
  const fileNames = (log.data?.attachments as string[]) ?? []
  const baseTaskId = (log.data?.base_task_id as string) ?? ''
  const baseTaskInstruction = (log.data?.base_task_instruction as string) ?? ''

  return (
    <div className="flex justify-end py-1">
      <div className="max-w-[85%] md:max-w-[70%]">
        <div className="flex items-baseline gap-2 justify-end mb-0.5">
          <span className="text-[10px] text-gray-400">{time}</span>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">나</span>
        </div>

        {/* 이전 작업 참조 태그 */}
        {baseTaskId && (
          <div className="flex justify-end mb-1.5">
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg
              bg-purple-500/80 text-white text-xs">
              🔗 {baseTaskInstruction ? baseTaskInstruction.slice(0, 30) + '...' : '이전 작업 참조'}
            </span>
          </div>
        )}

        {/* 이미지 썸네일 */}
        {fileInfos.filter((f) => f.isImage).map((f, i) => (
          <div key={`img-${i}`} className="mb-1.5 flex justify-end">
            <a href={f.url} target="_blank" rel="noopener noreferrer"
              className="block max-w-[240px] rounded-xl overflow-hidden
                border border-gray-200 dark:border-gray-700">
              <img src={f.url} alt={f.name}
                className="w-full max-h-[300px] object-cover" loading="lazy" />
            </a>
          </div>
        ))}

        {/* 일반 파일 첨부 */}
        {fileInfos.filter((f) => !f.isImage).length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
            {fileInfos.filter((f) => !f.isImage).map((f, i) => (
              <a key={`file-${i}`} href={f.url} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg
                  bg-blue-500/80 text-white text-xs hover:bg-blue-500 transition-colors">
                <span>{fileIcon(f.name)}</span>
                <span className="truncate max-w-[120px]">{f.name}</span>
                <span className="text-blue-200 text-[10px]">{formatSize(f.size)}</span>
              </a>
            ))}
          </div>
        )}

        {/* fileInfos가 없으면 fileNames 폴백 */}
        {fileInfos.length === 0 && fileNames.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
            {fileNames.map((name, i) => (
              <div key={`fn-${i}`} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg
                bg-blue-500/80 text-white text-xs">
                <span>{fileIcon(name)}</span>
                <span className="truncate max-w-[120px]">{name}</span>
              </div>
            ))}
          </div>
        )}

        {/* 텍스트 메시지 */}
        {log.message && (
          <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-md
            text-sm leading-relaxed">
            {linkify(log.message)}
          </div>
        )}
      </div>
    </div>
  )
}

// 에이전트 메시지 버블
function MessageBubble({ log, isResponse }: { log: LogEntry; isResponse: boolean }) {
  const [showReactions, setShowReactions] = useState(false)
  const { updateLogReactions } = useStore()
  const content = log.message.replace(/^\[.*?\]\s*/, '')
  const artifactPaths = (log.data?.artifacts as string[]) ?? []
  const needsInput = !!log.data?.needs_input
  const reactions = (log.data?.reactions as Record<string, string[]>) ?? {}

  async function handleReact(emoji: string) {
    try {
      const res = await fetch(`/api/logs/${log.id}/react`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emoji, user: 'user' }),
      })
      if (res.ok) {
        const data = await res.json()
        updateLogReactions(log.id, data.reactions)
      }
    } catch { /* 무시 */ }
    setShowReactions(false)
  }

  return (
    <div className="group relative">
      <div className={`px-3 md:px-4 py-2.5 rounded-2xl rounded-tl-md text-sm leading-relaxed
        ${needsInput
          ? 'bg-amber-50 dark:bg-amber-900/20 border-2 border-amber-300 dark:border-amber-600 shadow-sm'
          : isResponse
            ? 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-sm'
            : 'bg-gray-100 dark:bg-gray-800/60'
        }`}>
        {needsInput && (
          <div className="flex items-center gap-1.5 mb-2 text-amber-600 dark:text-amber-400">
            <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-amber-200 dark:bg-amber-800/50">
              답변 필요
            </span>
          </div>
        )}
        {isResponse ? (
          <div className="prose dark:prose-invert prose-sm max-w-none">
            <Markdown>{content}</Markdown>
          </div>
        ) : (
          <span className="text-gray-700 dark:text-gray-300">{linkify(content)}</span>
        )}
      </div>

      {/* 리액션 버튼 — 호버 시 표시 */}
      <button
        onClick={() => setShowReactions(!showReactions)}
        className="absolute -top-2 right-0 opacity-0 group-hover:opacity-100 transition-opacity
          p-1 rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700
          shadow-sm cursor-pointer text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </button>

      {/* 리액션 팔레트 */}
      {showReactions && (
        <div className="absolute -top-8 right-0 flex gap-1 p-1 rounded-lg
          bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-lg z-10">
          {REACTION_EMOJIS.map((emoji) => (
            <button key={emoji} onClick={() => handleReact(emoji)}
              className="w-7 h-7 flex items-center justify-center rounded hover:bg-gray-100
                dark:hover:bg-gray-700 cursor-pointer text-sm transition-colors">
              {emoji}
            </button>
          ))}
        </div>
      )}

      {/* 리액션 뱃지 */}
      {Object.keys(reactions).length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {Object.entries(reactions).map(([emoji, users]) => (
            <button key={emoji} onClick={() => handleReact(emoji)}
              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-xs
                bg-gray-100 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600
                hover:bg-gray-200 dark:hover:bg-gray-700 cursor-pointer transition-colors">
              <span>{emoji}</span>
              <span className="text-gray-500 dark:text-gray-400">{users.length}</span>
            </button>
          ))}
        </div>
      )}

      {/* 산출물 파일 카드 */}
      {artifactPaths.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {artifactPaths.map((path, pi) => {
            // task_id/단계명/파일명 → 단계명/파일명 으로 표시
            const parts = path.split('/')
            const name = parts.length >= 3 ? `${parts[parts.length - 2]}/${parts[parts.length - 1]}` : parts.pop() ?? path
            return (
              <a key={pi} href={`/api/artifacts/${path}`} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg
                  bg-gray-100 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600
                  text-xs text-gray-600 dark:text-gray-300
                  hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                <span>{fileIcon(name)}</span>
                <span className="truncate max-w-[250px]">{name}</span>
              </a>
            )
          })}
        </div>
      )}
    </div>
  )
}

// 작업 중 / 입력 중 인디케이터
function WorkingIndicator({ workingAgents, typingAgents }: { workingAgents: Agent[]; typingAgents: Set<string> }) {
  const [now, setNow] = useState(Date.now())

  const hasWorking = workingAgents.length > 0
  const hasTyping = typingAgents.size > 0

  useEffect(() => {
    if (!hasWorking) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [hasWorking])

  if (!hasWorking && !hasTyping) return null

  // 작업 중 표시 (업무 모드)
  if (hasWorking) {
    const names = workingAgents.map((a) => {
      const p = AGENT_PROFILE[a.agent_id]
      return p?.character || p?.name || a.agent_id
    })

    const startedAt = workingAgents[0]?.work_started_at
    const elapsed = startedAt ? Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000)) : 0
    const min = Math.floor(elapsed / 60)
    const sec = elapsed % 60
    const timeStr = min > 0 ? `${min}분 ${sec}초` : `${sec}초`

    const statusText = workingAgents[0]?.status === 'meeting' ? '회의 중' : '작업 중'

    let text = ''
    if (names.length === 1) {
      text = `${names[0]} ${statusText}`
    } else if (names.length <= 3) {
      text = `${names.join(', ')} ${statusText}`
    } else {
      text = `${names[0]} 외 ${names.length - 1}명 ${statusText}`
    }

    return (
      <div className="flex items-center gap-2 py-2 pl-12">
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
        <span className="text-xs text-gray-400">{text} ({timeStr})</span>
      </div>
    )
  }

  // 입력 중 표시 (대화 모드)
  const typingNames = Array.from(typingAgents).map((id) => {
    const p = AGENT_PROFILE[id]
    return p?.character || p?.name || id
  })

  let typingText = ''
  if (typingNames.length === 1) {
    typingText = `${typingNames[0]} 입력 중`
  } else if (typingNames.length <= 3) {
    typingText = `${typingNames.join(', ')} 입력 중`
  } else {
    typingText = `${typingNames[0]} 외 ${typingNames.length - 1}명 입력 중`
  }

  return (
    <div className="flex items-center gap-2 py-2 pl-12">
      <div className="flex gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
      <span className="text-xs text-gray-400">{typingText}...</span>
    </div>
  )
}
