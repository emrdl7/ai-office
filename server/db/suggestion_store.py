# 건의게시판 저장소 — SQLite 기반
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'suggestions.db'


def _conn() -> sqlite3.Connection:
  DB_PATH.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(str(DB_PATH))
  conn.row_factory = sqlite3.Row
  conn.execute('PRAGMA journal_mode=WAL')
  conn.execute('''
    CREATE TABLE IF NOT EXISTS suggestions (
      id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'general',
      title TEXT NOT NULL,
      content TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      response TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
  ''')
  # suggestion_type 컬럼 추가 마이그레이션 (prompt/code)
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN suggestion_type TEXT DEFAULT "prompt"')
    conn.commit()
  except sqlite3.OperationalError:
    pass  # 이미 존재
  # target_agent — 건의가 적용될 대상 에이전트 (빈 값이면 제안자 본인)
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN target_agent TEXT DEFAULT ""')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  # auto_applied — 자동 반영 여부 (0/1), auto_applied_at — 반영 시각 ISO
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN auto_applied INTEGER DEFAULT 0')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  try:
    conn.execute('ALTER TABLE suggestions ADD COLUMN auto_applied_at TEXT DEFAULT ""')
    conn.commit()
  except sqlite3.OperationalError:
    pass
  return conn


# 발언에서 언급된 대상 에이전트를 감지하는 heuristic
_TARGET_PATTERNS: list[tuple[str, list[str]]] = [
  ('planner', ['planner.md', '@기획', '@planner', '기획자', '기획 에이전트', '기획 단계', '기획에서',
               '드러커', '플래너']),
  ('designer', ['designer.md', '@디자인', '@designer', '디자이너', '디자인 에이전트',
                '아이브', 'UX', 'UI 가이드']),
  ('developer', ['developer.md', '@개발', '@developer', '개발자', '개발 에이전트',
                 '튜링', '개발팀']),
  ('qa', ['qa.md', 'QA.md', '@qa', '@QA', 'QA가', 'QA는', 'QA팀', 'QA 기준', 'QA 단계',
          '데밍', '검수자']),
  ('teamlead', ['@팀장', '팀장이', '팀장은', '잡스가', '잡스는']),
]


def detect_target_agent(message: str, speaker: str = '') -> str:
  '''발언 텍스트에서 적용 대상 에이전트를 추론. 자기 자신이나 미발견이면 빈 문자열.'''
  text = message
  for agent, patterns in _TARGET_PATTERNS:
    if agent == speaker:
      continue
    for p in patterns:
      if p in text:
        return agent
  return ''


def classify_suggestion_type(title: str, content: str, category: str = 'general') -> str:
  '''건의 내용을 3가지로 분류: 'prompt' | 'rule' | 'code'.

  - prompt: 에이전트 태도/관점 조정 (PromptEvolver 규칙)
  - rule: 프로세스/규약/명세 기준 수립 (PromptEvolver 규칙 — high priority 메타 규칙)
  - code: 실제 Python/TS/yml 파일을 만들거나 고쳐야 함
  '''
  text = f'{title} {content}'.lower()

  # 강한 code 시그널 — 실제 파일 작성·수정·설치가 필수인 경우
  strong_code = [
    '.yml', '.yaml', '.github/workflows', 'github actions',
    '.tsx', '.ts ', '.js ', '.py ', '.mjs',
    'npm install', 'pip install', 'yarn add', '라이브러리 설치',
    '버튼 추가', '페이지 추가', '화면 추가', '컴포넌트 추가',
    '엔드포인트 추가', 'api 구현', 'endpoint 구현',
    '스크립트 작성', '스크립트 추가', 'workflow 파일',
    'websocket', 'webhook', 'sse 구현',
    '데이터베이스 마이그레이션', '스키마 변경',
    '크롤링', '스크래핑', 'mcp 서버 구현',
  ]
  if any(kw in text for kw in strong_code):
    return 'code'

  # rule 시그널 — 규칙/기준/명세/규약 수립 (md 편집 수준)
  rule_keywords = [
    '규칙', '원칙', '가이드라인', '규약', '표준', '기준 정의', '기준 수립',
    '명세화', '명세 작성', '명세 기준', '검수 기준', '평가 기준', '작성 규칙',
    '작성 원칙', '문서화 방식', 'bdd', 'spec-first', 'gherkin 문법',
    '인수 조건', '인수조건', 'acceptance criteria', '완료 기준', '합격 기준',
    '산출물 포맷', '보고서 포맷', '템플릿 정의',
    '프로세스 정의', '프로세스 개선', '워크플로우 정의',
    '사용자 관점', '시나리오 작성',
  ]
  if any(kw in text for kw in rule_keywords):
    return 'rule'

  # 약한 code 시그널 — 파이프라인/자동화 등 인프라 작업
  weak_code = [
    'api', 'endpoint', 'mcp', '도구 추가', '기능 추가', '기능 개발',
    '자동화 도구', '자동 저장', '자동 백업',
    'ci/cd', '파이프라인', 'pipeline', '배포',
    '외부 접근', '파일 시스템', '인증', 'auth', 'oauth',
  ]
  if category in ('도구 부족', '데이터 부족'):
    return 'code'
  if any(kw in text for kw in weak_code):
    return 'code'

  # 기본값: 프롬프트
  return 'prompt'


def create_suggestion(
  agent_id: str,
  title: str,
  content: str,
  category: str = 'general',
  suggestion_type: str | None = None,
  target_agent: str = '',
) -> dict:
  '''건의를 등록한다. suggestion_type 미지정 시 자동 분류.
  target_agent가 지정되면 승인 시 해당 에이전트의 PromptEvolver 규칙으로 반영.'''
  c = _conn()
  suggestion_id = str(uuid.uuid4())[:8]
  now = datetime.now(timezone.utc).isoformat()
  if not suggestion_type:
    suggestion_type = classify_suggestion_type(title, content, category)
  c.execute(
    'INSERT INTO suggestions (id, agent_id, category, title, content, status, created_at, updated_at, suggestion_type, target_agent) '
    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    (suggestion_id, agent_id, category, title, content, 'pending', now, now, suggestion_type, target_agent),
  )
  c.commit()
  c.close()
  return {
    'id': suggestion_id, 'agent_id': agent_id, 'category': category,
    'title': title, 'content': content, 'status': 'pending',
    'response': '', 'created_at': now, 'updated_at': now,
    'suggestion_type': suggestion_type, 'target_agent': target_agent,
  }


def get_suggestion(suggestion_id: str) -> dict | None:
  '''건의 단건을 반환한다.'''
  c = _conn()
  row = c.execute('SELECT * FROM suggestions WHERE id = ?', (suggestion_id,)).fetchone()
  c.close()
  return dict(row) if row else None


def list_suggestions(status: str = '') -> list[dict]:
  '''건의 목록을 반환한다.'''
  c = _conn()
  if status:
    rows = c.execute(
      'SELECT * FROM suggestions WHERE status = ? ORDER BY created_at DESC', (status,)
    ).fetchall()
  else:
    rows = c.execute('SELECT * FROM suggestions ORDER BY created_at DESC').fetchall()
  c.close()
  return [dict(r) for r in rows]


def update_suggestion(suggestion_id: str, status: str = '', response: str = '') -> bool:
  '''건의 상태/답변을 업데이트한다.'''
  c = _conn()
  now = datetime.now(timezone.utc).isoformat()
  updates = []
  params = []
  if status:
    updates.append('status = ?')
    params.append(status)
  if response:
    updates.append('response = ?')
    params.append(response)
  if not updates:
    c.close()
    return False
  updates.append('updated_at = ?')
  params.append(now)
  params.append(suggestion_id)
  c.execute(f'UPDATE suggestions SET {", ".join(updates)} WHERE id = ?', params)
  changed = c.total_changes > 0
  c.commit()
  c.close()
  return changed


def delete_suggestion(suggestion_id: str) -> bool:
  '''건의를 삭제한다.'''
  c = _conn()
  c.execute('DELETE FROM suggestions WHERE id = ?', (suggestion_id,))
  changed = c.total_changes > 0
  c.commit()
  c.close()
  return changed
