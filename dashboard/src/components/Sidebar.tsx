// 사이드바 — 팀원 목록 + 채널 선택
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { Agent, ChannelId } from '../types'

// 포켓몬 아바타
const POKEMON_IMG: Record<string, string> = {
  teamlead: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-viii/icons/150.png',
  planner: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-viii/icons/65.png',
  designer: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-viii/icons/38.png',
  developer: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-viii/icons/6.png',
  qa: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-viii/icons/80.png',
}

export const AGENT_PROFILE: Record<string, { name: string; pokemon: string; color: string; role: string }> = {
  teamlead: { name: '팀장', pokemon: '뮤츠', color: 'from-purple-500 to-purple-700', role: '총괄' },
  planner: { name: '기획자', pokemon: '알라카짐', color: 'from-blue-500 to-blue-700', role: '기획/PM' },
  designer: { name: '디자이너', pokemon: '나인테일', color: 'from-orange-400 to-pink-500', role: 'UI/UX' },
  developer: { name: '개발자', pokemon: '리자몽', color: 'from-orange-500 to-red-600', role: '개발' },
  qa: { name: 'QA', pokemon: '야도란', color: 'from-yellow-500 to-amber-600', role: '검수' },
  user: { name: '나', pokemon: '', color: 'from-green-500 to-emerald-600', role: '' },
  system: { name: '시스템', pokemon: '', color: 'from-gray-500 to-gray-600', role: '' },
  meeting: { name: '회의', pokemon: '', color: 'from-gray-500 to-gray-600', role: '' },
  orchestrator: { name: '시스템', pokemon: '', color: 'from-gray-500 to-gray-600', role: '' },
}

// 상태별 온라인 표시
function statusDot(status: string): string {
  switch (status) {
    case 'working': return 'bg-blue-400 animate-pulse'
    case 'meeting': return 'bg-purple-400 animate-pulse'
    case 'waiting': return 'bg-yellow-400'
    default: return 'bg-gray-400'
  }
}

async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error('에이전트 상태 로드 실패')
  return res.json() as Promise<Agent[]>
}

const DEFAULT_AGENTS: Agent[] = [
  { agent_id: 'teamlead', status: 'idle' },
  { agent_id: 'planner', status: 'idle' },
  { agent_id: 'designer', status: 'idle' },
  { agent_id: 'developer', status: 'idle' },
  { agent_id: 'qa', status: 'idle' },
]

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const { activeChannel, setActiveChannel, toggleTheme, theme, toggleArtifacts, showArtifacts } = useStore()

  // 채널 선택 시 모바일에서 사이드바 닫기
  function selectChannel(channel: ChannelId) {
    setActiveChannel(channel)
    onClose?.()
  }

  const { data: agents = DEFAULT_AGENTS } = useQuery({
    queryKey: ['agents'],
    queryFn: fetchAgents,
    refetchInterval: 2000,
  })

  const logs = useStore((s) => s.logs)

  // 에이전트의 마지막 메시지
  const lastMsg = (agentId: string): string => {
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].agent_id === agentId && logs[i].event_type !== 'status_change') {
        return logs[i].message.replace(/^\[.*?\]\s*/, '').slice(0, 40)
      }
    }
    return ''
  }

  return (
    <aside
      className="w-64 h-full flex-shrink-0 flex flex-col
        bg-gray-900 dark:bg-gray-950
        border-r border-gray-800"
      aria-label="채널 목록"
    >
      {/* 헤더 */}
      <div className="px-4 py-3 flex items-center justify-between border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-bold text-lg">AI</span>
          <h1 className="text-sm font-semibold text-white">Office</h1>
        </div>
        <div className="flex gap-1">
          <button
            onClick={toggleArtifacts}
            className={`p-1.5 rounded cursor-pointer transition-colors
              ${showArtifacts ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}`}
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
            className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-gray-800
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
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 px-2 mb-1">
          채널
        </h3>
        <button
          onClick={() => selectChannel('all')}
          className={`w-full text-left px-2 py-1.5 rounded text-sm cursor-pointer transition-colors
            ${activeChannel === 'all'
              ? 'bg-blue-600/20 text-blue-300'
              : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            }`}
        >
          # 팀 채널
        </button>
      </div>

      {/* 팀원 DM */}
      <div className="px-3 pt-2 flex-1 overflow-y-auto">
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 px-2 mb-1">
          팀원
        </h3>
        <ul className="space-y-0.5" role="list">
          {agents.map((agent) => {
            const profile = AGENT_PROFILE[agent.agent_id]
            if (!profile) return null
            const isActive = activeChannel === agent.agent_id
            const msg = lastMsg(agent.agent_id)

            return (
              <li key={agent.agent_id}>
                <button
                  onClick={() => selectChannel(agent.agent_id as ChannelId)}
                  className={`w-full text-left px-2 py-2 rounded flex items-center gap-2.5
                    cursor-pointer transition-colors
                    ${isActive
                      ? 'bg-blue-600/20 text-blue-300'
                      : 'text-gray-300 hover:bg-gray-800'
                    }`}
                >
                  {/* 아바타 */}
                  <div className="relative flex-shrink-0">
                    <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${profile.color}
                      flex items-center justify-center overflow-hidden`}>
                      {POKEMON_IMG[agent.agent_id] ? (
                        <img
                          src={POKEMON_IMG[agent.agent_id]}
                          alt={profile.pokemon}
                          className="w-7 h-7 object-contain scale-[1.6]"
                          loading="lazy"
                        />
                      ) : (
                        <span className="text-white text-xs font-bold">
                          {profile.name[0]}
                        </span>
                      )}
                    </div>
                    {/* 온라인 상태 표시 */}
                    <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full
                      border-2 border-gray-900 ${statusDot(agent.status)}`} />
                  </div>

                  {/* 이름 + 모델 */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-sm font-medium">{profile.pokemon || profile.name}</span>
                      <span className="text-[10px] text-gray-500">{profile.role}</span>
                    </div>
                    {agent.model && (
                      <p className="text-[10px] text-gray-500 truncate">{agent.model}</p>
                    )}
                    {msg && (
                      <p className="text-[11px] text-gray-500 truncate">{msg}</p>
                    )}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </aside>
  )
}
