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
    c = sqlite3.connect(str(_DB), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=NORMAL')
    c.execute('PRAGMA busy_timeout=5000')
    c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            spec_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            input_json TEXT DEFAULT '{}',
            artifacts_json TEXT DEFAULT '{}',
            artifact_kinds_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            started_at TEXT DEFAULT '',
            finished_at TEXT DEFAULT '',
            current_step TEXT DEFAULT '',
            error TEXT DEFAULT '',
            total_cost_usd REAL DEFAULT 0.0
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
            revised INTEGER DEFAULT 0,
            revision_feedback TEXT DEFAULT '',
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
    # 기존 DB 마이그레이션 — 컬럼이 없으면 추가
    for table, col, definition in [
        ('job_steps', 'revised', 'INTEGER DEFAULT 0'),
        ('job_steps', 'revision_feedback', 'TEXT DEFAULT ""'),
        ('job_steps', 'persona', 'TEXT DEFAULT ""'),
        ('job_steps', 'skills_json', "TEXT DEFAULT '[]'"),
        ('job_steps', 'tools_json', "TEXT DEFAULT '[]'"),
        ('job_steps', 'execution_mode', 'TEXT DEFAULT ""'),
        ('job_steps', 'selection_source', 'TEXT DEFAULT ""'),
        ('job_steps', 'selection_reason', 'TEXT DEFAULT ""'),
        ('jobs', 'total_cost_usd', 'REAL DEFAULT 0.0'),
        ('jobs', 'artifact_kinds_json', "TEXT DEFAULT '{}'"),
        ('jobs', 'planned_steps_json', "TEXT DEFAULT '[]'"),
        ('job_gates', 'ai_suggestion', "TEXT DEFAULT ''"),
        ('job_gates', 'ai_confidence', 'INTEGER DEFAULT 0'),
        ('job_gates', 'ai_model', "TEXT DEFAULT ''"),
        ('job_gates', 'ai_reason', "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
        except Exception:
            pass  # 이미 존재하면 무시
    c.commit()
    return c


# ── Job CRUD ──────────────────────────────────────────────────────────────────

def create_job(job: JobRun) -> None:
    c = _conn()
    c.execute(
        'INSERT INTO jobs (id, spec_id, title, status, input_json, artifacts_json, artifact_kinds_json, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (job.id, job.spec_id, job.title, job.status,
         json.dumps(job.input, ensure_ascii=False),
         json.dumps(job.artifacts, ensure_ascii=False),
         json.dumps(job.artifact_kinds, ensure_ascii=False),
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
    if 'artifact_kinds' in kwargs:
        kwargs['artifact_kinds_json'] = json.dumps(kwargs.pop('artifact_kinds'), ensure_ascii=False)
    if 'planned_steps' in kwargs:
        kwargs['planned_steps_json'] = json.dumps(kwargs.pop('planned_steps'), ensure_ascii=False)
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
    d['artifact_kinds'] = json.loads(d.pop('artifact_kinds_json', None) or '{}')
    d['planned_steps'] = json.loads(d.pop('planned_steps_json', None) or '[]')
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
        d['artifact_kinds'] = json.loads(d.pop('artifact_kinds_json', None) or '{}')
        d['planned_steps'] = json.loads(d.pop('planned_steps_json', None) or '[]')
        result.append(d)
    return result


# ── Step CRUD ─────────────────────────────────────────────────────────────────

def upsert_step(step: StepRun) -> None:
    c = _conn()
    c.execute(
        'INSERT INTO job_steps (job_id, step_id, status, started_at, finished_at, '
        'output, error, model_used, cost_usd, revised, revision_feedback, '
        'persona, skills_json, tools_json, execution_mode, selection_source, selection_reason) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
        'ON CONFLICT(job_id, step_id) DO UPDATE SET '
        'status=excluded.status, started_at=excluded.started_at, '
        'finished_at=excluded.finished_at, output=excluded.output, '
        'error=excluded.error, model_used=excluded.model_used, cost_usd=excluded.cost_usd, '
        'revised=excluded.revised, revision_feedback=excluded.revision_feedback, '
        'persona=excluded.persona, skills_json=excluded.skills_json, tools_json=excluded.tools_json, '
        'execution_mode=excluded.execution_mode, selection_source=excluded.selection_source, '
        'selection_reason=excluded.selection_reason',
        (step.job_id, step.step_id, step.status,
         step.started_at, step.finished_at,
         step.output or '',
         step.error, step.model_used, step.cost_usd,
         step.revised, step.revision_feedback,
         step.persona,
         json.dumps(step.skills, ensure_ascii=False),
         json.dumps(step.tools, ensure_ascii=False),
         step.execution_mode,
         step.selection_source,
         step.selection_reason),
    )
    c.commit()
    c.close()


def get_steps(job_id: str) -> list[dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        'SELECT * FROM job_steps WHERE job_id = ? ORDER BY rowid', (job_id,),
    ).fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        d['skills'] = json.loads(d.pop('skills_json', None) or '[]')
        d['tools'] = json.loads(d.pop('tools_json', None) or '[]')
        result.append(d)
    return result


def get_component_usage_stats(limit: int = 1000) -> dict[str, dict[str, Any]]:
    """최근 step 실행 이력에서 persona/skill/tool 사용 통계를 집계한다."""
    c = _conn()
    rows = c.execute(
        'SELECT persona, skills_json, tools_json, status, error, started_at, finished_at '
        'FROM job_steps ORDER BY rowid DESC LIMIT ?',
        (limit,),
    ).fetchall()
    c.close()

    stats: dict[str, dict[str, Any]] = {
        'personas': {},
        'skills': {},
        'tools': {},
    }

    def bump(kind: str, component_id: str, row: sqlite3.Row) -> None:
        if not component_id:
            return
        item = stats[kind].setdefault(component_id, {
            'usage_count': 0,
            'failure_count': 0,
            'last_used_at': '',
            'last_error': '',
        })
        item['usage_count'] += 1
        if row['status'] == 'failed':
            item['failure_count'] += 1
            if row['error'] and not item['last_error']:
                item['last_error'] = str(row['error'])[:300]
        used_at = row['finished_at'] or row['started_at'] or ''
        if used_at and used_at > item['last_used_at']:
            item['last_used_at'] = used_at

    for row in rows:
        bump('personas', row['persona'] or '', row)
        try:
            skills = json.loads(row['skills_json'] or '[]')
        except Exception:
            skills = []
        try:
            tools = json.loads(row['tools_json'] or '[]')
        except Exception:
            tools = []
        for skill_id in skills:
            bump('skills', str(skill_id), row)
        for tool_id in tools:
            bump('tools', str(tool_id), row)

    return stats


def get_routing_quality_stats(limit: int = 1000) -> dict[str, Any]:
    """최근 step 실행 이력에서 라우팅 선택 품질을 집계한다.

    품질 점수는 운영 관측용 휴리스틱이다. 모델 출력 평가가 아니라, 성공/실패,
    수정 재실행, fallback, 선택 근거 누락 같은 실행 신호를 합산한다.
    """
    c = _conn()
    rows = c.execute(
        'SELECT status, model_used, cost_usd, revised, persona, skills_json, tools_json, '
        'execution_mode, selection_source, selection_reason '
        'FROM job_steps ORDER BY rowid DESC LIMIT ?',
        (limit,),
    ).fetchall()
    c.close()

    def parse_json_list(value: str | None) -> list[str]:
        try:
            parsed = json.loads(value or '[]')
            return [str(v) for v in parsed if str(v)]
        except Exception:
            return []

    def quality(row: sqlite3.Row) -> int:
        score = 100 if row['status'] == 'done' else 35
        score -= min(int(row['revised'] or 0) * 12, 36)
        if row['selection_source'] == 'fallback':
            score -= 12
        if not row['selection_reason']:
            score -= 6
        if not row['execution_mode']:
            score -= 6
        return max(0, min(100, score))

    def make_bucket(label: str) -> dict[str, Any]:
        return {
            'id': label,
            'steps': 0,
            'done': 0,
            'failed': 0,
            'revised': 0,
            'fallback_count': 0,
            'total_cost_usd': 0.0,
            'quality_total': 0,
        }

    def bump(bucket: dict[str, Any], row: sqlite3.Row, q: int) -> None:
        bucket['steps'] += 1
        if row['status'] == 'done':
            bucket['done'] += 1
        if row['status'] == 'failed':
            bucket['failed'] += 1
        if int(row['revised'] or 0) > 0:
            bucket['revised'] += 1
        if row['selection_source'] == 'fallback':
            bucket['fallback_count'] += 1
        bucket['total_cost_usd'] += float(row['cost_usd'] or 0.0)
        bucket['quality_total'] += q

    overall = make_bucket('overall')
    by_mode: dict[str, dict[str, Any]] = {}
    by_persona: dict[str, dict[str, Any]] = {}
    by_skill: dict[str, dict[str, Any]] = {}
    by_tool: dict[str, dict[str, Any]] = {}

    for row in rows:
        q = quality(row)
        bump(overall, row, q)

        mode = row['execution_mode'] or 'unknown'
        bump(by_mode.setdefault(mode, make_bucket(mode)), row, q)

        persona = row['persona'] or ''
        if persona:
            bump(by_persona.setdefault(persona, make_bucket(persona)), row, q)
        for skill_id in parse_json_list(row['skills_json']):
            bump(by_skill.setdefault(skill_id, make_bucket(skill_id)), row, q)
        for tool_id in parse_json_list(row['tools_json']):
            bump(by_tool.setdefault(tool_id, make_bucket(tool_id)), row, q)

    def finalize(bucket: dict[str, Any]) -> dict[str, Any]:
        steps = int(bucket['steps'] or 0)
        done = int(bucket['done'] or 0)
        revised = int(bucket['revised'] or 0)
        return {
            'id': bucket['id'],
            'steps': steps,
            'done': done,
            'failed': int(bucket['failed'] or 0),
            'success_rate': round(done / steps * 100, 1) if steps else 0,
            'revised': revised,
            'revision_rate': round(revised / steps * 100, 1) if steps else 0,
            'fallback_count': int(bucket['fallback_count'] or 0),
            'avg_cost_usd': round(float(bucket['total_cost_usd'] or 0.0) / steps, 5) if steps else 0,
            'avg_quality_score': round(float(bucket['quality_total'] or 0.0) / steps, 1) if steps else 0,
        }

    def top_items(items: dict[str, dict[str, Any]], *, limit_items: int = 8) -> list[dict[str, Any]]:
        finalized = [finalize(v) for v in items.values()]
        finalized.sort(key=lambda x: (x['avg_quality_score'], -x['steps'], x['id']))
        return finalized[:limit_items]

    return {
        'overall': finalize(overall),
        'by_execution_mode': sorted(
            [finalize(v) for v in by_mode.values()],
            key=lambda x: (-x['steps'], x['id']),
        ),
        'risk_items': {
            'personas': top_items(by_persona),
            'skills': top_items(by_skill),
            'tools': top_items(by_tool),
        },
    }


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


def update_gate_ai(
    job_id: str, gate_id: str,
    suggestion: str, confidence: int = 0,
    model: str = '', reason: str = '',
) -> None:
    """Gate AI 제안을 job_gates에 저장."""
    c = _conn()
    c.execute(
        'UPDATE job_gates SET ai_suggestion=?, ai_confidence=?, ai_model=?, ai_reason=? '
        'WHERE job_id=? AND gate_id=?',
        (suggestion, int(confidence), model, reason[:500], job_id, gate_id),
    )
    c.commit()
    c.close()


def gate_agreement_stats(days: int = 7) -> dict[str, Any]:
    """최근 N일간 Gate AI 제안과 사람 결정의 일치율 집계.

    반환: {total, matched, mismatched, pending_ai, by_gate:[{gate_id, count, match_rate}]}
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    c = _conn()
    rows = c.execute(
        "SELECT gate_id, ai_suggestion, decision, ai_confidence, ai_model "
        "FROM job_gates "
        "WHERE opened_at >= ? AND decision != '' AND ai_suggestion != ''",
        (cutoff,),
    ).fetchall()
    c.close()

    # AI 제안('approve'/'revise'/'reject') ↔ 사람 결정('approved'/'revised'/'rejected') 매핑
    ai_to_decision = {'approve': 'approved', 'revise': 'revised', 'reject': 'rejected'}
    total = 0
    matched = 0
    by_gate: dict[str, dict[str, int]] = {}
    for r in rows:
        total += 1
        ai = (r['ai_suggestion'] or '').strip().lower()
        human = (r['decision'] or '').strip().lower()
        gid = r['gate_id']
        slot = by_gate.setdefault(gid, {'count': 0, 'matched': 0})
        slot['count'] += 1
        if ai_to_decision.get(ai) == human:
            matched += 1
            slot['matched'] += 1

    return {
        'days': days,
        'total': total,
        'matched': matched,
        'mismatched': total - matched,
        'match_rate': round(matched / total, 3) if total else 0.0,
        'by_gate': [
            {
                'gate_id': gid,
                'count': v['count'],
                'matched': v['matched'],
                'match_rate': round(v['matched'] / v['count'], 3) if v['count'] else 0.0,
            }
            for gid, v in sorted(by_gate.items(), key=lambda x: -x[1]['count'])
        ],
    }


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
