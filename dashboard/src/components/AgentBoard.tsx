// 에이전트 상태 보드 컴포넌트 (DASH-02)
import { useQuery } from '@tanstack/react-query'
import type { Agent } from '../types'

// 에이전트 이름 한글 매핑
const AGENT_NAMES: Record<string, string> = {
  claude: 'Claude 팀장',
  planner: '기획자',
  designer: '디자이너',
  developer: '개발자',
  qa: 'QA',
}

async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error('에이전트 상태 로드 실패')
  return res.json() as Promise<Agent[]>
}

// 상태별 스타일
function statusStyles(status: string): { dot: string; badge: string; label: string } {
  switch (status) {
    case 'working':
      return {
        dot: 'bg-blue-400 animate-pulse',
        badge: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300',
        label: '작업 중',
      }
    case 'done':
      return {
        dot: 'bg-green-400',
        badge: 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300',
        label: '완료',
      }
    case 'error':
      return {
        dot: 'bg-red-400',
        badge: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300',
        label: '오류',
      }
    default:
      return {
        dot: 'bg-gray-400',
        badge: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400',
        label: '대기 중',
      }
  }
}

// 기본 에이전트 목록 (서버 응답 전 표시용)
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

  return (
    <section aria-label="에이전트 상태 보드">
      <h2 className="text-sm font-semibold uppercase tracking-wider mb-3 opacity-60">
        에이전트 상태
      </h2>
      <ul className="space-y-2" role="list" aria-label="에이전트 목록">
        {agents.map((agent) => {
          const styles = statusStyles(agent.status)
          const displayName = AGENT_NAMES[agent.agent_id] ?? agent.agent_id
          return (
            <li
              key={agent.agent_id}
              className="flex items-center gap-3 px-3 py-2 rounded-lg
                bg-gray-50 dark:bg-gray-800/50
                border border-gray-200 dark:border-gray-700"
              aria-label={`${displayName} — ${styles.label}`}
            >
              {/* 상태 점 */}
              <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${styles.dot}`} />

              {/* 에이전트 이름 */}
              <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-200">
                {displayName}
              </span>

              {/* 상태 배지 */}
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles.badge}`}
              >
                {styles.label}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
