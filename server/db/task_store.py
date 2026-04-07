# 태스크 영속 저장소 — SQLite 기반
from __future__ import annotations
# 서버 재시작해도 태스크 내역 + 진행 상태 유지
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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
  # context_json 컬럼 추가 (이미 있으면 무시)
  try:
    conn.execute('ALTER TABLE tasks ADD COLUMN context_json TEXT DEFAULT ""')
    conn.commit()
  except sqlite3.OperationalError:
    pass  # 이미 존재
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


def update_task_state(task_id: str, state: str, context: Optional[dict] = None) -> None:
  '''태스크 상태를 업데이트한다. context가 있으면 함께 저장.'''
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  if context is not None:
    c.execute(
      'UPDATE tasks SET state=?, context_json=?, updated_at=? WHERE task_id=?',
      (state, json.dumps(context, ensure_ascii=False), now, task_id),
    )
  else:
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


def get_task(task_id: str) -> Optional[dict]:
  '''태스크 하나를 조회한다.'''
  c = _conn()
  row = c.execute(
    'SELECT task_id, instruction, state, attachments, context_json, created_at, updated_at '
    'FROM tasks WHERE task_id=?',
    (task_id,),
  ).fetchone()
  c.close()
  if not row:
    return None
  d = dict(row)
  if d.get('context_json'):
    try:
      d['context'] = json.loads(d['context_json'])
    except json.JSONDecodeError:
      d['context'] = None
  else:
    d['context'] = None
  return d


def get_resumable_tasks() -> list[dict]:
  '''서버 재시작 시 복구할 태스크 목록 (running, waiting_input).'''
  c = _conn()
  rows = c.execute(
    "SELECT task_id, instruction, state, attachments, context_json, created_at, updated_at "
    "FROM tasks WHERE state IN ('running', 'waiting_input') ORDER BY created_at ASC"
  ).fetchall()
  c.close()
  results = []
  for row in rows:
    d = dict(row)
    if d.get('context_json'):
      try:
        d['context'] = json.loads(d['context_json'])
      except json.JSONDecodeError:
        d['context'] = None
    else:
      d['context'] = None
    results.append(d)
  return results
