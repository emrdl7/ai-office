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
  return conn


def classify_suggestion_type(title: str, content: str, category: str = 'general') -> str:
  '''건의 내용을 보고 'prompt'(에이전트 규칙 조정) 또는 'code'(실제 코드 수정)로 분류.

  키워드 heuristic — LLM 호출 없음. 애매하면 'prompt'가 안전한 기본값
  (코드 수정은 파괴적이므로 확신 없으면 프롬프트로).
  '''
  text = f'{title} {content}'.lower()

  # 코드 수정 명확 시그널 — API/도구/기능 신설
  code_keywords = [
    'api', 'endpoint', '엔드포인트', 'mcp', '도구', 'tool',
    '기능 추가', '기능추가', '기능 개발', '신기능',
    '자동화', '자동 저장', '자동 백업', '자동 내보내기',
    '인증', 'auth', 'oauth', 'token',
    '데이터베이스', 'database', 'schema', '스키마',
    'websocket', 'webhook', 'sse',
    'ci/cd', '파이프라인', 'pipeline', '배포',
    '의존성', 'dependency', '라이브러리 추가',
    '버튼 추가', '페이지 추가', '화면 추가', '컴포넌트 추가',
    '서버에서', '클라이언트에서', '프런트', '백엔드에서',
    '파일 저장', '파일 읽기', '파일 시스템',
    '외부 접근', '크롤링', '스크래핑',
  ]
  # 카테고리가 명시적 코드 요구면 우선
  if category in ('도구 부족', '데이터 부족'):
    return 'code'

  if any(kw in text for kw in code_keywords):
    return 'code'

  # 기본값: 프롬프트 (태도/기준/프로세스/관점 변경)
  return 'prompt'


def create_suggestion(
  agent_id: str,
  title: str,
  content: str,
  category: str = 'general',
  suggestion_type: str | None = None,
) -> dict:
  '''건의를 등록한다. suggestion_type 미지정 시 자동 분류.'''
  c = _conn()
  suggestion_id = str(uuid.uuid4())[:8]
  now = datetime.now(timezone.utc).isoformat()
  if not suggestion_type:
    suggestion_type = classify_suggestion_type(title, content, category)
  c.execute(
    'INSERT INTO suggestions (id, agent_id, category, title, content, status, created_at, updated_at, suggestion_type) '
    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
    (suggestion_id, agent_id, category, title, content, 'pending', now, now, suggestion_type),
  )
  c.commit()
  c.close()
  return {
    'id': suggestion_id, 'agent_id': agent_id, 'category': category,
    'title': title, 'content': content, 'status': 'pending',
    'response': '', 'created_at': now, 'updated_at': now,
    'suggestion_type': suggestion_type,
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
