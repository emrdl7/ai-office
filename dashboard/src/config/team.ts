// 팀 구성 중앙 설정 — 백엔드 /api/team과 동기화하거나 이 파일만 수정
// 백엔드(server/config/team.py)가 단일 소스. 네트워크 없이도 동작하도록 로컬에도 미러링.

export interface Member {
  agent_id: string
  display_name: string        // 짧은 이름 (잡스)
  full_name: string           // 전체 이름 (스티브 잡스)
  role_ko: string             // 한국어 역할명
  role_short: string          // 사이드바 축약 (팀장, 기획/PM, ...)
  persona?: string
  idle_comment: string
  fallback_quote?: string
  color: string               // tailwind gradient classes
}

// Tailwind JIT가 dynamic class를 잡지 못하므로 여기 명시적으로 문자열 상수.
export const TEAM: Member[] = [
  {
    agent_id: 'teamlead',
    display_name: '잡스',
    full_name: '스티브 잡스',
    role_ko: '팀장',
    role_short: '팀장',
    idle_comment: '지시 대기 중',
    color: 'from-slate-600 to-slate-800',
  },
  {
    agent_id: 'planner',
    display_name: '드러커',
    full_name: '피터 드러커',
    role_ko: '기획자',
    role_short: '기획/PM',
    idle_comment: '올바른 질문을 찾는 중',
    color: 'from-blue-500 to-blue-700',
  },
  {
    agent_id: 'designer',
    display_name: '아이브',
    full_name: '조너선 아이브',
    role_ko: '디자이너',
    role_short: '디자인',
    idle_comment: '레퍼런스 분석 중',
    color: 'from-rose-400 to-pink-600',
  },
  {
    agent_id: 'developer',
    display_name: '튜링',
    full_name: '앨런 튜링',
    role_ko: '개발자',
    role_short: '개발',
    idle_comment: '알고리즘 정의 중',
    color: 'from-emerald-500 to-teal-700',
  },
  {
    agent_id: 'qa',
    display_name: '데밍',
    full_name: 'W. 에드워즈 데밍',
    role_ko: 'QA',
    role_short: '검수',
    idle_comment: '프로세스 개선 중',
    color: 'from-amber-500 to-orange-600',
  },
]

// 특수 참여자 (팀원 아님)
export const SPECIAL_MEMBERS: Record<string, { name: string; character: string; color: string; role: string }> = {
  user: { name: '나', character: '', color: 'from-green-500 to-emerald-600', role: '' },
  system: { name: '시스템', character: '', color: 'from-gray-500 to-gray-600', role: '' },
  meeting: { name: '회의', character: '', color: 'from-gray-500 to-gray-600', role: '' },
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
