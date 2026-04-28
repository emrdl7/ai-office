"""업무일지 DB — tasks / project_meta / milestones (work-report 포팅)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

_DB = Path('data/workreport.db')


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB))
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS wr_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT,
            project TEXT,
            task_name TEXT NOT NULL,
            task_detail TEXT,
            progress INTEGER DEFAULT 0,
            due_date TEXT,
            milestone_id INTEGER,
            duration_min INTEGER,
            parent_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS wr_project_meta (
            project TEXT PRIMARY KEY,
            is_maintenance INTEGER DEFAULT 0,
            description TEXT,
            start_date TEXT,
            target_date TEXT,
            status TEXT DEFAULT 'active',
            client TEXT,
            category TEXT
        );

        CREATE TABLE IF NOT EXISTS wr_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            name TEXT NOT NULL,
            target_date TEXT,
            status TEXT DEFAULT 'pending',
            description TEXT
        );
        """)


# ── Task CRUD ──────────────────────────────────────────────────────────────

def create_task(
    task_name: str,
    project: str = '',
    task_detail: str = '',
    progress: int = 0,
    due_date: str = '',
    duration_min: int | None = None,
    work_date: str = '',
    work_time: str = '',
) -> dict[str, Any]:
    today = work_date or date.today().isoformat()
    now_time = work_time or datetime.now().strftime('%H:%M')
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO wr_tasks
               (date, time, project, task_name, task_detail, progress, due_date, duration_min)
               VALUES (?,?,?,?,?,?,?,?)""",
            (today, now_time, project, task_name, task_detail, progress, due_date or None, duration_min),
        )
        row = c.execute('SELECT * FROM wr_tasks WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def update_task(task_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {'task_name', 'task_detail', 'progress', 'project', 'due_date',
               'duration_min', 'milestone_id', 'parent_id', 'date', 'time'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    updates['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sets = ', '.join(f'{k}=?' for k in updates)
    vals = list(updates.values()) + [task_id]
    with _conn() as c:
        c.execute(f'UPDATE wr_tasks SET {sets} WHERE id=?', vals)
        row = c.execute('SELECT * FROM wr_tasks WHERE id=?', (task_id,)).fetchone()
    return dict(row) if row else None


def delete_task(task_id: int) -> bool:
    with _conn() as c:
        cur = c.execute('DELETE FROM wr_tasks WHERE id=?', (task_id,))
    return cur.rowcount > 0


def get_daily_tasks(work_date: str) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM wr_tasks WHERE date=? ORDER BY time, id', (work_date,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_weekly_tasks(start_date: str) -> dict[str, Any]:
    from datetime import timedelta
    start = date.fromisoformat(start_date)
    end = start + timedelta(days=6)
    end_str = end.isoformat()
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM wr_tasks WHERE date>=? AND date<=? ORDER BY date, time',
            (start_date, end_str),
        ).fetchall()
        overdue = c.execute(
            """SELECT * FROM wr_tasks
               WHERE due_date < ? AND progress < 100
               ORDER BY due_date""",
            (start_date,),
        ).fetchall()
    return {
        'tasks': [dict(r) for r in rows],
        'overdue': [dict(r) for r in overdue],
        'period': {'start': start_date, 'end': end_str},
    }


def get_recent_tasks(limit: int = 20) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM wr_tasks ORDER BY date DESC, time DESC LIMIT ?', (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Project ────────────────────────────────────────────────────────────────

def list_projects() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("""
            SELECT t.project,
                   COUNT(*) as task_count,
                   AVG(t.progress) as avg_progress,
                   MIN(t.date) as first_date,
                   MAX(t.date) as last_date,
                   m.description, m.status, m.client, m.category,
                   m.target_date, m.is_maintenance
            FROM wr_tasks t
            LEFT JOIN wr_project_meta m ON t.project = m.project
            WHERE t.project != '' AND t.project IS NOT NULL
            GROUP BY t.project
            ORDER BY last_date DESC
        """).fetchall()
    return [dict(r) for r in rows]


def upsert_project_meta(project: str, **fields: Any) -> None:
    allowed = {'description', 'status', 'client', 'category',
               'start_date', 'target_date', 'is_maintenance'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    with _conn() as c:
        existing = c.execute(
            'SELECT project FROM wr_project_meta WHERE project=?', (project,)
        ).fetchone()
        if existing:
            if updates:
                sets = ', '.join(f'{k}=?' for k in updates)
                c.execute(
                    f'UPDATE wr_project_meta SET {sets} WHERE project=?',
                    [*updates.values(), project],
                )
        else:
            updates['project'] = project
            cols = ', '.join(updates)
            placeholders = ', '.join('?' * len(updates))
            c.execute(
                f'INSERT INTO wr_project_meta ({cols}) VALUES ({placeholders})',
                list(updates.values()),
            )


# ── Milestone ──────────────────────────────────────────────────────────────

def list_milestones(project: str = '') -> list[dict[str, Any]]:
    with _conn() as c:
        if project:
            rows = c.execute(
                'SELECT * FROM wr_milestones WHERE project=? ORDER BY target_date', (project,)
            ).fetchall()
        else:
            rows = c.execute(
                'SELECT * FROM wr_milestones ORDER BY target_date'
            ).fetchall()
    return [dict(r) for r in rows]


def create_milestone(project: str, name: str, target_date: str = '', description: str = '') -> dict[str, Any]:
    with _conn() as c:
        cur = c.execute(
            'INSERT INTO wr_milestones (project, name, target_date, description) VALUES (?,?,?,?)',
            (project, name, target_date or None, description),
        )
        row = c.execute('SELECT * FROM wr_milestones WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def update_milestone(milestone_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {'name', 'target_date', 'status', 'description'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    sets = ', '.join(f'{k}=?' for k in updates)
    vals = list(updates.values()) + [milestone_id]
    with _conn() as c:
        c.execute(f'UPDATE wr_milestones SET {sets} WHERE id=?', vals)
        row = c.execute('SELECT * FROM wr_milestones WHERE id=?', (milestone_id,)).fetchone()
    return dict(row) if row else None


def delete_milestone(milestone_id: int) -> bool:
    with _conn() as c:
        cur = c.execute('DELETE FROM wr_milestones WHERE id=?', (milestone_id,))
    return cur.rowcount > 0


# ── Dashboard ─────────────────────────────────────────────────────────────

def get_dashboard() -> dict[str, Any]:
    today = date.today().isoformat()
    with _conn() as c:
        total = c.execute('SELECT COUNT(*) FROM wr_tasks').fetchone()[0]
        today_count = c.execute(
            'SELECT COUNT(*) FROM wr_tasks WHERE date=?', (today,)
        ).fetchone()[0]
        avg_progress = c.execute(
            "SELECT AVG(progress) FROM wr_tasks WHERE date=?", (today,)
        ).fetchone()[0] or 0
        overdue_count = c.execute(
            "SELECT COUNT(*) FROM wr_tasks WHERE due_date < ? AND progress < 100",
            (today,),
        ).fetchone()[0]
        projects = c.execute(
            "SELECT COUNT(DISTINCT project) FROM wr_tasks WHERE project != '' AND project IS NOT NULL"
        ).fetchone()[0]
        recent = c.execute(
            'SELECT * FROM wr_tasks ORDER BY date DESC, id DESC LIMIT 5'
        ).fetchall()
    return {
        'today': today,
        'today_count': today_count,
        'total_count': total,
        'avg_progress_today': round(avg_progress, 1),
        'overdue_count': overdue_count,
        'active_projects': projects,
        'recent_tasks': [dict(r) for r in recent],
    }
