'''자동 반영 엔진 — prompt/rule 타입 건의를 PromptEvolver에 반영한다.

main.py의 _apply_suggestion_to_prompts를 재사용 가능하도록 분리.
rule 타입도 같은 경로 사용 (구현 비용↓, 롤백은 rule id로 동일하게 제거).
'''
import logging
import re
from datetime import datetime, timezone

from memory.team_memory import TeamMemory, SharedLesson
from improvement.prompt_evolver import PromptEvolver, PromptRule

logger = logging.getLogger(__name__)


def _extract_rule_body(content: str) -> str:
  '''메타 헤더 제거한 발언 본문만 추출.'''
  m = re.search(r'의 발언:\s*"([^"]+)"', content)
  if m:
    return m.group(1).strip()
  lines = []
  for line in content.splitlines():
    s = line.strip()
    if not s:
      if lines:
        break
      continue
    if s.startswith('[') or s.startswith('단계:') or s.startswith('카테고리:') or s.startswith('트리거'):
      continue
    lines.append(s)
  return ' '.join(lines)[:400] if lines else content[:300]


async def apply_prompt_or_rule(suggestion: dict, user_comment: str = '') -> bool:
  '''prompt 또는 rule 타입 건의를 PromptEvolver/TeamMemory에 반영.

  Returns: 성공 여부.
  '''
  try:
    sid = suggestion['id']
    agent_id = suggestion['agent_id']
    target_agent = (suggestion.get('target_agent') or '').strip()
    apply_to = target_agent or agent_id
    title = suggestion['title']
    content = suggestion['content']
    category = suggestion.get('category', 'general')
    stype = suggestion.get('suggestion_type', 'prompt')
    now_iso = datetime.now(timezone.utc).isoformat()
    rule_body = _extract_rule_body(content)
    comment_suffix = f'\n[사용자 코멘트] {user_comment}' if user_comment else ''

    # 1. 팀 공유 교훈
    try:
      TeamMemory().add_lesson(SharedLesson(
        id=f'suggestion-{sid}',
        project_title='건의 자동반영' if not user_comment else '건의 수용',
        agent_name=apply_to,
        lesson=f'{rule_body}{comment_suffix}',
        category='process_improvement',
        timestamp=now_iso,
      ))
    except Exception:
      logger.debug('TeamMemory add_lesson 실패', exc_info=True)

    # 2. 대상 에이전트 PromptEvolver 규칙
    try:
      evolver = PromptEvolver()
      existing = evolver.load_rules(apply_to)
      existing.append(PromptRule(
        id=f'suggestion-{sid}',
        created_at=now_iso,
        source=('auto' if not user_comment else 'manual'),
        category=category,
        rule=f'{rule_body}{comment_suffix}',
        evidence=f'[{stype}] 건의 #{sid}' + (' 자동 반영' if not user_comment else ' 사용자 승인'),
        priority='high',
        active=True,
      ))
      evolver.save_rules(apply_to, existing)
      return True
    except Exception:
      logger.debug('PromptEvolver save 실패', exc_info=True)
      return False
  except Exception:
    logger.warning('apply_prompt_or_rule 실패', exc_info=True)
    return False


def rollback_prompt_or_rule(suggestion_id: str, agent_ids: list[str] | None = None) -> dict:
  '''자동 반영을 되돌린다 — PromptEvolver 규칙 + TeamMemory lesson 제거.'''
  removed = {'rules': 0, 'lessons': 0}
  rule_id = f'suggestion-{suggestion_id}'

  # PromptEvolver 규칙 제거 — 대상 에이전트를 모를 수 있으니 모든 에이전트 스캔
  try:
    evolver = PromptEvolver()
    import json
    from pathlib import Path
    patches_dir = Path(__file__).parent.parent / 'data' / 'improvement' / 'prompt_patches'
    if patches_dir.exists():
      for f in patches_dir.glob('*.json'):
        try:
          data = json.loads(f.read_text())
          before = len(data.get('rules', []))
          data['rules'] = [r for r in data['rules'] if r.get('id') != rule_id]
          after = len(data['rules'])
          if after < before:
            data['meta']['total_rules'] = after
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            removed['rules'] += (before - after)
        except Exception:
          logger.debug('rule remove 실패: %s', f, exc_info=True)
  except Exception:
    pass

  # TeamMemory lesson 제거
  try:
    import json
    from pathlib import Path
    p = Path(__file__).parent.parent / 'data' / 'memory' / 'team_shared.json'
    if p.exists():
      d = json.loads(p.read_text())
      before = len(d.get('lessons', []))
      d['lessons'] = [l for l in d.get('lessons', []) if l.get('id') != rule_id]
      after = len(d['lessons'])
      if after < before:
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        removed['lessons'] += (before - after)
  except Exception:
    logger.debug('lesson remove 실패', exc_info=True)

  return removed
