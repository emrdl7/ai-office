import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { LogEntry } from '../types'

const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/logs`

interface Props {
  addLog: (log: LogEntry) => void
  setLogs: (logs: LogEntry[]) => void
}

export function useChatWebSocket({ addLog, setLogs }: Props) {
  const qc = useQueryClient()
  const [connected, setConnected] = useState(false)
  const [typingAgents, setTypingAgents] = useState<Set<string>>(new Set())
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const typingTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    fetch('/api/ws-token').then(r => r.json()).then(({ token }) => {
      const ws = new WebSocket(`${WS_BASE}?token=${token}`)
      wsRef.current = ws
      ws.onopen = () => {
        setConnected(true)
        fetch('/api/logs/history?limit=200')
          .then((r) => r.json())
          .then((data: LogEntry[]) => {
            if (!Array.isArray(data) || data.length === 0) return
            const hiddenBefore = localStorage.getItem('logsHiddenBefore') || ''
            const filtered = hiddenBefore
              ? data.filter((l) => (l.timestamp || '') > hiddenBefore)
              : data
            if (filtered.length > 0) setLogs(filtered)
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
          if (log.event_type === 'status_change') {
            qc.invalidateQueries({ queryKey: ['agents'] })
            return
          }
          if (log.event_type === 'reaction_update' || log.event_type === 'project_close') {
            return
          }
          if (log.event_type === 'project_update') {
            addLog(log)
            return
          }
          if (log.event_type === 'typing') {
            clearTimeout(typingTimers.current.get(log.agent_id))
            setTypingAgents((prev) => new Set(prev).add(log.agent_id))
            typingTimers.current.set(log.agent_id, setTimeout(() => {
              setTypingAgents((prev) => {
                const next = new Set(prev)
                next.delete(log.agent_id)
                return next
              })
              typingTimers.current.delete(log.agent_id)
            }, 15000))
          } else {
            setTypingAgents((prev) => {
              const next = new Set(prev)
              next.delete(log.agent_id)
              return next
            })
            addLog(log)
          }
        } catch { /* 무시 */ }
      }
    }).catch(() => {})
  }, [addLog, qc, setLogs])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      typingTimers.current.forEach(clearTimeout)
      typingTimers.current.clear()
      wsRef.current?.close()
    }
  }, [connect])

  return { connected, typingAgents }
}
