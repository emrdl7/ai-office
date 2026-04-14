// 사이드바 — 팀원 목록 + 채널 선택
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { Agent, ChannelId } from '../types'
import { AGENT_PROFILE, AGENT_IDS, IDLE_COMMENTS as TEAM_IDLE_COMMENTS } from '../config/team'
import { IconClipboard, IconChart, IconRefresh } from './icons'
import { ReactionStatsPanel } from './ReactionStats'

export { AGENT_PROFILE }

// 아바타 이미지 — config/team.ts의 agent_id 기반 자동 생성
const AVATAR_IMG: Record<string, string> = Object.fromEntries(
  AGENT_IDS.map((id) => [id, `/avatars/${id}.png`])
)

// 상태별 아바타 링 스타일
const STATUS_RING: Record<string, string> = {
  working: 'ring-2 ring-blue-400 ring-offset-1 ring-offset-white dark:ring-offset-gray-950',
  meeting: 'ring-2 ring-purple-400 ring-offset-1 ring-offset-white dark:ring-offset-gray-950',
  waiting: 'ring-2 ring-yellow-400/60 ring-offset-1 ring-offset-white dark:ring-offset-gray-950',
  idle: '',
}

// 온라인 상태 점
const STATUS_DOT: Record<string, string> = {
  working: 'bg-blue-400 animate-pulse',
  meeting: 'bg-purple-400 animate-pulse',
  waiting: 'bg-yellow-400',
  idle: 'bg-green-400',
}

// 상태 뱃지
const STATUS_BADGE: Record<string, { text: string; cls: string }> = {
  working: { text: '작업중', cls: 'bg-blue-500/20 text-blue-400' },
  meeting: { text: '회의중', cls: 'bg-purple-500/20 text-purple-400' },
  waiting: { text: '대기', cls: 'bg-yellow-500/20 text-yellow-500' },
  idle: { text: '온라인', cls: 'bg-green-500/20 text-green-500' },
}

// 기본 성격 코멘트 — config/team.ts에서 가져옴
const IDLE_COMMENTS = TEAM_IDLE_COMMENTS

// 경과 시간 훅
function useElapsed(startedAt: string | undefined): string {
  const [elapsed, setElapsed] = useState('')

  useEffect(() => {
    if (!startedAt) { setElapsed(''); return }
    const update = () => {
      const secs = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000)
      if (secs < 60) setElapsed(`${secs}초째`)
      else if (secs < 3600) setElapsed(`${Math.floor(secs / 60)}분째`)
      else setElapsed(`${Math.floor(secs / 3600)}시간째`)
    }
    update()
    const t = setInterval(update, 5000)
    return () => clearInterval(t)
  }, [startedAt])

  return elapsed
}

// 타이핑 점 애니메이션
function TypingDots() {
  return (
    <span className="inline-flex items-center gap-0.5 ml-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1 h-1 rounded-full bg-current animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}

async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error('에이전트 상태 로드 실패')
  return res.json() as Promise<Agent[]>
}

async function fetchDailyQuotes(): Promise<Record<string, string>> {
  const res = await fetch('/api/agents/quotes')
  if (!res.ok) return {}
  return res.json()
}

const DEFAULT_AGENTS: Agent[] = [
  { agent_id: 'teamlead', status: 'idle' },
  { agent_id: 'planner', status: 'idle' },
  { agent_id: 'designer', status: 'idle' },
  { agent_id: 'developer', status: 'idle' },
  { agent_id: 'qa', status: 'idle' },
]

// 에이전트 카드 컴포넌트 (경과 시간 훅을 카드 단위로 분리)
function AgentCard({
  agent,
  isActive,
  dailyQuote,
  onClick,
}: {
  agent: Agent
  isActive: boolean
  dailyQuote: string
  onClick: () => void
}) {
  const profile = AGENT_PROFILE[agent.agent_id]
  if (!profile) return null

  const elapsed = useElapsed(
    agent.status === 'working' || agent.status === 'meeting' ? agent.work_started_at : undefined
  )
  const badge = STATUS_BADGE[agent.status] ?? STATUS_BADGE.idle
  const ring = STATUS_RING[agent.status] ?? ''
  const dot = STATUS_DOT[agent.status] ?? 'bg-gray-400'

  // 한마디 결정 로직
  let comment = ''
  let commentNode: React.ReactNode = null

  if (agent.status === 'working') {
    const parts: string[] = []
    if (agent.current_phase) parts.push(agent.current_phase)
    if (elapsed) parts.push(elapsed)
    comment = parts.join(' · ')
    commentNode = (
      <span className="text-blue-400 text-[11px]">
        {comment} <TypingDots />
      </span>
    )
  } else if (agent.status === 'meeting') {
    comment = elapsed ? `회의 진행 중 · ${elapsed}` : '회의 진행 중'
    commentNode = (
      <span className="text-purple-400 text-[11px]">
        {comment} <TypingDots />
      </span>
    )
  } else if (agent.status === 'waiting') {
    comment = agent.current_phase ? `${agent.current_phase} 대기 중` : '결과 대기 중...'
    commentNode = (
      <span className="text-yellow-500/80 text-[11px]">{comment}</span>
    )
  } else {
    // idle — 오늘의 한마디 (있으면) or 기본 코멘트
    const raw = dailyQuote || IDLE_COMMENTS[agent.agent_id] || ''
    comment = raw
    commentNode = raw ? (
      <span className="text-gray-400 dark:text-gray-500 text-[11px] italic leading-snug">
        "{raw}"
      </span>
    ) : null
  }

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-2 py-2.5 rounded-xl flex items-start gap-2.5
        cursor-pointer transition-all duration-150
        ${isActive
          ? 'bg-blue-600/15 dark:bg-blue-600/20'
          : 'hover:bg-gray-100 dark:hover:bg-gray-800/70'
        }`}
    >
      {/* 아바타 */}
      <div className="relative flex-shrink-0 mt-0.5">
        <div className={`w-9 h-9 rounded-full bg-gradient-to-br ${profile.color}
          flex items-center justify-center overflow-hidden transition-all ${ring}`}>
          {AVATAR_IMG[agent.agent_id] ? (
            <img src={AVATAR_IMG[agent.agent_id]} alt={profile.character}
              className="w-full h-full object-cover" loading="lazy" />
          ) : (
            <span className="text-white text-xs font-bold">{profile.name[0]}</span>
          )}
        </div>
        <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full
          border-2 border-white dark:border-gray-950 ${dot}`} />
      </div>

      {/* 정보 영역 */}
      <div className="flex-1 min-w-0">
        {/* 이름 + 상태 뱃지 */}
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className={`text-sm font-semibold truncate
            ${isActive ? 'text-blue-400' : 'text-gray-900 dark:text-gray-100'}`}>
            {profile.character || profile.name}
          </span>
          <span className={`shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${badge.cls}`}>
            {badge.text}
          </span>
        </div>

        {/* 역할 + 모델 */}
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className="text-[10px] text-gray-400">{profile.role}</span>
          {agent.model && (
            <>
              <span className="text-[10px] text-gray-600 dark:text-gray-600">·</span>
              <span className="text-[10px] text-gray-400 truncate">{agent.model}</span>
            </>
          )}
        </div>

        {/* 한마디 */}
        {commentNode && (
          <div className="leading-tight whitespace-normal break-words">
            {commentNode}
          </div>
        )}
      </div>
    </button>
  )
}

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const { activeChannel, setActiveChannel, toggleTheme, theme, toggleArtifacts, showArtifacts, logs } = useStore()
  const prevLogsLen = useRef(0)
  const [showReactions, setShowReactions] = useState(false)

  function selectChannel(channel: ChannelId) {
    setActiveChannel(channel)
    onClose?.()
  }

  const { data: agents = DEFAULT_AGENTS } = useQuery({
    queryKey: ['agents'],
    queryFn: fetchAgents,
    refetchInterval: 2000,
  })

  // 오늘의 한마디 — 하루 한 번 생성, staleTime 1시간
  const { data: dailyQuotes = {} } = useQuery({
    queryKey: ['daily-quotes'],
    queryFn: fetchDailyQuotes,
    staleTime: 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
    retry: 1,
  })

  // 새 메시지 도착 시 강조 (flash)
  const [flashAgent, setFlashAgent] = useState<string | null>(null)
  useEffect(() => {
    if (logs.length <= prevLogsLen.current) { prevLogsLen.current = logs.length; return }
    const newLog = logs[logs.length - 1]
    if (newLog?.agent_id && newLog.agent_id !== 'user' && newLog.event_type === 'response') {
      setFlashAgent(newLog.agent_id)
      setTimeout(() => setFlashAgent(null), 1200)
    }
    prevLogsLen.current = logs.length
  }, [logs])

  return (
    <aside
      className="w-72 h-full flex-shrink-0 flex flex-col
        bg-white dark:bg-gray-950
        border-r border-gray-200 dark:border-gray-800"
      aria-label="채널 목록"
    >
      {/* 헤더 */}
      <div className="px-4 py-3 flex items-center justify-between border-b border-gray-200 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-bold text-lg">AI</span>
          <h1 className="text-sm font-semibold text-gray-900 dark:text-white">Office</h1>
        </div>
        <div className="flex gap-1">
          <button
            onClick={toggleArtifacts}
            className={`p-1.5 rounded cursor-pointer transition-colors
              ${showArtifacts ? 'bg-blue-600 text-white' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'}`}
            aria-label="산출물 패널 토글"
            title="산출물"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </button>
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="테마 전환"
            title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
          >
            {theme === 'dark' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* 채널 */}
      <div className="px-3 pt-4 pb-2">
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 px-2 mb-1.5">
          채널
        </h3>
        <button
          onClick={() => selectChannel('all')}
          className={`w-full text-left px-3 py-2 rounded-xl text-sm cursor-pointer transition-colors
            flex items-center gap-2
            ${activeChannel === 'all'
              ? 'bg-blue-600/15 text-blue-400 font-medium'
              : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-200'
            }`}
        >
          <span className="text-base">#</span>
          <span>팀 채널</span>
        </button>
      </div>

      {/* 팀원 DM */}
      <div className="px-3 pt-2 flex-1 overflow-y-auto">
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 px-2 mb-1.5">
          팀원
        </h3>
        <ul className="space-y-0.5" role="list">
          {agents.map((agent) => (
            <li
              key={agent.agent_id}
              className={`transition-all duration-300 rounded-xl
                ${flashAgent === agent.agent_id
                  ? 'bg-blue-50 dark:bg-blue-900/20'
                  : ''
                }`}
            >
              <AgentCard
                agent={agent}
                isActive={activeChannel === agent.agent_id}
                dailyQuote={dailyQuotes[agent.agent_id] ?? ''}
                onClick={() => selectChannel(agent.agent_id as ChannelId)}
              />
            </li>
          ))}
        </ul>
      </div>

      {/* 하단 메뉴 */}
      <div className="mt-auto p-3 border-t border-gray-200 dark:border-gray-800 space-y-1">
        <button
          onClick={() => useStore.getState().setShowSuggestions(true)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg
            text-sm text-gray-600 dark:text-gray-400
            hover:bg-gray-100 dark:hover:bg-gray-800
            cursor-pointer transition-colors"
        >
          <IconClipboard className="w-4 h-4" />
          <span>건의게시판</span>
        </button>
        <button
          onClick={() => setShowReactions(true)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg
            text-sm text-gray-600 dark:text-gray-400
            hover:bg-gray-100 dark:hover:bg-gray-800
            cursor-pointer transition-colors"
        >
          <IconChart className="w-4 h-4" />
          <span>리액션 통계</span>
        </button>
        <button
          onClick={async () => {
            if (!confirm('백엔드 서버를 재시작합니다. 5초 내 자동 재연결됩니다. 계속할까요?')) return
            try {
              const r = await fetch('/api/server/restart', { method: 'POST' })
              if (r.status === 409) {
                const err = await r.json().catch(() => ({}))
                if (confirm(`${err.detail || '코드 패치 진행 중'}\n\n그래도 강제 재시작할까요? (작업 중단됨)`)) {
                  await fetch('/api/server/restart?force=true', { method: 'POST' })
                }
              }
            } catch { /* 프로세스 종료로 인한 네트워크 에러 무시 */ }
          }}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg
            text-sm text-gray-600 dark:text-gray-400
            hover:bg-gray-100 dark:hover:bg-gray-800
            cursor-pointer transition-colors"
          title="백엔드만 재시작 (코드 병합 후 반영용)"
        >
          <IconRefresh className="w-4 h-4" />
          <span>서버 재시작</span>
        </button>
      </div>
      {showReactions && <ReactionStatsPanel onClose={() => setShowReactions(false)} />}
    </aside>
  )
}
