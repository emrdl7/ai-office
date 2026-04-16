"""Playbook — 여러 Job을 자동으로 체이닝하는 워크플로우.

Playbook YAML 포맷 (server/jobs/specs/playbooks/*.yaml):
  id: research_to_planning
  title: 리서치 → 기획
  description: ...
  input_fields:
    - topic
    - product
  steps:
    - spec_id: research
      title_template: "{topic} 리서치"
      input_map:
        topic: "{topic}"
        scope: "전체"
    - spec_id: planning
      title_template: "{topic} 기획"
      input_map:
        product: "{product}"
        goals: "{topic} 관련 서비스 개선"
        research_notes: "{research.report}"   # 이전 step의 artifact 참조
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PLAYBOOKS_DIR = Path(__file__).parent / 'specs' / 'playbooks'
_registry: dict[str, 'PlaybookSpec'] = {}


@dataclass
class PlaybookStepSpec:
    spec_id: str                           # Job spec ID
    title_template: str = ''              # e.g. "{topic} 리서치"
    input_map: dict[str, str] = field(default_factory=dict)
    # input_map 값에서 "{stepid.artifact_key}" 패턴을 이전 Job 산출물로 치환


@dataclass
class PlaybookSpec:
    id: str
    title: str
    description: str
    input_fields: list[str]
    steps: list[PlaybookStepSpec]


def load_all() -> dict[str, PlaybookSpec]:
    """playbooks/ 디렉토리의 YAML을 로드한다."""
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        return {}

    _registry.clear()
    if not _PLAYBOOKS_DIR.exists():
        return {}

    for path in sorted(_PLAYBOOKS_DIR.glob('*.yaml')):
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            spec = _parse(data)
            _registry[spec.id] = spec
        except Exception:
            logger.exception('Playbook 로드 실패: %s', path)
    return _registry


def get(pb_id: str) -> PlaybookSpec | None:
    if not _registry:
        load_all()
    return _registry.get(pb_id)


def all_playbooks() -> list[PlaybookSpec]:
    if not _registry:
        load_all()
    return list(_registry.values())


def _parse(data: dict[str, Any]) -> PlaybookSpec:
    steps = [
        PlaybookStepSpec(
            spec_id=s['spec_id'],
            title_template=s.get('title', ''),
            input_map=s.get('input_map', {}),
        )
        for s in data.get('steps', [])
    ]
    return PlaybookSpec(
        id=data['id'],
        title=data['title'],
        description=data.get('description', ''),
        input_fields=data.get('input_fields', []),
        steps=steps,
    )


# ── PlaybookRun 영속화 (jobs.db에 추가 테이블) ────────────────────────────────

def _conn():
    from db.job_store import _conn as _jconn
    c = _jconn()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS playbook_runs (
            id TEXT PRIMARY KEY,
            playbook_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            input_json TEXT DEFAULT '{}',
            job_ids_json TEXT DEFAULT '[]',
            current_step INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            finished_at TEXT DEFAULT '',
            error TEXT DEFAULT ''
        );
    ''')
    c.commit()
    return c


def create_run(run_id: str, playbook_id: str, input_data: dict) -> None:
    c = _conn()
    c.execute(
        'INSERT INTO playbook_runs (id, playbook_id, input_json, created_at) VALUES (?,?,?,?)',
        (run_id, playbook_id,
         json.dumps(input_data, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()),
    )
    c.commit()
    c.close()


def update_run(run_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    if 'job_ids' in kwargs:
        kwargs['job_ids_json'] = json.dumps(kwargs.pop('job_ids'))
    cols = ', '.join(f'{k} = ?' for k in kwargs)
    vals = list(kwargs.values()) + [run_id]
    c = _conn()
    c.execute(f'UPDATE playbook_runs SET {cols} WHERE id = ?', vals)
    c.commit()
    c.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    c = _conn()
    row = c.execute('SELECT * FROM playbook_runs WHERE id = ?', (run_id,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    d['input'] = json.loads(d.pop('input_json') or '{}')
    d['job_ids'] = json.loads(d.pop('job_ids_json') or '[]')
    return d


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        'SELECT * FROM playbook_runs ORDER BY created_at DESC LIMIT ?', (limit,),
    ).fetchall()
    c.close()
    result = []
    for row in rows:
        d = dict(row)
        d['input'] = json.loads(d.pop('input_json') or '{}')
        d['job_ids'] = json.loads(d.pop('job_ids_json') or '[]')
        result.append(d)
    return result


# ── 실행기 ────────────────────────────────────────────────────────────────────

import asyncio

_running_runs: dict[str, asyncio.Task] = {}


async def run_playbook(playbook_id: str, input_data: dict[str, Any]) -> str:
    """Playbook을 시작하고 run_id를 반환한다."""
    spec = get(playbook_id)
    if not spec:
        raise ValueError(f'Playbook 없음: {playbook_id}')

    run_id = uuid.uuid4().hex[:12]
    create_run(run_id, playbook_id, input_data)

    task = asyncio.create_task(_execute_playbook(run_id, spec, input_data))
    _running_runs[run_id] = task
    task.add_done_callback(lambda _: _running_runs.pop(run_id, None))

    return run_id


async def _execute_playbook(
    run_id: str,
    spec: PlaybookSpec,
    input_data: dict[str, Any],
) -> None:
    """Playbook의 각 step(Job)을 순서대로 실행한다.

    - 이전 Job이 gate로 인해 waiting_gate 상태면 완료될 때까지 폴링
    - 이전 Job의 artifacts를 다음 step input_map에서 참조 가능
    """
    from jobs.registry import get as get_job_spec
    from jobs.runner import submit as job_submit
    from db.job_store import get_job

    from log_bus.event_bus import event_bus, LogEvent

    async def emit(msg: str, data: dict | None = None) -> None:
        try:
            await event_bus.publish(LogEvent(
                agent_id='system',
                event_type='playbook_event',
                message=msg,
                data={'run_id': run_id, **(data or {})},
            ))
        except Exception:
            pass

    await emit(f'▶ Playbook 시작: {spec.title}')
    job_ids: list[str] = []
    # context: input_data + 이전 job artifacts (stepid.key 형태)
    context: dict[str, str] = {k: str(v) for k, v in input_data.items()}

    try:
        for idx, step_spec in enumerate(spec.steps):
            update_run(run_id, current_step=idx, job_ids=job_ids)

            job_spec = get_job_spec(step_spec.spec_id)
            if not job_spec:
                raise ValueError(f'Job spec 없음: {step_spec.spec_id}')

            # input 구성 — {prev_step.artifact} 패턴 치환
            step_input: dict[str, str] = {}
            for field_key, template in step_spec.input_map.items():
                step_input[field_key] = _fill_template(template, context)

            # 이전 Job 산출물 전체를 attachments_text로 주입
            attachments_text = _build_attachments(context)

            title = _fill_template(step_spec.title_template or job_spec.title, context)

            await emit(f'  ▶ Step {idx + 1}/{len(spec.steps)}: {title}',
                       {'step_idx': idx, 'spec_id': step_spec.spec_id})

            job = await job_submit(job_spec, step_input, title=title,
                                   attachments_text=attachments_text)
            job_ids.append(job.id)

            # Job 완료 대기 (gate 포함)
            finished = await _wait_job(job.id)
            if not finished:
                update_run(run_id, status='failed',
                           error=f'Step {idx + 1} Job {job.id} 실패',
                           finished_at=datetime.now(timezone.utc).isoformat())
                await emit(f'❌ Playbook 실패: Step {idx + 1}')
                return

            # 산출물을 context에 추가 (step_spec.spec_id.artifact_key)
            row = get_job(job.id)
            if row:
                arts = row.get('artifacts') or {}
                for k, v in arts.items():
                    context[f'{step_spec.spec_id}.{k}'] = str(v)

        update_run(run_id, status='done', job_ids=job_ids,
                   finished_at=datetime.now(timezone.utc).isoformat())
        await emit(f'🎉 Playbook 완료: {spec.title}', {'job_ids': job_ids})

    except asyncio.CancelledError:
        update_run(run_id, status='cancelled',
                   finished_at=datetime.now(timezone.utc).isoformat())
        raise
    except Exception as e:
        logger.exception('Playbook 실행 오류: %s', run_id)
        update_run(run_id, status='failed', error=str(e)[:500],
                   finished_at=datetime.now(timezone.utc).isoformat())
        await emit(f'❌ Playbook 오류: {e!s:.200}')


async def _wait_job(job_id: str, max_wait: float = 7200.0) -> bool:
    """Job 완료를 event-bus 구독으로 대기한다. (4-2 Runner 통합)

    runner가 job_done / job_failed / job_cancelled 이벤트를 발행하면
    즉시 깨어나 결과를 반환합니다.
    Gate 대기(waiting_gate)는 runner 내부에서 처리되므로 여기서는 무시합니다.

    Returns True if done, False if failed/cancelled or timeout.
    """
    from db.job_store import get_job
    from log_bus.event_bus import event_bus

    # 먼저 현재 상태 확인 — 이미 완료된 경우 즉시 반환
    row = get_job(job_id)
    if row:
        status = row.get('status', '')
        if status == 'done':
            return True
        if status in ('failed', 'cancelled'):
            return False

    # event-bus 큐 구독으로 완료 대기
    q = event_bus.subscribe()
    try:
        deadline = asyncio.get_event_loop().time() + max_wait
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning('[playbook] Job 완료 대기 타임아웃: %s', job_id)
                return False
            try:
                event = await asyncio.wait_for(q.get(), timeout=min(remaining, 30.0))
            except asyncio.TimeoutError:
                # 타임아웃마다 DB 상태 확인 (이벤트 누락 방지)
                row = get_job(job_id)
                if row:
                    status = row.get('status', '')
                    if status == 'done':
                        return True
                    if status in ('failed', 'cancelled'):
                        return False
                continue

            # 이벤트 필터링
            data = getattr(event, 'data', {}) or {}
            if data.get('job_id') != job_id:
                continue
            event_type = getattr(event, 'event_type', '')
            if event_type == 'job_done':
                return True
            if event_type in ('job_failed', 'job_cancelled'):
                return False
    finally:
        event_bus.unsubscribe(q)


def _fill_template(template: str, context: dict[str, str]) -> str:
    """'{key}' 패턴을 context 값으로 치환한다."""
    result = template
    for k, v in context.items():
        result = result.replace('{' + k + '}', str(v))
    # 치환 안 된 패턴 제거
    result = re.sub(r'\{[^}]+\}', '', result)
    return result.strip()


def _build_attachments(context: dict[str, str]) -> str:
    """spec_id.key 패턴의 context 항목을 attachments_text로 변환한다."""
    parts = []
    for k, v in context.items():
        if '.' in k and v and len(v) > 50:
            parts.append(f'[{k}]\n{v[:1500]}')
    return '\n\n'.join(parts)[:4000]
