import { useEffect, useState } from 'react'
import { AGENT_PROFILE } from '../../config/team'
import type { Agent } from '../../types'

interface Props {
  workingAgents: Agent[]
  typingAgents: Set<string>
}

export function WorkingIndicator({ workingAgents, typingAgents }: Props) {
  const [now, setNow] = useState(Date.now())
  const hasWorking = workingAgents.length > 0
  const hasTyping = typingAgents.size > 0

  useEffect(() => {
    if (!hasWorking) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [workingAgents.length])

  if (!hasWorking && !hasTyping) return null

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
    const text = names.length === 1
      ? `${names[0]} ${statusText}`
      : names.length <= 3
        ? `${names.join(', ')} ${statusText}`
        : `${names[0]} 외 ${names.length - 1}명 ${statusText}`

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

  const typingNames = Array.from(typingAgents).map((id) => {
    const p = AGENT_PROFILE[id]
    return p?.character || p?.name || id
  })
  const typingText = typingNames.length === 1
    ? `${typingNames[0]} 입력 중`
    : typingNames.length <= 3
      ? `${typingNames.join(', ')} 입력 중`
      : `${typingNames[0]} 외 ${typingNames.length - 1}명 입력 중`

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
