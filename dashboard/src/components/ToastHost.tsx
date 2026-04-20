// 실시간 알림 토스트 — 주요 이벤트(model_fallback emergency / drift_detected /
// gate_ai_agreement mismatch / job_failed)를 우상단에 표시
import { useEffect, useRef, useState } from 'react'
import { MatIcon } from './icons'

type Tone = 'success' | 'warn' | 'danger' | 'info'

interface Toast {
  id: number
  tone: Tone
  title: string
  body?: string
}

const TONE_STYLE: Record<Tone, string> = {
  success: 'border-emerald-300 dark:border-emerald-700/50 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-800 dark:text-emerald-200',
  warn:    'border-amber-300 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200',
  danger:  'border-red-300 dark:border-red-700/50 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200',
  info:    'border-indigo-300 dark:border-indigo-700/50 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-800 dark:text-indigo-200',
}

const TONE_ICON: Record<Tone, string> = {
  success: 'check_circle',
  warn:    'warning',
  danger:  'error',
  info:    'info',
}

const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/logs`

export function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    let cancelled = false

    const push = (t: Omit<Toast, 'id'>) => {
      const id = Date.now() + Math.random()
      setToasts(prev => [...prev.slice(-4), { id, ...t }])
      setTimeout(() => {
        setToasts(prev => prev.filter(x => x.id !== id))
      }, 8000)
    }

    const connect = () => {
      if (cancelled) return
      fetch('/api/ws-token').then(r => r.json()).then(({ token }) => {
        if (cancelled) return
        const ws = new WebSocket(`${WS_BASE}?token=${token}`)
        wsRef.current = ws
        ws.onmessage = (event) => {
          try {
            const log = JSON.parse(event.data)
            const et = log.event_type as string
            const msg = (log.message as string) || ''
            const data = log.data || {}

            if (et === 'model_fallback' && data.stage === 'emergency') {
              push({ tone: 'warn', title: '모델 비상 폴백', body: msg })
            } else if (et === 'drift_detected') {
              push({ tone: 'warn', title: '페르소나 드리프트 감지', body: msg })
            } else if (et === 'gate_ai_agreement' && data.matched === false) {
              push({
                tone: 'info',
                title: 'Gate AI ↔ 사람 불일치',
                body: `AI=${data.ai_suggestion} / Human=${data.human_decision}`,
              })
            } else if (et === 'job_failed') {
              push({ tone: 'danger', title: 'Job 실패', body: msg.slice(0, 140) })
            } else if (et === 'job_done' && msg.includes('🎉')) {
              push({ tone: 'success', title: 'Job 완료', body: msg.slice(0, 140) })
            }
          } catch {
            // ignore
          }
        }
        ws.onclose = () => {
          if (cancelled) return
          reconnectTimer.current = setTimeout(connect, 3000)
        }
      }).catch(() => {
        if (cancelled) return
        reconnectTimer.current = setTimeout(connect, 5000)
      })
    }

    connect()
    return () => {
      cancelled = true
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [])

  if (toasts.length === 0) return null

  return (
    <div
      className="fixed top-4 right-4 flex flex-col gap-2 pointer-events-none"
      style={{ zIndex: 'var(--z-toast, 60)' as React.CSSProperties['zIndex'] }}
    >
      {toasts.map(t => (
        <div
          key={t.id}
          className={`pointer-events-auto min-w-[260px] max-w-sm rounded-lg border px-3 py-2.5 shadow-lg ${TONE_STYLE[t.tone]} animate-[fadeIn_160ms_ease-out]`}
        >
          <div className="flex items-start gap-2">
            <MatIcon name={TONE_ICON[t.tone]} className="text-[18px] mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold leading-tight">{t.title}</p>
              {t.body && <p className="text-[11px] leading-snug mt-0.5 opacity-90 break-words">{t.body}</p>}
            </div>
            <button
              onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
              className="opacity-60 hover:opacity-100 transition-opacity cursor-pointer"
              aria-label="닫기"
            >
              <MatIcon name="close" className="text-[14px]" />
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
