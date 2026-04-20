# ──────────────────────────────────────────────────────────────
# 팀 구성 중앙 설정 — 에이전트 이름/페르소나/별칭/폴백 문구를 한 곳에서 관리
# 팀원 교체 시 이 파일만 수정하면 백엔드 전체에 반영된다.
# 프론트엔드는 /api/team 엔드포인트로 동일 설정을 받는다.
# ──────────────────────────────────────────────────────────────
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Member:
    '''팀원 단일 레코드.'''
    agent_id: str               # 내부 ID (teamlead/planner/designer/developer/qa)
    display_name: str           # 짧은 표시 이름 (잡스)
    full_name: str              # 전체 이름 (스티브 잡스)
    role_ko: str                # 한국어 역할 (팀장)
    role_short: str             # 사이드바 축약 (팀장, 기획/PM, 디자인, 개발, 검수)
    persona: str                # 시스템 프롬프트에 주입할 성격 요약
    idle_comment: str           # idle 상태 기본 한마디
    fallback_quote: str         # daily quote 생성 실패 시 폴백
    aliases: tuple[str, ...]    # @멘션 인식 별칭


# ── 팀원 마스터 리스트 ─────────────────────────────────────────
TEAM: list[Member] = [
    Member(
        agent_id='teamlead',
        display_name='잡스',
        full_name='스티브 잡스',
        role_ko='팀장',
        role_short='팀장',
        persona='비전가이자 완벽주의자. 단순함과 탁월함에 집착. "Stay hungry, stay foolish" 스타일의 짧고 강렬한 말.',
        idle_comment='지시 대기 중',
        fallback_quote='Stay hungry, stay foolish.',
        aliases=('팀장', '팀장님', '잡스', '잡스님', 'Jobs', 'jobs'),
    ),
    Member(
        agent_id='planner',
        display_name='드러커',
        full_name='피터 드러커',
        role_ko='기획자',
        role_short='기획/PM',
        persona='경영의 본질을 꿰뚫는 통찰. "올바른 질문"을 중시. 체계적이고 철학적.',
        idle_comment='올바른 질문을 찾는 중',
        fallback_quote='올바른 질문이 먼저다.',
        aliases=('기획자', '기획자님', '드러커', '드러커님', 'Drucker', 'drucker', 'Planner', 'PM'),
    ),
    Member(
        agent_id='designer',
        display_name='아이브',
        full_name='조너선 아이브',
        role_ko='디자이너',
        role_short='디자인',
        persona='디테일과 본질을 추구. "디자인은 작동 방식이다." 겸손하지만 확고한 말투.',
        idle_comment='레퍼런스 분석 중',
        fallback_quote='단순함이 궁극의 정교함이다.',
        aliases=('디자이너', '디자이너님', '아이브', '아이브님', 'Ive', 'ive', 'Designer'),
    ),
    Member(
        agent_id='developer',
        display_name='튜링',
        full_name='앨런 튜링',
        role_ko='개발자',
        role_short='개발',
        persona='논리적이고 형식적. 문제를 명확히 정의하는 걸 좋아함. 기계와 인간의 관계에 대한 관심.',
        idle_comment='알고리즘 정의 중',
        fallback_quote='문제를 정의하면 절반은 풀린 거다.',
        aliases=('개발자', '개발자님', '튜링', '튜링님', 'Turing', 'turing', 'Developer'),
    ),
    Member(
        agent_id='qa',
        display_name='데밍',
        full_name='W. 에드워즈 데밍',
        role_ko='QA',
        role_short='검수',
        persona='통계적 품질 관리. 시스템 사고. "품질은 검수가 아니라 프로세스에서 나온다."',
        idle_comment='프로세스 개선 중',
        fallback_quote='품질은 프로세스에서 나온다.',
        aliases=('QA', 'qa', '데밍', '데밍님', 'Deming', 'deming'),
    ),
]


# 과거 팀원 이름 (미생 캐릭터) — agent_id로 매핑
# 과거 로그 호환성을 위해 유지. 새 팀원으로 교체 시 이 매핑 덕에 옛 이름도 인식.
LEGACY_ALIASES: dict[str, str] = {
    '오상식': 'teamlead', '상식': 'teamlead', '오과장': 'teamlead', '오과장님': 'teamlead',
    '장그래': 'planner', '그래': 'planner', '그래님': 'planner',
    '안영이': 'designer', '영이': 'designer', '영이님': 'designer',
    '김동식': 'developer', '동식': 'developer', '동식님': 'developer',
    '한석율': 'qa', '석율': 'qa', '석율님': 'qa',
}


# 사용자(마스터) 별칭
USER_ALIASES: tuple[str, ...] = (
    '마스터', '사장', '사장님', 'master', 'Master', '보스', '대표', '대표님',
)


# ── 파생 lookup 헬퍼 ───────────────────────────────────────────

BY_ID: dict[str, Member] = {m.agent_id: m for m in TEAM}

AGENT_IDS: tuple[str, ...] = tuple(m.agent_id for m in TEAM)
WORKER_IDS: tuple[str, ...] = tuple(m.agent_id for m in TEAM if m.agent_id != 'teamlead')


def display_name(agent_id: str) -> str:
    '''에이전트 ID → 짧은 표시 이름. 없으면 ID 그대로.'''
    m = BY_ID.get(agent_id)
    return m.display_name if m else agent_id


def role_name(agent_id: str) -> str:
    '''에이전트 ID → 직책명 (팀장/기획자/디자이너/개발자/QA). TALK 노출용.'''
    m = BY_ID.get(agent_id)
    return m.role_ko if m else agent_id


def display_with_role(agent_id: str) -> str:
    '''"잡스 팀장" 형식. 팀장만 쓰임.'''
    m = BY_ID.get(agent_id)
    if not m:
        return agent_id
    if m.agent_id == 'teamlead':
        return f'{m.display_name} {m.role_ko}'
    return m.display_name


def profile_names(include_teamlead: bool = False) -> dict[str, str]:
    '''역할별 display_name 매핑. office.py 레거시 호환.'''
    if include_teamlead:
        return {m.agent_id: display_with_role(m.agent_id) for m in TEAM}
    return {m.agent_id: m.display_name for m in TEAM if m.agent_id != 'teamlead'}


def build_mention_map() -> dict[str, str]:
    '''@멘션 → agent_id 매핑 생성 (별칭 + 레거시 포함).'''
    result: dict[str, str] = {}
    for m in TEAM:
        result[m.agent_id] = m.agent_id
        for alias in m.aliases:
            result[alias] = m.agent_id
    # 과거 이름도 인식
    result.update(LEGACY_ALIASES)
    # 사용자
    for alias in USER_ALIASES:
        result[alias] = 'user'
    return result


def team_roster_prompt() -> str:
    '''모든 에이전트 시스템 프롬프트 최상단에 주입할 팀 로스터.'''
    lines = ['## 현재 팀 구성 (절대 규칙)\n']
    for m in TEAM:
        lines.append(f'- {m.role_ko}: **{m.display_name}** ({m.full_name})')
    lines.append('')
    legacy_pairs: list[tuple[str, str]] = []
    for old, aid in LEGACY_ALIASES.items():
        if len(old) >= 2:  # 짧은 별칭(상식, 그래 등) 제외, 풀네임만
            member = BY_ID.get(aid)
            if member and old not in [p[0] for p in legacy_pairs]:
                legacy_pairs.append((old, member.display_name))
    # 중복 제거 후 대표 매핑만
    unique_legacy: dict[str, str] = {}
    for old, new in legacy_pairs:
        if new not in unique_legacy.values():
            unique_legacy[old] = new
    lines.append('**중요**: 과거 대화 로그에 다음 구 이름이 보이더라도 절대 쓰지 마라:')
    for old, new in unique_legacy.items():
        lines.append(f'- "{old}" → {new}')
    lines.append('팀원을 언급할 때는 반드시 위 현재 이름만 사용하라.\n')
    lines.append('---\n')
    return '\n'.join(lines)


def to_api_dict() -> list[dict]:
    '''프론트엔드 /api/team 엔드포인트용 직렬화.'''
    return [
        {
            'agent_id': m.agent_id,
            'display_name': m.display_name,
            'full_name': m.full_name,
            'role_ko': m.role_ko,
            'role_short': m.role_short,
            'persona': m.persona,
            'idle_comment': m.idle_comment,
            'fallback_quote': m.fallback_quote,
        }
        for m in TEAM
    ]
