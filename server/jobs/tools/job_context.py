"""job_context — 이전 Job 산출물 참조."""
from __future__ import annotations

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='job_context',
    name='이전 Job 산출물 참조',
    description='최근 완료된 Job의 산출물을 가져온다. Job 체이닝 시 이전 결과를 참조하려면 추가하라.',
    category='general',
    params=['source_job_id'],
)


def execute(context: dict[str, str]) -> str:
    source_job_id = context.get('source_job_id', '')
    if not source_job_id:
        return ''
    try:
        from db.job_store import get_job
        job = get_job(source_job_id)
        if not job:
            return f'[Job {source_job_id} 없음]'
        arts = job.get('artifacts') or {}
        if not arts:
            return f'[Job {source_job_id} 산출물 없음]'
        parts = [f'[이전 Job: {job.get("title", source_job_id)}]']
        for k, v in arts.items():
            if v:
                parts.append(f'\n## {k}\n{str(v)[:1500]}')
        return '\n'.join(parts)[:4000]
    except Exception as e:
        return f'[job_context 실패: {e}]'
