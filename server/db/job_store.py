"""Job 파이프라인 영속화 — jobs / job_steps / job_gates 테이블."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobs.models import JobRun, StepRun, GateRun

_DB = Path(__file__).parent.parent / 'data' / 'jobs.db'


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB))
    c.row_factory = sqlite3.Row
    c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            spec_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            input_json TEXT DEFAULT '{}',
            artifacts_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            started_at TEXT DEFAULT '',
            finished_at TEXT DEFAULT '',
            current_step TEXT DEFAULT '',
            error TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS job_steps (
            job_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT DEFAULT '',
            finished_at TEXT DEFAULT '',
            output TEXT DEFAULT '',
            error TEXT DEFAULT '',
            model_used TEXT DEFAULT '',
            cost_usd REAL DEFAULT 0.0,
            PRIMARY KEY (job_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS job_gates (
            job_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            opened_at TEXT NOT NULL,
            decided_at TEXT DEFAULT '',
            decision TEXT DEFAULT '',
            feedback TEXT DEFAULT '',
            PRIMARY KEY (job_id, gate_id)
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
    ''')
    c.commit()
    return c


# ── Job CRUD ──────────────────────────────────────────────────────────────────

def create_job(job: JobRun) -> None:
    c = _conn()
    c.execute(
        'INSERT INTO jobs (id, spec_id, title, status, input_json, artifacts_json, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (job.id, job.spec_id, job.title, job.status,
         json.dumps(job.input, ensure_ascii=False),
         json.dumps(job.artifacts, ensure_ascii=False),
         job.created_at),
    )
    c.commit()
    c.close()


def update_job(job_id: str, **kwargs: Any) -> None:
    """status, current_step, started_at, finished_at, error, artifacts_json 등 갱신."""
    if not kwargs:
        return
    if 'artifacts' in kwargs:
        kwargs['artifacts_json'] = json.dumps(kwargs.pop('artifacts'), ensure_ascii=False)
    cols = ', '.join(f'{k} = ?' for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    c = _conn()
    c.execute(f'UPDATE jobs SET {cols} WHERE id = ?', vals)
    c.commit()
    c.close()


def get_job(job_id: str) -> dict[str, Any] | None:
    c = _conn()
    row = c.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    d['input'] = json.loads(d.pop('input_json') or '{}')
    d['artifacts'] = json.loads(d.pop('artifacts_json') or '{}')
    return d


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    c = _conn()
    if status:
        rows = c.execute(
            'SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?',
            (status, limit),
        ).fetchall()
    else:
        rows = c.execute(
            'SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?', (limit,),
        ).fetchall()
    c.close()
    result = []
    for row in rows:
        d = dict(row)
        d['input'] = json.loads(d.pop('input_json') or '{}')
        d['artifacts'] = json.loads(d.pop('artifacts_json') or '{}')
        result.append(d)
    return result


# ── Step CRUD ─────────────────────────────────────────────────────────────────

def upsert_step(step: StepRun) -> None:
    c = _conn()
    c.execute(
        'INSERT INTO job_steps (job_id, step_id, status, started_at, finished_at, '
        'output, error, model_used, cost_usd) VALUES (?,?,?,?,?,?,?,?,?) '
        'ON CONFLICT(job_id, step_id) DO UPDATE SET '
        'status=excluded.status, started_at=excluded.started_at, '
        'finished_at=excluded.finished_at, output=excluded.output, '
        'error=excluded.error, model_used=excluded.model_used, cost_usd=excluded.cost_usd',
        (step.job_id, step.step_id, step.status,
         step.started_at, step.finished_at,
         step.output or '',
         step.error, step.model_used, step.cost_usd),
    )
    c.commit()
    c.close()


def get_steps(job_id: str) -> list[dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        'SELECT * FROM job_steps WHERE job_id = ? ORDER BY rowid', (job_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ── Gate CRUD ─────────────────────────────────────────────────────────────────

def open_gate(gate: GateRun) -> None:
    c = _conn()
    c.execute(
        'INSERT OR IGNORE INTO job_gates '
        '(job_id, gate_id, status, opened_at) VALUES (?, ?, ?, ?)',
        (gate.job_id, gate.gate_id, gate.status, gate.opened_at),
    )
    c.commit()
    c.close()


def decide_gate(job_id: str, gate_id: str, decision: str, feedback: str = '') -> None:
    """decision: 'approved' | 'rejected' | 'revised'"""
    c = _conn()
    c.execute(
        'UPDATE job_gates SET status = ?, decision = ?, feedback = ?, decided_at = ? '
        'WHERE job_id = ? AND gate_id = ?',
        (decision, decision, feedback,
         datetime.now(timezone.utc).isoformat(),
         job_id, gate_id),
    )
    c.commit()
    c.close()


def get_gate(job_id: str, gate_id: str) -> dict[str, Any] | None:
    c = _conn()
    row = c.execute(
        'SELECT * FROM job_gates WHERE job_id = ? AND gate_id = ?',
        (job_id, gate_id),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def list_pending_gates() -> list[dict[str, Any]]:
    """승인 대기 중인 Gate 전체 — 대시보드 Gate Inbox용."""
    c = _conn()
    rows = c.execute(
        "SELECT g.*, j.title AS job_title, j.spec_id "
        "FROM job_gates g JOIN jobs j ON g.job_id = j.id "
        "WHERE g.status = 'pending' ORDER BY g.opened_at",
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]
