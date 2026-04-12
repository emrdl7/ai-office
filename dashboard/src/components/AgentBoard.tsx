// 에이전트 상태 보드 (DASH-02)
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { Agent } from '../types'

// 미생 캐릭터 아바타 이미지
const AVATAR_IMG: Record<string, string> = {
  claude: '/avatars/teamlead.png', teamlead: '/avatars/teamlead.png',
  planner: '/avatars/planner.png',
  designer: '/avatars/designer.png',
  developer: '/avatars/developer.png',
  qa: '/avatars/qa.png',
}

// 미생 캐릭터명 + 직급
const AGENT_INFO: Record<string, { character: string; role: string }> = {
  claude: { character: '잡스', role: '팀장' },
  planner: { character: '드러커', role: '기획자' },
  designer: { character: '아이브', role: '디자이너' },
  developer: { character: '튜링', role: '개발자' },
  qa: { character: '데밍', role: 'QA' },
}

// 캐릭터 배경 그라데이션
const AGENT_GRADIENT: Record<string, string> = {
  claude: 'from-slate-600 to-slate-800',
  planner: 'from-blue-500 to-blue-700',
  designer: 'from-rose-400 to-pink-600',
  developer: 'from-emerald-500 to-teal-700',
  qa: 'from-amber-500 to-orange-600',
}

// 에이전트별 사용 모델
const AGENT_MODELS: Record<string, string> = {
  claude: 'Claude CLI',
  planner: 'Gemma (Ollama)',
  designer: 'Gemma (Ollama)',
  developer: 'OpenCode (Cloud)',
  qa: 'Gemma (Ollama)',
}

async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error('에이전트 상태 로드 실패')
  return res.json() as Promise<Agent[]>
}

// 상태별 스타일
function statusStyles(status: string): { dot: string; label: string } {
  switch (status) {
    case 'working':
      return { dot: 'bg-blue-400 animate-pulse', label: '작업 중' }
    case 'done':
      return { dot: 'bg-green-400', label: '완료' }
    case 'error':
      return { dot: 'bg-red-400', label: '오류' }
    case 'waiting':
      return { dot: 'bg-yellow-400', label: '대기' }
    default:
      return { dot: 'bg-gray-400', label: '유휴' }
  }
}

const DEFAULT_AGENTS: Agent[] = [
  { agent_id: 'claude', status: 'idle' },
  { agent_id: 'planner', status: 'idle' },
  { agent_id: 'designer', status: 'idle' },
  { agent_id: 'developer', status: 'idle' },
  { agent_id: 'qa', status: 'idle' },
]

export function AgentBoard() {
  const { data: agents = DEFAULT_AGENTS } = useQuery({
    queryKey: ['agents'],
    queryFn: fetchAgents,
    refetchInterval: 2000,
  })

  const logs = useStore((s) => s.logs)

  // 각 에이전트의 마지막 로그 메시지
  const lastMessage = (agentId: string): string => {
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].agent_id === agentId) {
        return logs[i].message
      }
    }
    return ''
  }

  return (
    <section aria-label="에이전트 상태 보드">
      <h2 className="text-xs font-semibold uppercase tracking-wider mb-3 opacity-60">
        구성원
      </h2>
      <ul className="space-y-1.5" role="list" aria-label="에이전트 목록">
        {agents.map((agent) => {
          const styles = statusStyles(agent.status)
          const info = AGENT_INFO[agent.agent_id] ?? { character: agent.agent_id, role: '' }
          const gradient = AGENT_GRADIENT[agent.agent_id] ?? 'from-gray-500 to-gray-600'
          const msg = lastMessage(agent.agent_id)
          return (
            <li
              key={agent.agent_id}
              className="px-3 py-2 rounded-lg
                bg-gray-50 dark:bg-gray-800/50
                border border-gray-200 dark:border-gray-700"
              aria-label={`${info.character}(${info.role}) — ${styles.label}`}
            >
              <div className="flex items-center gap-2.5">
                <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center shadow-sm flex-shrink-0 overflow-hidden`}>
                  {AVATAR_IMG[agent.agent_id]
                    ? <img src={AVATAR_IMG[agent.agent_id]} alt={info.character}
                        className="w-full h-full object-cover" loading="lazy" />
                    : <span className="text-white text-xs font-bold">{info.character[0]}</span>}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                      {info.character}
                    </span>
                    <span className="text-[10px] text-gray-400">({info.role})</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${styles.dot}`} />
                    <span className="text-[10px] text-gray-400">{styles.label}</span>
                    <span className="text-[10px] text-purple-500 dark:text-purple-400 font-mono">
                      {AGENT_MODELS[agent.agent_id] ?? ''}
                    </span>
                  </div>
                </div>
              </div>
              {msg && (
                <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1 truncate pl-12">
                  {msg.replace(/^\[.*?\]\s*/, '').slice(0, 60)}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
