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
  conn.commit()
  return conn


def create_suggestion(
  agent_id: str,
  title: str,
  content: str,
  category: str = 'general',
) -> dict:
  '''건의를 등록한다.'''
  c = _conn()
  suggestion_id = str(uuid.uuid4())[:8]
  now = datetime.now(timezone.utc).isoformat()
  c.execute(
    'INSERT INTO suggestions (id, agent_id, category, title, content, status, created_at, updated_at) '
    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
    (suggestion_id, agent_id, category, title, content, 'pending', now, now),
  )
  c.commit()
  c.close()
  return {
    'id': suggestion_id, 'agent_id': agent_id, 'category': category,
    'title': title, 'content': content, 'status': 'pending',
    'response': '', 'created_at': now, 'updated_at': now,
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
