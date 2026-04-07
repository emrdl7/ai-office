# 에이전트 도메인 전문 지식 로딩 + 학습 규칙 추출
from __future__ import annotations

from pathlib import Path

from memory.agent_memory import AgentMemory

EXPERTISE_DIR = Path(__file__).parent.parent.parent / 'data' / 'expertise'

TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    'website': ['사이트', '웹사이트', '홈페이지', '랜딩', '퍼블리싱', '웹페이지'],
    'app': ['앱', '어플', '모바일', '네이티브', 'ios', 'android'],
    'analysis': ['분석', '리서치', '조사', '벤치마크', '경쟁사', '시장'],
    'document': ['문서', '제안서', '기획서', '매뉴얼', '보고서', '가이드'],
}


def detect_task_type(text: str) -> str:
    """텍스트에서 작업 유형을 감지한다."""
    lower = text.lower()
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return task_type
    return ''


def load_expertise(agent_name: str, task_type: str = '') -> str:
    """Layer 1 (base + task_type) + Layer 2 (learned) 전문 지식을 결합 반환."""
    parts: list[str] = []

    # Layer 1a: base (항상)
    base = EXPERTISE_DIR / 'base' / f'{agent_name}.md'
    if base.exists():
        content = base.read_text(encoding='utf-8').strip()
        if content:
            parts.append(content)

    # Layer 1b: task_type (있을 때만)
    if task_type:
        typed = EXPERTISE_DIR / task_type / f'{agent_name}.md'
        if typed.exists():
            content = typed.read_text(encoding='utf-8').strip()
            if content:
                parts.append(content)

    # Layer 2: learned rules (자가개선 축적)
    learned = EXPERTISE_DIR / 'learned' / f'{agent_name}.md'
    if learned.exists():
        content = learned.read_text(encoding='utf-8').strip()
        if content:
            parts.append(content)

    return '\n\n'.join(parts)


def extract_learned_rule(
    agent_name: str,
    failure_feedback: str,
    memory_root: str = 'data/memory',
) -> str | None:
    """반복 실패 패턴에서 학습 규칙을 추출하여 learned/{agent}.md에 추가한다.

    동일 키워드 패턴의 실패가 2회 이상 반복되면 규칙으로 승격.
    Returns: 추가된 규칙 텍스트 또는 None
    """
    memory = AgentMemory(agent_name, memory_root=memory_root)
    recent_failures = [
        r for r in memory.load_relevant(task_type=agent_name, limit=10)
        if not r.success
    ]

    if len(recent_failures) < 2:
        return None

    # 현재 실패와 유사한 과거 실패가 있는지 (키워드 겹침)
    current_words = set(failure_feedback.split())
    for past in recent_failures:
        past_words = set(past.feedback.split())
        overlap = current_words & past_words
        # 의미 있는 겹침 (3단어 이상, 1글자 조사/접속사 제외)
        meaningful = {w for w in overlap if len(w) > 1}
        if len(meaningful) >= 3:
            # 규칙으로 승격
            rule = f'- {failure_feedback.strip()}'
            _append_learned_rule(agent_name, rule)
            return rule

    return None


def _append_learned_rule(agent_name: str, rule: str) -> None:
    """learned/{agent}.md에 규칙을 추가한다. 중복 방지."""
    learned_dir = EXPERTISE_DIR / 'learned'
    learned_dir.mkdir(parents=True, exist_ok=True)
    path = learned_dir / f'{agent_name}.md'

    existing = ''
    if path.exists():
        existing = path.read_text(encoding='utf-8')

    # 중복 체크
    if rule.strip() in existing:
        return

    # 최대 20개 규칙 유지
    lines = [line for line in existing.strip().split('\n') if line.strip()]
    if not lines:
        lines = ['## 학습된 규칙 (자가개선)']

    rule_lines = [line for line in lines if line.startswith('- ')]
    if len(rule_lines) >= 20:
        # 가장 오래된 규칙 제거
        for i, line in enumerate(lines):
            if line.startswith('- '):
                lines.pop(i)
                break

    lines.append(rule)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
