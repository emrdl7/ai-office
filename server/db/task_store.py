# 태스크 영속 저장소 — SQLite 기반
# 서버 재시작해도 태스크 내역 유지
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / 'data' / 'tasks.db'


def _conn() -> sqlite3.Connection:
  DB_PATH.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(str(DB_PATH))
  conn.row_factory = sqlite3.Row
  conn.execute('PRAGMA journal_mode=WAL')
  conn.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
      task_id TEXT PRIMARY KEY,
      instruction TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'idle',
      attachments TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
  ''')
  conn.commit()
  return conn


def save_task(task_id: str, instruction: str, state: str = 'idle', attachments: str = '') -> None:
  '''태스크를 저장하거나 업데이트한다.'''
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  c.execute(
    'INSERT INTO tasks (task_id, instruction, state, attachments, created_at, updated_at) '
    'VALUES (?, ?, ?, ?, ?, ?) '
    'ON CONFLICT(task_id) DO UPDATE SET state=?, updated_at=?',
    (task_id, instruction, state, attachments, now, now, state, now),
  )
  c.commit()
  c.close()


def update_task_state(task_id: str, state: str) -> None:
  '''태스크 상태를 업데이트한다.'''
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  c.execute(
    'UPDATE tasks SET state=?, updated_at=? WHERE task_id=?',
    (state, now, task_id),
  )
  c.commit()
  c.close()


def list_tasks() -> list[dict]:
  '''모든 태스크를 생성 순서로 반환한다.'''
  c = _conn()
  rows = c.execute(
    'SELECT task_id, instruction, state, attachments, created_at, updated_at '
    'FROM tasks ORDER BY created_at ASC'
  ).fetchall()
  c.close()
  return [dict(r) for r in rows]


def get_task(task_id: str) -> dict | None:
  '''태스크 하나를 조회한다.'''
  c = _conn()
  row = c.execute(
    'SELECT task_id, instruction, state, attachments, created_at, updated_at '
    'FROM tasks WHERE task_id=?',
    (task_id,),
  ).fetchone()
  c.close()
  return dict(row) if row else None
