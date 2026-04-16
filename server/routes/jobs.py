"""Job 파이프라인 REST API."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# 첨부파일 제한 (tasks.py와 동일)
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.md', '.csv', '.json', '.yaml', '.yml',
    '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css',
    '.zip', '.tar', '.gz',
}


class GateDecisionRequest(BaseModel):
    decision: str          # 'approved' | 'rejected' | 'revised'
    feedback: str = ''


def _validate_upload(f: UploadFile, content: bytes) -> str | None:
    ext = Path(f.filename or '').suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f'허용되지 않는 파일 형식: {ext} ({f.filename})'
    if len(content) > MAX_UPLOAD_SIZE:
        return f'파일 크기 초과: {f.filename}'
    return None


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

    from db.job_store import get_steps

    rows = list_pending_gates()
    result = []
    for row in rows:
        gate_prompt = ''
        after_step = ''
        spec = get_spec(row.get('spec_id', ''))
        if spec:
            for g in spec.gates:
                if g.id == row['gate_id']:
                    gate_prompt = g.prompt
                    after_step = g.after_step
                    break

        # 검토 대상 step 산출물 조회
        step_output = ''
        step_model = ''
        step_revised = 0
        step_revision_feedback = ''
        if after_step:
            steps = get_steps(row['job_id'])
            for s in steps:
                if s['step_id'] == after_step and s.get('status') == 'done':
                    step_output = s.get('output', '')
                    step_model = s.get('model_used', '')
                    step_revised = s.get('revised', 0) or 0
                    step_revision_feedback = s.get('revision_feedback', '')
                    break

        result.append({
            'job_id': row['job_id'],
            'job_title': row['job_title'],
            'job_spec_id': row['spec_id'],
            'gate_id': row['gate_id'],
            'gate_prompt': gate_prompt,
            'after_step': after_step,
            'step_output': step_output,
            'step_model': step_model,
            'step_revised': step_revised,
            'step_revision_feedback': step_revision_feedback,
            'opened_at': row['opened_at'],
        })
    return result


@router.post('/api/jobs')
async def submit_job(
    spec_id: str = Form(...),
    title: str = Form(default=''),
    input: str = Form(default='{}'),          # JSON 직렬화된 dict
    source_job_id: str = Form(default=''),    # 이전 Job ID (체이닝 시)
    files: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """Job을 제출하고 백그라운드 실행을 시작한다. 파일 첨부·Job 체이닝 지원."""
    from core import paths
    from harness.file_reader import read_file
    from jobs.registry import get
    from jobs.runner import submit

    spec = get(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f'Job 타입을 찾을 수 없습니다: {spec_id}')

    # input JSON 파싱
    try:
        input_data: dict[str, Any] = json.loads(input) if input.strip() else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail='input 필드가 유효한 JSON이 아닙니다')

    # 필수 입력 검증
    missing = [f for f in spec.input_fields if f not in input_data and f != 'notes']
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f'필수 입력값 누락: {", ".join(missing)}',
        )

    attachments_text = ''

    # 이전 Job 산출물을 참조 자료로 주입 (Job 체이닝)
    if source_job_id:
        from db.job_store import get_job as _get_job
        source = _get_job(source_job_id)
        if source and source.get('artifacts'):
            artifacts = source['artifacts']
            if isinstance(artifacts, str):
                try:
                    artifacts = json.loads(artifacts)
                except Exception:
                    artifacts = {}
            if artifacts:
                src_title = source.get('title', source_job_id)
                src_spec = source.get('spec_id', '')
                attachments_text += f'[이전 Job 산출물 — {src_title} ({src_spec})]\n\n'
                for key, content in artifacts.items():
                    if content and len(content) > 10:
                        attachments_text += f'## {key}\n{content}\n\n'

    # 파일 첨부 처리 — 임시 저장 후 텍스트 추출
    if files:
        job_tmp_id = f'job_upload_{spec_id}'
        upload_dir = paths.WORKSPACE_ROOT / job_tmp_id / 'uploads'
        upload_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            if not f.filename:
                continue
            content = await f.read()
            err = _validate_upload(f, content)
            if err:
                logger.warning('Job 파일 업로드 거부: %s', err)
                continue
            file_path = upload_dir / f.filename
            file_path.write_bytes(content)
            parsed = read_file(str(file_path))
            if parsed:
                attachments_text += f'\n[첨부파일: {f.filename}]\n{parsed}\n'
            else:
                attachments_text += f'\n[첨부파일: {f.filename}] (바이너리 파일, 텍스트 추출 불가)\n'

    job = await submit(spec, input_data, title, attachments_text=attachments_text)
    return {'job_id': job.id, 'status': job.status, 'title': job.title}


@router.get('/api/jobs/insights')
async def job_insights() -> dict[str, Any]:
    """Job 파이프라인 인사이트 — 완료율, 모델 사용, 스펙별 통계."""
    from db.job_store import _conn as _jconn

    c = _jconn()

    status_rows = c.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
    ).fetchall()
    by_status = {r['status']: r['cnt'] for r in status_rows}

    spec_rows = c.execute(
        "SELECT spec_id, status, COUNT(*) as cnt FROM jobs GROUP BY spec_id, status"
    ).fetchall()
    by_spec: dict[str, dict[str, int]] = {}
    for r in spec_rows:
        by_spec.setdefault(r['spec_id'], {})
        by_spec[r['spec_id']][r['status']] = r['cnt']

    model_rows = c.execute(
        "SELECT model_used, COUNT(*) as cnt FROM job_steps "
        "WHERE status='done' AND model_used != '' GROUP BY model_used ORDER BY cnt DESC"
    ).fetchall()
    model_usage = [{'model': r['model_used'], 'count': r['cnt']} for r in model_rows]

    time_rows = c.execute(
        "SELECT started_at, finished_at FROM jobs "
        "WHERE status='done' AND started_at!='' AND finished_at!=''"
    ).fetchall()
    durations = []
    for r in time_rows:
        try:
            from datetime import datetime
            s = datetime.fromisoformat(r['started_at'])
            e = datetime.fromisoformat(r['finished_at'])
            durations.append((e - s).total_seconds())
        except Exception:
            pass
    avg_duration = int(sum(durations) / len(durations)) if durations else 0

    revised_rows = c.execute(
        "SELECT SUM(revised) as total_revised, COUNT(*) as total_steps "
        "FROM job_steps WHERE status='done'"
    ).fetchone()
    total_revised = revised_rows['total_revised'] or 0
    total_steps = revised_rows['total_steps'] or 0

    daily_rows = c.execute(
        "SELECT DATE(finished_at) as day, COUNT(*) as cnt "
        "FROM jobs WHERE status='done' AND finished_at!='' "
        "AND finished_at >= DATE('now', '-7 days') "
        "GROUP BY day ORDER BY day"
    ).fetchall()
    daily_done = [{'day': r['day'], 'count': r['cnt']} for r in daily_rows]

    c.close()
    total = sum(by_status.values())
    done = by_status.get('done', 0)
    return {
        'total': total,
        'by_status': by_status,
        'completion_rate': round(done / total * 100, 1) if total else 0,
        'avg_duration_sec': avg_duration,
        'by_spec': by_spec,
        'model_usage': model_usage,
        'total_revised': total_revised,
        'total_steps_done': total_steps,
        'revision_rate': round(total_revised / total_steps * 100, 1) if total_steps else 0,
        'daily_done': daily_done,
    }


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
async def delete_job(job_id: str) -> dict[str, str]:
    """Job 삭제 — 완료/실패/취소 상태는 DB에서 영구 삭제, 실행 중은 취소."""
    from db.job_store import get_job as _get, update_job, _conn as _jconn
    from datetime import datetime, timezone

    job = _get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job을 찾을 수 없습니다')

    if job['status'] in ('done', 'cancelled', 'failed'):
        # 영구 삭제
        c = _jconn()
        c.execute('DELETE FROM job_steps WHERE job_id = ?', (job_id,))
        c.execute('DELETE FROM job_gates WHERE job_id = ?', (job_id,))
        c.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
        c.commit()
        c.close()
        return {'status': 'deleted'}

    # 실행 중/대기 → 취소
    update_job(job_id, status='cancelled',
               finished_at=datetime.now(timezone.utc).isoformat())
    return {'status': 'cancelled'}
