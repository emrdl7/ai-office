// 채팅방 — 메신저 대화 UI + 파일첨부 + 이미지 썸네일 + 링크 프리뷰
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import { AGENT_PROFILE } from '../config/team'
import { MatIcon } from './icons'
import type { Agent, Job } from '../types'
import { useChatWebSocket } from '../hooks/useChatWebSocket'
import { useFileAttachment } from '../hooks/useFileAttachment'
import { MessageList } from './chat/MessageList'
import { WorkingIndicator } from './chat/WorkingIndicator'
import { filterLogs, fileIcon, formatSize, isImageFile, AVATAR_IMG } from './chat/chatUtils'

async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) return []
  return res.json()
}

async function fetchJobs(): Promise<Job[]> {
  const res = await fetch('/api/jobs?limit=20')
  if (!res.ok) return []
  return res.json()
}

export function ChatRoom({ onMenuClick }: { onMenuClick?: () => void }) {
  const { logs, addLog, setLogs, activeChannel, searchQuery, setSearchQuery } = useStore()

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: fetchAgents,
    staleTime: 10000,
  })
  const { data: jobs = [] } = useQuery({
    queryKey: ['jobs', 'chat-active-strip'],
    queryFn: fetchJobs,
    refetchInterval: 5000,
  })
  const workingAgents = agents.filter((a) => a.status === 'working' || a.status === 'meeting')
  const activeJobs = jobs.filter((job) => ['queued', 'running', 'waiting_gate'].includes(job.status)).slice(0, 3)

  const { connected, typingAgents } = useChatWebSocket({ addLog, setLogs })
  const { files, previews, fileInputRef, addFiles, handleFileChange, handlePaste, removeFile, clearFiles } = useFileAttachment()

  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [lightbox, setLightbox] = useState<string | null>(null)
  const [showSearch, setShowSearch] = useState(false)
  const sendLock = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const isInitialLoad = useRef(true)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: isInitialLoad.current ? 'instant' : 'smooth' })
    if (isInitialLoad.current && logs.length > 0) isInitialLoad.current = false
  }, [logs, activeChannel])

  function autoResize(el: HTMLTextAreaElement) {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    setIsDragging(true)
  }
  function handleDragLeave(e: React.DragEvent) {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragging(false)
  }
  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragging(false)
    addFiles(Array.from(e.dataTransfer.files))
  }

  async function handleSend() {
    if (sendLock.current) return
    if (!message.trim() && files.length === 0) return
    sendLock.current = true
    setSending(true)
    try {
      const form = new FormData()
      form.append('message', message.trim())
      form.append('to', 'all')
      for (const f of files) form.append('files', f)
      await fetch('/api/chat', { method: 'POST', body: form })
      setMessage('')
      clearFiles()
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

  const channelLogs = filterLogs(logs, activeChannel).filter(
    (log) => !searchQuery || log.message.toLowerCase().includes(searchQuery.toLowerCase())
  )
  const profile = AGENT_PROFILE[activeChannel]
  const channelTitle = activeChannel === 'all'
    ? '# TALK'
    : `${profile?.character || profile?.name || activeChannel}`

  return (
    <>
      {/* 이미지 라이트박스 */}
      {lightbox && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="확대 이미지"
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()} />
          <button className="absolute top-4 right-4 text-white/70 hover:text-white text-3xl cursor-pointer"
            onClick={() => setLightbox(null)}>&times;</button>
        </div>
      )}

      {/* 헤더 */}
      <header className="flex items-center justify-between px-4 md:px-5 h-[64px] shrink-0
        glass-panel border-x-0 border-t-0 rounded-none">
        <div className="flex items-center gap-3">
          <button onClick={onMenuClick}
            className="md:hidden p-1.5 rounded-lg text-gray-500 hover:bg-gray-100
              dark:hover:bg-gray-800 cursor-pointer"
            aria-label="메뉴">
            <MatIcon name="menu" className="text-[20px]" />
          </button>
          {activeChannel !== 'all' && AVATAR_IMG[activeChannel] && (
            <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${profile?.color}
              flex items-center justify-center overflow-hidden`}>
              <img src={AVATAR_IMG[activeChannel]} alt={profile?.character}
                className="w-full h-full object-cover" />
            </div>
          )}
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">{channelTitle}</h2>
              <span className={`hidden sm:inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold
                ${connected ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300' : 'bg-slate-500/15 text-slate-500'}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'bg-emerald-400' : 'bg-slate-400'}`} />
                {connected ? 'LIVE' : 'OFFLINE'}
              </span>
            </div>
            {activeChannel !== 'all' && profile && (
              <p className="text-[11px] text-gray-500">{profile.role}</p>
            )}
            {activeChannel === 'all' && (
              <p className="text-[11px] text-slate-500 dark:text-slate-400">대화로 업무를 만들고 실행 흐름을 관제합니다</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setShowSearch(!showSearch); if (showSearch) setSearchQuery('') }}
            className={`p-1.5 rounded-lg transition-colors cursor-pointer
              ${showSearch ? 'text-blue-500 bg-blue-50 dark:bg-blue-900/30' : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}`}
            aria-label="검색" title="대화 검색">
            <MatIcon name="search" className="text-[16px]" />
          </button>
          <button
            onClick={() => {
              localStorage.setItem('logsHiddenBefore', new Date().toISOString())
              setLogs([])
            }}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
              dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="대화 지우기" title="화면에서 대화 숨기기 (서버 기록은 보존)">
            <MatIcon name="delete_sweep" className="text-[16px]" />
          </button>
          <button onClick={() => window.location.reload()}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
              dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="새로고침" title="새로고침">
            <MatIcon name="refresh" className="text-[16px]" />
          </button>
        </div>
      </header>

      {activeChannel === 'all' && (
        <section className="shrink-0 px-4 md:px-6 py-3 border-b border-slate-200/70 dark:border-slate-800/70">
          <div className="max-w-5xl mx-auto flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-bold text-slate-900 dark:text-white">대화로 업무를 요청하세요</p>
              <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                비서가 요청 내용을 해석해 필요한 페르소나, 스킬, 툴, 실행 방식을 선택합니다.
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">Active Jobs</p>
              <p className="text-2xl font-black text-slate-900 dark:text-white tabular-nums">{activeJobs.length}</p>
            </div>
          </div>
          {activeJobs.length > 0 && (
            <div className="max-w-5xl mx-auto mt-2 flex gap-2 overflow-x-auto no-scrollbar">
              {activeJobs.map((job) => (
                <button
                  key={job.id}
                  onClick={() => useStore.getState().setActiveChannel('jobs')}
                  className="shrink-0 rounded-xl border border-slate-200/80 dark:border-slate-700/80 bg-white/70 dark:bg-slate-900/60 px-3 py-2 text-left hover:border-cyan-400 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${job.status === 'waiting_gate' ? 'bg-amber-400' : job.status === 'running' ? 'bg-cyan-400 animate-pulse' : 'bg-slate-400'}`} />
                    <span className="max-w-[220px] truncate text-xs font-semibold text-slate-700 dark:text-slate-200">{job.title}</span>
                  </div>
                  <p className="mt-0.5 text-[10px] text-slate-400">{job.current_step || job.status}</p>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {/* 검색 바 */}
      {showSearch && (
        <div className="px-4 py-2 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
          <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="대화 검색..."
            className="w-full px-3 py-1.5 text-sm rounded-lg
              bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700
              focus:outline-none focus:ring-2 focus:ring-blue-500
              text-gray-800 dark:text-gray-200 placeholder-gray-400"
            autoFocus />
        </div>
      )}

      {/* 대화 영역 — 입력창 아래까지 확장되어 유리효과가 보임 */}
      <div
        className={`flex-1 overflow-y-auto min-h-0 relative
          bg-transparent
          ${isDragging ? 'ring-2 ring-inset ring-blue-400' : ''}`}
        role="log" aria-live="polite" aria-label="대화"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}>
        {isDragging && (
          <div className="absolute inset-0 z-20 flex items-center justify-center
            bg-blue-500/10 pointer-events-none">
            <div className="flex flex-col items-center gap-2 px-6 py-4 rounded-2xl
              bg-white dark:bg-gray-800 border-2 border-dashed border-blue-400 shadow-lg">
              <MatIcon name="image" className="text-[36px] text-blue-400" />
              <span className="text-sm font-medium text-blue-600 dark:text-blue-400">여기에 놓으세요</span>
            </div>
          </div>
        )}
        <div className="max-w-4xl mx-auto px-3 md:px-6 space-y-1 pt-4 pb-36">
          {channelLogs.length === 0 ? (
            <div className="py-24 md:py-32">
              <div className="command-surface mx-auto max-w-xl rounded-3xl p-6 text-center">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-950 text-white dark:bg-cyan-300 dark:text-slate-950">
                  <MatIcon name="auto_awesome" className="text-[26px]" />
                </div>
                <h3 className="text-lg font-black tracking-tight text-slate-950 dark:text-white">무엇을 맡길까요?</h3>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  {activeChannel === 'all'
                    ? '업무 등록, 일정 관리, 자료 정리, 실행 요청처럼 필요한 내용을 그대로 말하면 됩니다.'
                    : `${profile?.name}에게 메시지를 보내세요.`}
                </p>
              </div>
            </div>
          ) : (
            <>
              <MessageList logs={channelLogs} onImageClick={setLightbox} />
              <WorkingIndicator workingAgents={workingAgents} typingAgents={typingAgents} />
              <div ref={bottomRef} />
            </>
          )}
        </div>

        {/* 입력창 */}
        <div className="sticky bottom-0 px-3 md:px-5 pb-4 pt-2">
          <div className="max-w-3xl mx-auto">
            <input ref={fileInputRef} type="file" multiple accept="*/*"
              onChange={handleFileChange} className="hidden" />

            <div className={`rounded-[28px] px-4 pt-3 pb-2
              backdrop-blur-xl shadow-lg transition-all duration-200 border
              ${message.trim() || files.length > 0
                ? 'bg-white/90 dark:bg-slate-950/90 border-cyan-400/70 dark:border-cyan-400/50 shadow-cyan-500/15'
                : 'bg-white/78 dark:bg-slate-950/78 border-slate-200/70 dark:border-slate-700/60'
              }`}>

              {/* 첨부파일 미리보기 */}
              {files.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-2.5">
                  {files.map((f, i) => (
                    <div key={`${f.name}-${i}`} className="relative group">
                      {isImageFile(f.name) && previews[i] ? (
                        <div className="w-20 h-20 rounded-xl overflow-hidden
                          border border-gray-200/60 dark:border-gray-700/60 relative shadow-sm">
                          <img src={previews[i]} alt={f.name} className="w-full h-full object-cover" />
                          <button onClick={() => removeFile(i)}
                            className="absolute top-1 right-1 w-5 h-5 rounded-full
                              bg-black/60 text-white flex items-center justify-center
                              opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity"
                            aria-label={`${f.name} 제거`}>
                            <MatIcon name="close" className="text-[11px]" />
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 px-3 py-2 rounded-xl
                          bg-black/5 dark:bg-white/5 border border-gray-200/50 dark:border-gray-700/50">
                          <MatIcon name={fileIcon(f.name)} className="text-[18px] text-gray-500" />
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate max-w-[110px]">{f.name}</p>
                            <p className="text-[10px] text-gray-400">{formatSize(f.size)}</p>
                          </div>
                          <button onClick={() => removeFile(i)}
                            className="text-gray-400 hover:text-red-400 cursor-pointer ml-1 transition-colors"
                            aria-label={`${f.name} 제거`}>
                            <MatIcon name="close" className="text-[13px]" />
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <textarea ref={inputRef} value={message}
                onChange={(e) => { setMessage(e.target.value); autoResize(e.target) }}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder={activeChannel === 'all'
                  ? '업무를 맡기거나 질문하세요...'
                  : `${profile?.character || profile?.name}에게 메시지 보내기...`}
                rows={1}
                className="w-full text-sm resize-none bg-transparent
                  text-gray-900 dark:text-gray-100 placeholder-gray-400/60 dark:placeholder-gray-500/70
                  focus:outline-none min-h-[32px] max-h-[200px] leading-relaxed"
                aria-label="메시지 입력" disabled={sending} />

              <div className="flex items-center justify-between pt-1">
                <button onClick={() => fileInputRef.current?.click()}
                  className="p-1.5 rounded-xl text-gray-400 hover:text-gray-600
                    dark:hover:text-gray-300 hover:bg-black/5 dark:hover:bg-white/10
                    cursor-pointer transition-colors"
                  aria-label="파일 첨부" disabled={sending}>
                  <MatIcon name="attach_file" className="text-[18px]" />
                </button>
                <div className="flex items-center gap-2.5">
                  {message.length >= 100 && (
                    <span className={`text-[10px] tabular-nums
                      ${message.length > 1500 ? 'text-red-400' : 'text-gray-400/60'}`}>
                      {message.length.toLocaleString()}
                    </span>
                  )}
                  <button onClick={handleSend}
                    disabled={sending || (!message.trim() && files.length === 0)}
                    aria-label="전송"
                    className={`flex items-center justify-center w-8 h-8 rounded-xl
                      transition-all duration-200 cursor-pointer
                      ${message.trim() || files.length > 0
                        ? 'bg-slate-950 hover:bg-cyan-600 dark:bg-cyan-300 dark:hover:bg-cyan-200 text-white dark:text-slate-950 shadow-sm shadow-cyan-500/30 hover:scale-105 active:scale-95'
                        : 'text-gray-400/40 dark:text-gray-600 cursor-not-allowed'
                      } disabled:opacity-60`}>
                    {sending
                      ? <span className="w-3.5 h-3.5 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                      : <MatIcon name="send" className="text-[15px]" />
                    }
                  </button>
                </div>
              </div>
            </div>

            <p className="text-[10px] text-gray-400/40 text-center mt-1 hidden md:block select-none">
  엔터 전송 · Shift+엔터 줄바꿈
            </p>
          </div>
        </div>
      </div>
    </>
  )
}
