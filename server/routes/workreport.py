"""업무일지 REST API."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.workreport_store import (
    create_task, update_task, delete_task,
    get_daily_tasks, get_weekly_tasks, get_recent_tasks,
    list_projects, upsert_project_meta,
    list_milestones, create_milestone, update_milestone, delete_milestone,
    get_dashboard,
)

router = APIRouter()


# ── Task ──────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    task_name: str
    project: str = ''
    task_detail: str = ''
    progress: int = 0
    due_date: str = ''
    duration_min: int | None = None
    date: str = ''
    time: str = ''


class TaskUpdate(BaseModel):
    task_name: str | None = None
    task_detail: str | None = None
    progress: int | None = None
    project: str | None = None
    due_date: str | None = None
    duration_min: int | None = None


@router.post('/api/workreport/tasks')
def api_create_task(body: TaskCreate) -> dict[str, Any]:
    return create_task(
        task_name=body.task_name,
        project=body.project,
        task_detail=body.task_detail,
        progress=body.progress,
        due_date=body.due_date,
        duration_min=body.duration_min,
        work_date=body.date,
        work_time=body.time,
    )


@router.put('/api/workreport/tasks/{task_id}')
def api_update_task(task_id: int, body: TaskUpdate) -> dict[str, Any]:
    result = update_task(task_id, **body.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail='작업을 찾을 수 없습니다')
    return result


@router.delete('/api/workreport/tasks/{task_id}')
def api_delete_task(task_id: int) -> dict[str, str]:
    if not delete_task(task_id):
        raise HTTPException(status_code=404, detail='작업을 찾을 수 없습니다')
    return {'ok': 'deleted'}


@router.get('/api/workreport/tasks/daily')
def api_daily(work_date: str = '') -> list[dict[str, Any]]:
    return get_daily_tasks(work_date or date.today().isoformat())


@router.get('/api/workreport/tasks/weekly')
def api_weekly(start: str = '') -> dict[str, Any]:
    from datetime import timedelta
    if not start:
        today = date.today()
        start = (today - timedelta(days=today.weekday())).isoformat()
    return get_weekly_tasks(start)


@router.get('/api/workreport/tasks/recent')
def api_recent(limit: int = 20) -> list[dict[str, Any]]:
    return get_recent_tasks(limit)


# ── Project ───────────────────────────────────────────────────────────────

class ProjectMeta(BaseModel):
    description: str = ''
    status: str = 'active'
    client: str = ''
    category: str = ''
    start_date: str = ''
    target_date: str = ''
    is_maintenance: int = 0


@router.get('/api/workreport/projects')
def api_projects() -> list[dict[str, Any]]:
    return list_projects()


@router.put('/api/workreport/projects/{project}')
def api_upsert_project(project: str, body: ProjectMeta) -> dict[str, str]:
    upsert_project_meta(project, **body.model_dump(exclude_none=True))
    return {'ok': 'saved'}


# ── Milestone ─────────────────────────────────────────────────────────────

class MilestoneCreate(BaseModel):
    project: str
    name: str
    target_date: str = ''
    description: str = ''


class MilestoneUpdate(BaseModel):
    name: str | None = None
    target_date: str | None = None
    status: str | None = None
    description: str | None = None


@router.get('/api/workreport/milestones')
def api_milestones(project: str = '') -> list[dict[str, Any]]:
    return list_milestones(project)


@router.post('/api/workreport/milestones')
def api_create_milestone(body: MilestoneCreate) -> dict[str, Any]:
    return create_milestone(
        project=body.project,
        name=body.name,
        target_date=body.target_date,
        description=body.description,
    )


@router.put('/api/workreport/milestones/{milestone_id}')
def api_update_milestone(milestone_id: int, body: MilestoneUpdate) -> dict[str, Any]:
    result = update_milestone(milestone_id, **body.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail='마일스톤을 찾을 수 없습니다')
    return result


@router.delete('/api/workreport/milestones/{milestone_id}')
def api_delete_milestone(milestone_id: int) -> dict[str, str]:
    if not delete_milestone(milestone_id):
        raise HTTPException(status_code=404, detail='마일스톤을 찾을 수 없습니다')
    return {'ok': 'deleted'}


# ── Dashboard ─────────────────────────────────────────────────────────────

@router.get('/api/workreport/dashboard')
def api_dashboard() -> dict[str, Any]:
    return get_dashboard()


# ── 주간 취합 + 복사 텍스트 ────────────────────────────────────────────────

@router.get('/api/workreport/weekly-summary')
def api_weekly_summary(start: str = '') -> dict[str, Any]:
    """주간 작업을 프로젝트별로 취합하고 복사용 텍스트를 생성한다."""
    from datetime import timedelta
    if not start:
        today = date.today()
        start = (today - timedelta(days=today.weekday())).isoformat()

    weekly = get_weekly_tasks(start)
    tasks = weekly['tasks']
    period = weekly['period']

    # 프로젝트별 그룹화
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        key = t['project'] or '기타'
        groups[key].append(t)

    # 복사용 텍스트 생성
    start_dt = date.fromisoformat(period['start'])
    end_dt = date.fromisoformat(period['end'])
    header = f"[주간업무보고 {start_dt.month}/{start_dt.day}~{end_dt.month}/{end_dt.day}]"

    lines = [header, '']
    for project, ptasks in sorted(groups.items()):
        lines.append(f'■ {project}')
        for t in ptasks:
            status = '완료' if t['progress'] >= 100 else f'{t["progress"]}% 진행' if t['progress'] > 0 else '진행 중'
            detail = f' ({t["task_detail"]})' if t.get('task_detail') and t['task_detail'] != t['task_name'] else ''
            lines.append(f'  - {t["task_name"]}{detail} [{status}]')
        lines.append('')

    copy_text = '\n'.join(lines).strip()

    return {
        'period': period,
        'groups': {p: tasks for p, tasks in groups.items()},
        'overdue': weekly['overdue'],
        'total': len(tasks),
        'copy_text': copy_text,
    }
