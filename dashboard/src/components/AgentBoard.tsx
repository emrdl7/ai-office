// 에이전트 상태 보드 (DASH-02)
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { Agent } from '../types'

// 포켓몬 이미지 URL (PokeAPI 공식 아트워크)
const POKEMON_IMG: Record<string, string> = {
  claude: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/150.png',
  planner: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/65.png',
  designer: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/38.png',
  developer: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/6.png',
  qa: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/80.png',
}

// 포켓몬 이름 + 직급
const AGENT_INFO: Record<string, { pokemon: string; role: string }> = {
  claude: { pokemon: '뮤츠', role: '팀장' },
  planner: { pokemon: '알라카짐', role: '기획자' },
  designer: { pokemon: '나시', role: '디자이너' },
  developer: { pokemon: '리자몽', role: '개발자' },
  qa: { pokemon: '야도란', role: 'QA' },
}

// 포켓몬 배경 그라데이션
const AGENT_GRADIENT: Record<string, string> = {
  claude: 'from-purple-500 to-purple-700',
  planner: 'from-blue-500 to-blue-700',
  designer: 'from-orange-400 to-pink-500',
  developer: 'from-orange-500 to-red-600',
  qa: 'from-yellow-500 to-amber-600',
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
          const info = AGENT_INFO[agent.agent_id] ?? { pokemon: agent.agent_id, role: '' }
          const gradient = AGENT_GRADIENT[agent.agent_id] ?? 'from-gray-500 to-gray-600'
          const msg = lastMessage(agent.agent_id)
          return (
            <li
              key={agent.agent_id}
              className="px-3 py-2 rounded-lg
                bg-gray-50 dark:bg-gray-800/50
                border border-gray-200 dark:border-gray-700"
              aria-label={`${info.pokemon}(${info.role}) — ${styles.label}`}
            >
              <div className="flex items-center gap-2.5">
                <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center shadow-sm overflow-hidden flex-shrink-0`}>
                  <img
                    src={POKEMON_IMG[agent.agent_id]}
                    alt={info.pokemon}
                    className="w-7 h-7 object-contain"
                    loading="lazy"
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                      {info.pokemon}
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
