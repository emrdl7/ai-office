// 비서 표시 설정. 내부 실행 역할은 화면에 노출하지 않는다.

export interface Member {
  agent_id: string
  display_name: string        // 화면 표시 이름
  full_name: string           // 전체 표시 이름
  role_ko: string             // 한국어 역할명
  role_short: string          // 사이드바 축약
  persona?: string
  idle_comment: string
  fallback_quote?: string
  color: string               // tailwind gradient classes
}

// Tailwind JIT가 dynamic class를 잡지 못하므로 여기 명시적으로 문자열 상수.
export const TEAM: Member[] = [
  {
    agent_id: 'teamlead',
    display_name: '비서',
    full_name: 'AI Office 비서',
    role_ko: '비서',
    role_short: '업무 비서',
    idle_comment: '지시 대기 중',
    color: 'from-slate-600 to-slate-800',
  },
  {
    agent_id: 'planner',
    display_name: '비서',
    full_name: 'AI Office 비서',
    role_ko: '비서',
    role_short: '업무 비서',
    idle_comment: '정리 중',
    color: 'from-blue-500 to-blue-700',
  },
  {
    agent_id: 'designer',
    display_name: '비서',
    full_name: 'AI Office 비서',
    role_ko: '비서',
    role_short: '업무 비서',
    idle_comment: '정리 중',
    color: 'from-rose-400 to-pink-600',
  },
  {
    agent_id: 'developer',
    display_name: '비서',
    full_name: 'AI Office 비서',
    role_ko: '비서',
    role_short: '업무 비서',
    idle_comment: '작업 중',
    color: 'from-emerald-500 to-teal-700',
  },
  {
    agent_id: 'qa',
    display_name: '비서',
    full_name: 'AI Office 비서',
    role_ko: '비서',
    role_short: '업무 비서',
    idle_comment: '확인 중',
    color: 'from-amber-500 to-orange-600',
  },
]

export const SPECIAL_MEMBERS: Record<string, { name: string; character: string; color: string; role: string }> = {
  user: { name: '나', character: '', color: 'from-green-500 to-emerald-600', role: '' },
  system: { name: '시스템', character: '', color: 'from-gray-500 to-gray-600', role: '' },
  meeting: { name: '처리', character: '', color: 'from-gray-500 to-gray-600', role: '' },
  orchestrator: { name: '시스템', character: '', color: 'from-gray-500 to-gray-600', role: '' },
}

// 레거시 AGENT_PROFILE 호환 — Sidebar, ChatRoom 등 기존 코드가 이 shape에 의존.
export const AGENT_PROFILE: Record<
  string,
  { name: string; character: string; color: string; role: string }
> = (() => {
  const out: Record<string, { name: string; character: string; color: string; role: string }> = {
    ...SPECIAL_MEMBERS,
  }
  for (const m of TEAM) {
    out[m.agent_id] = {
      name: m.role_ko,
      character: m.display_name,
      color: m.color,
      role: m.role_short,
    }
  }
  return out
})()

export const IDLE_COMMENTS: Record<string, string> = Object.fromEntries(
  TEAM.map((m) => [m.agent_id, m.idle_comment]),
)

export const AGENT_IDS: string[] = TEAM.map((m) => m.agent_id)

export function displayName(agentId: string): string {
  return TEAM.find((m) => m.agent_id === agentId)?.display_name ?? agentId
}
