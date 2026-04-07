# 불합격 분석기 — Claude 불합격 사유�� 파싱해서 에이전트별로 분배
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from memory.agent_memory import AgentMemory, MemoryRecord

DB_PATH = Path(__file__).parent.parent / 'data' / 'rejections.db'

# 에이전트 키워드 매핑
AGENT_KEYWORDS = {
  'planner': ['기획', '계획', '로드맵', '일정', '범위', '목적', '구조', '사이트맵', '전략'],
  'designer': ['디자인', 'UI', 'UX', '와이어프레임', '컬러', '타이포', '레이아웃', '접근성', '반응형', '시각'],
  'developer': ['개발', '코드', '기술', '스택', '아키텍처', '프론트', '백엔드', 'API', '성능', '보안', '구현'],
  'qa': ['검수', '테스트', 'QA', '검증', '호환성', '품질'],
}


def _conn() -> sqlite3.Connection:
  DB_PATH.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(str(DB_PATH))
  conn.row_factory = sqlite3.Row
  conn.execute('''
    CREATE TABLE IF NOT EXISTS rejections (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_type TEXT NOT NULL,
      feedback TEXT NOT NULL,
      blamed_agents TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
  ''')
  conn.commit()
  return conn


def analyze_rejection(feedback: str, task_type: str = 'general') -> dict[str, list[str]]:
  '''불합격 사유를 분석하여 에이전트별 문제점을 추출한다.

  Returns:
    {'designer': ['디자인 분석이 피상적'], 'developer': ['기술 스택 근거 없음']}
  '''
  result: dict[str, list[str]] = {}

  # 문장 단위로 분리
  sentences = re.split(r'[.\n]', feedback)

  for sentence in sentences:
    sentence = sentence.strip()
    if len(sentence) < 5:
      continue
    for agent, keywords in AGENT_KEYWORDS.items():
      if any(kw in sentence for kw in keywords):
        if agent not in result:
          result[agent] = []
        result[agent].append(sentence)
        break

  # 특정 에이전트에 매칭 안 되면 planner 책임
  unmatched = [s.strip() for s in sentences if len(s.strip()) >= 10 and not any(
    any(kw in s for kw in kws) for kws in AGENT_KEYWORDS.values()
  )]
  if unmatched:
    if 'planner' not in result:
      result['planner'] = []
    result['planner'].extend(unmatched[:3])

  return result


def record_rejection(feedback: str, task_type: str, memory_root: str = 'data/memory') -> dict[str, list[str]]:
  '''불합격 사유를 분석하고 에이전트별 메모리에 기록한다.'''
  blamed = analyze_rejection(feedback, task_type)
  now = datetime.now(timezone.utc).isoformat()

  # DB에 저장
  c = _conn()
  c.execute(
    'INSERT INTO rejections (task_type, feedback, blamed_agents, created_at) VALUES (?, ?, ?, ?)',
    (task_type, feedback[:2000], ','.join(blamed.keys()), now),
  )
  c.commit()
  c.close()

  # 각 에이전트 메모리에 기록
  for agent, issues in blamed.items():
    mem = AgentMemory(agent, memory_root=memory_root)
    mem.record(MemoryRecord(
      task_id=f'rejection-{now[:10]}',
      task_type=task_type,
      success=False,
      feedback=f'팀장 불합격: {"; ".join(issues[:3])}',
      tags=['claude_rejection', task_type],
      timestamp=now,
    ))

  return blamed


def get_past_rejections(task_type: str = 'general', limit: int = 5) -> list[str]:
  '''과거 불합격 패턴을 검색하여 주의사항 목록으로 반환한다.'''
  c = _conn()
  rows = c.execute(
    'SELECT feedback, blamed_agents FROM rejections ORDER BY created_at DESC LIMIT ?',
    (limit,),
  ).fetchall()
  c.close()

  warnings = []
  for row in rows:
    # 핵심 문장만 추출
    short = row['feedback'][:150]
    warnings.append(f'[과거 불합격] {short}')

  return warnings
