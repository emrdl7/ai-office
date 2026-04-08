// 실시간 채팅 스트림 — Slack 스타일 메신저 UI (DASH-03)
import { useEffect, useRef, useState, useCallback } from 'react'
import { useStore } from '../store'
import type { LogEntry } from '../types'

// 미생 캐릭터 아바타 이미지
const AVATAR_IMG: Record<string, string> = {
  claude: '/avatars/teamlead.png', teamlead: '/avatars/teamlead.png',
  planner: '/avatars/planner.png',
  designer: '/avatars/designer.png',
  developer: '/avatars/developer.png',
  qa: '/avatars/qa.png',
}

// 에이전트별 미생 캐릭터 프로필
const AGENT_PROFILE: Record<string, { name: string; character: string; color: string; role: string; personality: string }> = {
  claude: { name: '팀장', character: '오상식', color: 'from-slate-600 to-slate-800', role: '분석·검수', personality: '원칙주의 리더' },
  planner: { name: '기획자', character: '장그래', color: 'from-blue-500 to-blue-700', role: '태스크 분해', personality: '끈기의 수읽기' },
  designer: { name: '디자이너', character: '안영이', color: 'from-rose-400 to-pink-600', role: 'UI/UX 설계', personality: '외유내강 프로' },
  developer: { name: '개발자', character: '김동식', color: 'from-emerald-500 to-teal-700', role: '코드 구현', personality: '묵묵한 실력파' },
  qa: { name: 'QA', character: '한석율', color: 'from-amber-500 to-orange-600', role: '품질 검수', personality: '냉철한 분석가' },
  orchestrator: { name: '시스템', character: '시스템', color: 'from-gray-500 to-gray-600', role: '', personality: '' },
  system: { name: '시스템', character: '시스템', color: 'from-gray-500 to-gray-600', role: '', personality: '' },
}

// 이벤트 타입별 메시지 스타일
const EVENT_STYLE: Record<string, { badge?: string; tone?: string }> = {
  task_start: { badge: '시작', tone: 'text-blue-400' },
  task_end: { badge: '완료', tone: 'text-green-400' },
  task_fail: { badge: '실패', tone: 'text-red-400' },
  error: { badge: '오류', tone: 'text-red-400' },
  status_change: { badge: '상태변경', tone: 'text-gray-400' },
  message: { tone: 'text-gray-300' },
  log: { tone: 'text-gray-300' },
}

// WebSocket URL
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/logs`

type ConnState = 'connecting' | 'open' | 'closed'
const STATE_LABELS: Record<ConnState, string> = {
  connecting: '연결 중...',
  open: '연결됨',
  closed: '연결 끊김',
}

// 메시지 내용 파싱 — [태그] 제거하고 실제 내용만 추출
function parseMessage(raw: string): { tag: string; content: string } {
  const match = raw.match(/^\[([^\]]+)\]\s*(.*)/)
  if (match) {
    return { tag: match[1], content: match[2] }
  }
  return { tag: '', content: raw }
}

// 시간 포맷
function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function LogStream() {
  const { logs, addLog, setLogs } = useStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [connState, setConnState] = useState<ConnState>('closed')
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  // WebSocket 연결
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    setConnState('connecting')
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen = () => setConnState('open')
    ws.onclose = () => {
      setConnState('closed')
      reconnectTimer.current = setTimeout(connect, 2000)
    }
    ws.onmessage = (event) => {
      try {
        const log = JSON.parse(event.data) as LogEntry
        addLog(log)
      } catch {
        // JSON 파싱 실패 시 무시
      }
    }
  }, [addLog])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  // 마운트 시 히스토리 복구
  useEffect(() => {
    fetch('/api/logs/history?limit=100')
      .then((res) => res.json())
      .then((data: LogEntry[]) => {
        if (Array.isArray(data) && data.length > 0) {
          setLogs(data)
        }
      })
      .catch(() => {})
  }, [setLogs])

  // 자동 스크롤
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const isConnected = connState === 'open'
  const statusLabel = STATE_LABELS[connState]

  // 연속된 같은 에이전트 메시지 그룹화
  function renderMessages() {
    const elements: React.ReactNode[] = []
    let prevAgent = ''
    let prevTime = ''

    for (let i = 0; i < logs.length; i++) {
      const log = logs[i]
      const profile = AGENT_PROFILE[log.agent_id] ?? { name: log.agent_id, emoji: '🤖', color: 'bg-gray-500', role: '' }
      const style = EVENT_STYLE[log.event_type] ?? {}
      const { content } = parseMessage(log.message)
      const time = formatTime(log.timestamp)
      const isNewGroup = log.agent_id !== prevAgent || time !== prevTime

      // 시스템 상태 변경은 간소화
      if (log.event_type === 'status_change') {
        elements.push(
          <div key={log.id ?? i} className="flex items-center justify-center py-1">
            <span className="text-[10px] text-gray-500 italic">{content}</span>
          </div>
        )
        prevAgent = log.agent_id
        prevTime = time
        continue
      }

      if (isNewGroup) {
        // 새 그룹 — 아바타 + 이름 + 시간
        elements.push(
          <div key={log.id ?? i} className="flex gap-3 py-1.5 group">
            <div className="flex-shrink-0 mt-0.5">
              <div className={`w-9 h-9 rounded-full bg-gradient-to-br ${profile.color} flex items-center justify-center shadow-sm overflow-hidden`}>
                {AVATAR_IMG[log.agent_id]
                  ? <img src={AVATAR_IMG[log.agent_id]} alt={profile.character}
                      className="w-full h-full object-cover" loading="lazy" />
                  : <span className="text-white text-sm font-bold">{profile.name[0]}</span>}
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                  {profile.character}
                </span>
                <span className="text-[10px] text-gray-400">
                  ({profile.name})
                </span>
                <span className="text-[10px] text-gray-400">{time}</span>
                {style.badge && (
                  <span className={`text-[10px] px-1.5 py-0 rounded font-medium
                    ${style.tone === 'text-green-400' ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400' :
                      style.tone === 'text-red-400' ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400' :
                      style.tone === 'text-blue-400' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' :
                      'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'}`}>
                    {style.badge}
                  </span>
                )}
              </div>
              {profile.personality && (
                <p className="text-[10px] text-gray-400 dark:text-gray-500 italic -mt-0.5">
                  {profile.personality}
                </p>
              )}
              <p className={`text-sm leading-relaxed mt-0.5 ${style.tone ?? 'text-gray-300'}`}>
                {content}
              </p>
            </div>
          </div>
        )
      } else {
        // 같은 그룹 — 내용만 추가
        elements.push(
          <div key={log.id ?? i} className="flex gap-3 py-0.5 pl-11">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                {style.badge && (
                  <span className={`text-[10px] px-1.5 py-0 rounded font-medium
                    ${style.tone === 'text-green-400' ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400' :
                      style.tone === 'text-red-400' ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400' :
                      style.tone === 'text-blue-400' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' :
                      'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'}`}>
                    {style.badge}
                  </span>
                )}
              </div>
              <p className={`text-sm leading-relaxed mt-0.5 ${style.tone ?? 'text-gray-300'}`}>
                {content}
              </p>
            </div>
          </div>
        )
      }

      prevAgent = log.agent_id
      prevTime = time
    }

    return elements
  }

  return (
    <section aria-label="실시간 채팅" className="flex flex-col h-full">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider opacity-60">
            # 작업 채널
          </h2>
          <div className="flex items-center gap-1" role="status">
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-gray-400'}`} />
            <span className="text-[10px] opacity-50">{statusLabel}</span>
          </div>
        </div>
      </div>

      {/* 채팅 영역 */}
      <div
        className="flex-1 overflow-y-auto space-y-0
          bg-white dark:bg-gray-900 rounded-lg p-3 min-h-0
          border border-gray-200 dark:border-gray-700"
        role="log"
        aria-live="polite"
        aria-label="에이전트 채팅"
      >
        {logs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-gray-400">
            <p className="text-2xl mb-2 opacity-30">💬</p>
            <p className="text-sm">아직 대화가 없습니다</p>
            <p className="text-xs mt-1 opacity-60">작업을 지시하면 팀원들이 대화를 시작합니다</p>
          </div>
        ) : (
          renderMessages()
        )}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
