"""Playbook REST API."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class PlaybookRunRequest(BaseModel):
    input: dict[str, str] = {}


@router.get('/api/playbooks')
async def list_playbooks() -> list[dict[str, Any]]:
    """등록된 Playbook 목록."""
    from jobs.playbook import all_playbooks
    return [
        {
            'id': p.id,
            'title': p.title,
            'description': p.description,
            'input_fields': p.input_fields,
            'step_count': len(p.steps),
            'steps': [
                {'spec_id': s.spec_id, 'title': s.title_template}
                for s in p.steps
            ],
        }
        for p in all_playbooks()
    ]


@router.post('/api/playbooks/{playbook_id}/run')
async def start_playbook(playbook_id: str, body: PlaybookRunRequest) -> dict[str, Any]:
    """Playbook을 시작하고 run_id를 반환한다."""
    from jobs.playbook import get, run_playbook

    spec = get(playbook_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f'Playbook 없음: {playbook_id}')

    run_id = await run_playbook(playbook_id, body.input)
    return {'run_id': run_id, 'playbook_id': playbook_id, 'status': 'running'}


@router.get('/api/playbooks/runs')
async def list_playbook_runs(limit: int = 20) -> list[dict[str, Any]]:
    """최근 Playbook 실행 목록."""
    from jobs.playbook import list_runs
    return list_runs(limit=limit)


@router.get('/api/playbooks/runs/{run_id}')
async def get_playbook_run(run_id: str) -> dict[str, Any]:
    """Playbook 실행 상세 — Job 목록 포함."""
    from jobs.playbook import get_run
    from db.job_store import get_job

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='Playbook Run 없음')

    jobs = []
    for jid in run.get('job_ids', []):
        row = get_job(jid)
        if row:
            jobs.append({
                'id': row['id'],
                'title': row['title'],
                'spec_id': row['spec_id'],
                'status': row['status'],
            })

    return {**run, 'jobs': jobs}
