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
  # 마이그레이션 — 이미 있으면 무시
  for alter in [
    'ALTER TABLE tasks ADD COLUMN context_json TEXT DEFAULT ""',
    'ALTER TABLE tasks ADD COLUMN project_id TEXT DEFAULT ""',
  ]:
    try:
      conn.execute(alter)
      conn.commit()
    except sqlite3.OperationalError:
      pass

  # 프로젝트 세션 테이블
  conn.execute('''
    CREATE TABLE IF NOT EXISTS projects (
      project_id TEXT PRIMARY KEY,
      title TEXT NOT NULL DEFAULT '',
      state TEXT NOT NULL DEFAULT 'active',
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
    'SELECT task_id, instruction, state, attachments, created_at, updated_at, project_id '
    'FROM tasks ORDER BY created_at ASC'
  ).fetchall()
  c.close()
  return [dict(r) for r in rows]


def get_task(task_id: str) -> Optional[dict]:
  '''태스크 하나를 조회한다.'''
  c = _conn()
  row = c.execute(
    'SELECT task_id, instruction, state, attachments, context_json, created_at, updated_at, project_id '
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


def update_task_project(task_id: str, project_id: str) -> None:
  '''태스크에 프로젝트 ID를 연결한다.'''
  c = _conn()
  c.execute('UPDATE tasks SET project_id=? WHERE task_id=?', (project_id, task_id))
  c.commit()
  c.close()


def create_project(project_id: str, title: str) -> None:
  '''새 프로젝트 세션을 생성한다.'''
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  c.execute(
    'INSERT OR IGNORE INTO projects (project_id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
    (project_id, title, 'active', now, now),
  )
  c.commit()
  c.close()


def update_project_title(project_id: str, title: str) -> None:
  '''프로젝트 제목을 업데이트한다.'''
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  c.execute('UPDATE projects SET title=?, updated_at=? WHERE project_id=?', (title, now, project_id))
  c.commit()
  c.close()


def get_active_project() -> Optional[dict]:
  '''가장 최근 활성 프로젝트를 반환한다.'''
  c = _conn()
  row = c.execute(
    "SELECT project_id, title, state, created_at, updated_at FROM projects "
    "WHERE state='active' ORDER BY updated_at DESC LIMIT 1"
  ).fetchone()
  c.close()
  return dict(row) if row else None


def archive_project(project_id: str) -> None:
  '''프로젝트를 아카이브한다.'''
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  c.execute("UPDATE projects SET state='archived', updated_at=? WHERE project_id=?", (now, project_id))
  c.commit()
  c.close()


def list_projects() -> list[dict]:
  '''모든 프로젝트를 최신순으로 반환한다.'''
  c = _conn()
  rows = c.execute('SELECT project_id, title, state, created_at, updated_at FROM projects ORDER BY updated_at DESC').fetchall()
  c.close()
  return [dict(r) for r in rows]


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
