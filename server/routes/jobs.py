"""Job 파이프라인 REST API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class JobSubmitRequest(BaseModel):
    spec_id: str           # 'research' | 'planning' | ...
    title: str = ''
    input: dict[str, Any] = {}


class GateDecisionRequest(BaseModel):
    decision: str          # 'approved' | 'rejected' | 'revised'
    feedback: str = ''


@router.get('/api/jobs/specs')
async def list_specs() -> list[dict[str, Any]]:
    """등록된 Job 타입 목록."""
    from jobs.registry import all_specs
    return [
        {'id': s.id, 'title': s.title, 'description': s.description,
         'input_fields': s.input_fields, 'step_count': len(s.steps)}
        for s in all_specs()
    ]


@router.get('/api/jobs/tools')
async def list_tools() -> list[dict[str, Any]]:
    """사용 가능한 Tool 목록."""
    from jobs.tool_registry import list_tools as _list
    return _list()


@router.patch('/api/jobs/tools/{tool_id}')
async def toggle_tool(tool_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """도구 활성화/비활성화 (run_shell 등 위험 도구 관리용)."""
    from jobs.tool_registry import _BUILTIN_TOOLS
    if tool_id not in _BUILTIN_TOOLS:
        raise HTTPException(status_code=404, detail=f'도구를 찾을 수 없습니다: {tool_id}')
    enabled = body.get('enabled', True)
    _BUILTIN_TOOLS[tool_id].enabled = bool(enabled)
    return {'id': tool_id, 'enabled': _BUILTIN_TOOLS[tool_id].enabled}


@router.get('/api/jobs/gates/pending')
async def pending_gates() -> list[dict[str, Any]]:
    """승인 대기 중인 Gate 전체 — Gate Inbox용."""
    from db.job_store import list_pending_gates
    from jobs.registry import get as get_spec

    rows = list_pending_gates()
    result = []
    for row in rows:
        # spec에서 gate prompt 조회
        gate_prompt = ''
        spec = get_spec(row.get('spec_id', ''))
        if spec:
            for g in spec.gates:
                if g.id == row['gate_id']:
                    gate_prompt = g.prompt
                    break
        result.append({
            'job_id': row['job_id'],
            'job_title': row['job_title'],
            'job_spec_id': row['spec_id'],
            'gate_id': row['gate_id'],
            'gate_prompt': gate_prompt,
            'opened_at': row['opened_at'],
        })
    return result


@router.post('/api/jobs')
async def submit_job(body: JobSubmitRequest) -> dict[str, Any]:
    """Job을 제출하고 백그라운드 실행을 시작한다."""
    from jobs.registry import get
    from jobs.runner import submit

    spec = get(body.spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f'Job 타입을 찾을 수 없습니다: {body.spec_id}')

    # 필수 입력 검증
    missing = [f for f in spec.input_fields if f not in body.input and f != 'notes']
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f'필수 입력값 누락: {", ".join(missing)}',
        )

    job = await submit(spec, body.input, body.title)
    return {'job_id': job.id, 'status': job.status, 'title': job.title}


@router.get('/api/jobs')
async def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Job 목록 조회."""
    from db.job_store import list_jobs as _list
    return _list(status=status, limit=limit)


@router.get('/api/jobs/{job_id}')
async def get_job(job_id: str) -> dict[str, Any]:
    """Job 상세 + Steps + Gates."""
    from db.job_store import get_job as _get, get_steps, get_gate
    from jobs.registry import get as get_spec

    job = _get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job을 찾을 수 없습니다')

    steps = get_steps(job_id)

    # Gate 목록
    spec = get_spec(job['spec_id'])
    gates = []
    if spec:
        for g in spec.gates:
            row = get_gate(job_id, g.id)
            gates.append({
                'gate_id': g.id,
                'after_step': g.after_step,
                'prompt': g.prompt,
                'status': row['status'] if row else 'not_reached',
                'decision': row['decision'] if row else '',
                'feedback': row['feedback'] if row else '',
                'opened_at': row['opened_at'] if row else '',
            })

    return {**job, 'steps': steps, 'gates': gates}


@router.post('/api/jobs/{job_id}/gates/{gate_id}')
async def decide_gate(
    job_id: str,
    gate_id: str,
    body: GateDecisionRequest,
) -> dict[str, str]:
    """Human Gate 결정 — approved / rejected / revised."""
    from jobs.runner import resolve_gate

    if body.decision not in ('approved', 'rejected', 'revised'):
        raise HTTPException(status_code=422, detail='decision은 approved|rejected|revised')

    await resolve_gate(job_id, gate_id, body.decision, body.feedback)
    return {'status': 'ok', 'decision': body.decision}


@router.delete('/api/jobs/{job_id}')
async def cancel_job(job_id: str) -> dict[str, str]:
    """실행 중 Job 취소."""
    from db.job_store import get_job as _get, update_job
    from datetime import datetime, timezone

    job = _get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job을 찾을 수 없습니다')
    if job['status'] in ('done', 'cancelled', 'failed'):
        raise HTTPException(status_code=409, detail=f'이미 종료된 Job: {job["status"]}')

    update_job(job_id, status='cancelled',
               finished_at=datetime.now(timezone.utc).isoformat())
    return {'status': 'cancelled'}
