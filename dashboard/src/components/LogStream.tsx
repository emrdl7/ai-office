// 실시간 로그 스트림 컴포넌트 (DASH-03)
import { useEffect, useRef } from 'react'
import useWebSocket, { ReadyState } from 'react-use-websocket'
import { useStore } from '../store'
import type { LogEntry } from '../types'

// 에이전트 ID별 색상
const AGENT_COLORS: Record<string, string> = {
  claude: 'text-purple-400',
  planner: 'text-blue-400',
  designer: 'text-pink-400',
  developer: 'text-green-400',
  qa: 'text-yellow-400',
  system: 'text-gray-400',
}

// 이벤트 타입별 접두사 아이콘 (텍스트)
const EVENT_PREFIX: Record<string, string> = {
  task_start: '[시작]',
  task_end: '[완료]',
  task_fail: '[실패]',
  message: '[메시지]',
  error: '[오류]',
}

// WebSocket URL 결정 (개발: 프록시 경유, 프로덕션: 직접 연결)
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/logs`

// 연결 상태 텍스트
const READY_STATE_LABELS: Record<number, string> = {
  [ReadyState.CONNECTING]: '연결 중...',
  [ReadyState.OPEN]: '연결됨',
  [ReadyState.CLOSING]: '연결 종료 중',
  [ReadyState.CLOSED]: '연결 끊김',
}

export function LogStream() {
  const { logs, addLog, setLogs } = useStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  // WebSocket 연결
  const { readyState } = useWebSocket(WS_URL, {
    onMessage: (event) => {
      try {
        const log = JSON.parse(event.data as string) as LogEntry
        addLog(log)
      } catch {
        // JSON 파싱 실패 시 무시
      }
    },
    shouldReconnect: () => true,    // 자동 재연결
    reconnectAttempts: 10,
    reconnectInterval: 2000,
  })

  // 마운트 시 로그 히스토리 복구
  useEffect(() => {
    fetch('/api/logs/history?limit=100')
      .then((res) => res.json())
      .then((data: LogEntry[]) => {
        if (Array.isArray(data) && data.length > 0) {
          setLogs(data)
        }
      })
      .catch(() => {
        // 히스토리 로드 실패는 무시 (실시간 로그로 대체)
      })
  }, [setLogs])

  // 새 로그 수신 시 자동 스크롤
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const isConnected = readyState === ReadyState.OPEN
  const statusLabel = READY_STATE_LABELS[readyState] ?? '알 수 없음'

  return (
    <section aria-label="실시간 로그 스트림" className="flex flex-col h-full">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <h2 className="text-sm font-semibold uppercase tracking-wider opacity-60">
          실시간 로그
        </h2>
        <div className="flex items-center gap-1.5" role="status" aria-label={`WebSocket 상태: ${statusLabel}`}>
          <span
            className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-gray-400'}`}
          />
          <span className="text-xs opacity-60">{statusLabel}</span>
        </div>
      </div>

      {/* 로그 목록 */}
      <div
        className="flex-1 overflow-y-auto font-mono text-xs space-y-0.5
          bg-gray-950 dark:bg-black rounded-lg p-3 min-h-0"
        role="log"
        aria-live="polite"
        aria-label="에이전트 로그"
      >
        {logs.length === 0 ? (
          <p className="text-gray-500 italic">로그를 기다리는 중...</p>
        ) : (
          logs.map((log, idx) => {
            const agentColor = AGENT_COLORS[log.agent_id] ?? 'text-gray-300'
            const prefix = EVENT_PREFIX[log.event_type] ?? `[${log.event_type}]`
            const time = new Date(log.timestamp).toLocaleTimeString('ko-KR', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })
            return (
              <div key={log.id ?? idx} className="flex gap-2 leading-relaxed">
                <span className="text-gray-600 flex-shrink-0">{time}</span>
                <span className={`flex-shrink-0 ${agentColor}`}>{log.agent_id}</span>
                <span className="text-gray-500 flex-shrink-0">{prefix}</span>
                <span className="text-gray-300 break-all">{log.message}</span>
              </div>
            )
          })
        )}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
