# 산출물/업로드/파일/내보내기 관련 엔드포인트
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from db.task_store import list_tasks
from orchestration.office import Office
from workspace.manager import WorkspaceManager

router = APIRouter()

from core import paths


@router.get('/api/artifacts')
async def list_all_artifacts(task_id: str = ''):
  '''산출물 목록 반환. task_id 지정 시 해당 태스크만.

  workspace 디렉토리명이 project_id인 경우 projects 테이블에서 메타데이터를 가져온다.
  task_id인 경우 tasks 테이블에서 instruction을 가져온다.
  '''
  if not paths.WORKSPACE_ROOT.exists():
    return []

  from db.task_store import list_projects
  project_map = {p['project_id']: p for p in list_projects()}
  task_list = list_tasks()
  task_map = {t['task_id']: t for t in task_list}
  project_to_task = {}
  for t in task_list:
    pid = t.get('project_id', '')
    if pid and pid not in project_to_task:
      project_to_task[pid] = t

  result = []
  dirs = [paths.WORKSPACE_ROOT / task_id] if task_id else sorted(paths.WORKSPACE_ROOT.iterdir())
  for task_dir in dirs:
    if not task_dir.is_dir() or task_dir.name.startswith('.'):
      continue
    dir_id = task_dir.name

    project = project_map.get(dir_id)
    task = task_map.get(dir_id)
    linked_task = project_to_task.get(dir_id)

    meta_title = ''
    meta_created = ''
    meta_state = ''
    if project:
      meta_title = project.get('title', '')
      meta_created = project.get('created_at', '')
      meta_state = project.get('state', '')
    if linked_task:
      meta_title = meta_title or linked_task.get('instruction', '')[:60]
      meta_created = meta_created or linked_task.get('created_at', '')
    if task:
      meta_title = meta_title or task.get('instruction', '')[:60]
      meta_created = meta_created or task.get('created_at', '')
      meta_state = meta_state or task.get('state', '')

    for f in sorted(task_dir.rglob('*')):
      if f.is_file() and f.name != '.gitkeep':
        rel = f.relative_to(paths.WORKSPACE_ROOT)
        ext = f.suffix.lower()
        ftype = 'code' if ext in {'.py','.ts','.js','.tsx','.jsx','.sh','.html','.css'} else 'doc' if ext in {'.md','.txt'} else 'data' if ext in {'.json','.yaml','.yml','.csv'} else 'image' if ext in {'.png','.jpg','.svg'} else 'unknown'
        if 'uploads' in str(rel):
          continue
        result.append({
          'task_id': dir_id,
          'path': str(rel),
          'name': f.name,
          'type': ftype,
          'size': f.stat().st_size,
          'project_title': meta_title,
          'created_at': meta_created,
          'state': meta_state,
        })
  return result


@router.get('/api/uploads/{task_id}/{filename}')
async def get_upload_file(task_id: str, filename: str):
  '''업로드된 파일을 바이너리로 반환한다 (이미지 썸네일 등).'''
  if '..' in task_id or '..' in filename:
    raise HTTPException(status_code=400, detail='유효하지 않은 경로')
  target = paths.WORKSPACE_ROOT / task_id / 'uploads' / filename
  if not target.exists() or not target.is_file():
    raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')
  from fastapi.responses import FileResponse
  return FileResponse(str(target), filename=filename)


@router.get('/api/artifacts/{file_path:path}')
async def get_artifact_content(file_path: str, request: Request):
  '''산출물 파일 내용을 반환한다.'''
  from fastapi.responses import HTMLResponse, PlainTextResponse
  if '..' in file_path:
    raise HTTPException(status_code=400, detail='유효하지 않은 경로')
  target = paths.WORKSPACE_ROOT / file_path
  if not target.exists() or not target.is_file():
    raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')

  if file_path.endswith('.pdf'):
    from fastapi.responses import FileResponse
    return FileResponse(str(target), media_type='application/pdf', filename=target.name)

  content = target.read_text(encoding='utf-8', errors='replace')

  if file_path.endswith('.html'):
    return HTMLResponse(content=content)

  accept = request.headers.get('accept', '')
  if 'text/html' in accept and file_path.endswith('.md'):
    import markdown as md_lib  # type: ignore[import-untyped]
    rendered = md_lib.markdown(content, extensions=['tables', 'fenced_code', 'nl2br'])
    html = f'''<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{Path(file_path).name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.8; color: #e0e0e0; background: #1a1a2e; }}
  h1 {{ font-size: 1.8em; color: #64b5f6; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ font-size: 1.4em; color: #81c784; margin-top: 2em; }}
  h3 {{ font-size: 1.15em; color: #ffb74d; }}
  p {{ margin: 0.8em 0; }}
  ul, ol {{ padding-left: 24px; }}
  li {{ margin: 4px 0; }}
  pre {{ background: #16213e; padding: 16px; border-radius: 8px; overflow-x: auto; }}
  code {{ background: #16213e; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #444; padding: 8px 12px; text-align: left; }}
  th {{ background: #16213e; color: #64b5f6; }}
  hr {{ border: none; border-top: 1px solid #333; margin: 2em 0; }}
  strong {{ color: #fff; }}
  a {{ color: #64b5f6; }}
</style>
</head><body>{rendered}</body></html>'''
    return HTMLResponse(content=html)

  return {'path': file_path, 'content': content}


@router.get('/api/files/{task_id}')
async def list_files(task_id: str):
  '''task_id의 산출물 파일 목록을 반환한다 (DASH-04).

  경로 순회 공격 방지: task_id에 '..' 또는 '/' 포함 시 400 반환.
  '''
  if '..' in task_id or '/' in task_id or '\\' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  task_dir = paths.WORKSPACE_ROOT / task_id

  if not task_dir.exists():
    return []

  wm = WorkspaceManager(task_id=task_id, workspace_root=str(paths.WORKSPACE_ROOT))
  artifacts = wm.list_artifacts()

  result = []
  for p in artifacts:
    rel = p.relative_to(task_dir)
    result.append({
      'path': str(rel),
      'type': wm.artifact_type(str(rel)),
      'size': p.stat().st_size,
    })
  return result


@router.get('/api/files/{task_id}/{file_path:path}')
async def get_file(task_id: str, file_path: str):
  '''파일 내용을 반환한다 (DASH-04).

  WorkspaceManager.safe_path()로 경로 순회를 방지한다.
  '''
  if '..' in task_id or '/' in task_id or '\\' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  wm = WorkspaceManager(task_id=task_id, workspace_root=str(paths.WORKSPACE_ROOT))
  try:
    target = wm.safe_path(file_path)
  except ValueError:
    raise HTTPException(status_code=400, detail='유효하지 않은 파일 경로입니다')

  if not target.exists():
    raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')

  try:
    content = target.read_text(encoding='utf-8')
  except UnicodeDecodeError:
    content = target.read_bytes().decode('latin-1')

  return {'path': file_path, 'content': content}


@router.get('/api/project/active')
async def get_active_project_api(request: Request):
  '''현재 활성 프로젝트 정보를 반환한다.'''
  office: Office = request.app.state.office
  if office._active_project_id:
    return {
      'project_id': office._active_project_id,
      'title': office._active_project_title,
    }
  return {'project_id': '', 'title': ''}


@router.get('/api/project/status')
async def get_project_status(request: Request):
  '''현재 프로젝트 진행 상태를 반환 — 대시보드 실시간 표시용.

  필드:
  - state: Office 상태 (idle/working/qa_review/...)
  - project_id/title: 활성 프로젝트
  - active_agent: 현재 작업 중인 에이전트
  - current_phase: 현재 단계명
  - work_started_at: 업무 시작 ISO
  - elapsed_sec: 업무 경과 시간 (초)
  - revision_count: 현재 리비전 반복 횟수
  - nodes: TaskGraph가 있으면 {total, completed, in_progress} 집계
  '''
  from datetime import datetime, timezone
  office: Office = request.app.state.office

  elapsed_sec = 0
  started = (office._work_started_at or '').strip()
  if started:
    try:
      started_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
      elapsed_sec = int((datetime.now(timezone.utc) - started_dt).total_seconds())
    except Exception:
      elapsed_sec = 0

  nodes_summary = None
  graph = getattr(office, '_task_graph', None)
  if graph is not None:
    try:
      state_dict = graph.to_state_dict()
      total = len(state_dict)
      completed = sum(1 for t in state_dict.values() if t.get('status') == 'completed')
      in_progress = sum(1 for t in state_dict.values() if t.get('status') == 'in_progress')
      nodes_summary = {
        'total': total, 'completed': completed, 'in_progress': in_progress,
      }
    except Exception:
      nodes_summary = None

  return {
    'state': office._state.value,
    'project_id': office._active_project_id or '',
    'title': office._active_project_title or '',
    'active_agent': office._active_agent or '',
    'current_phase': office._current_phase or '',
    'work_started_at': started,
    'elapsed_sec': elapsed_sec,
    'revision_count': office._revision_count,
    'nodes': nodes_summary,
  }


@router.get('/api/exports/{task_id}')
async def get_exportable_formats(task_id: str):
  '''태스크의 내보내기 가능 포맷 목록을 반환한다.'''
  from harness.export_engine import get_exportable_formats
  task_dir = paths.WORKSPACE_ROOT / task_id
  return {'formats': get_exportable_formats(task_dir)}


@router.post('/api/exports/{task_id}/{fmt}')
async def export_artifact(task_id: str, fmt: str):
  '''온디맨드 내보내기 — PDF, DOCX, ZIP 생성.'''
  from harness.export_engine import md_to_pdf, md_to_docx, folder_to_zip

  task_dir = paths.WORKSPACE_ROOT / task_id
  if not task_dir.exists():
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')

  export_dir = task_dir / 'exports'
  export_dir.mkdir(parents=True, exist_ok=True)

  if fmt == 'zip':
    out = folder_to_zip(task_dir, export_dir / 'bundle.zip')
    return {'path': f'{task_id}/exports/bundle.zip', 'format': 'zip'}

  md_parts = []
  for md_file in sorted(task_dir.rglob('*result*.md')):
    if 'uploads' in str(md_file) or 'exports' in str(md_file):
      continue
    content = md_file.read_text(encoding='utf-8', errors='replace')
    if len(content) > 100:
      md_parts.append(f'# {md_file.stem}\n\n{content}')

  if not md_parts:
    raise HTTPException(status_code=400, detail='변환할 산출물이 없습니다')

  combined = '\n\n---\n\n'.join(md_parts)

  if fmt == 'pdf':
    out = md_to_pdf(combined, export_dir / 'report.pdf', title=task_id[:20])
    return {'path': f'{task_id}/exports/{out.name}', 'format': 'pdf'}
  elif fmt == 'docx':
    out = md_to_docx(combined, export_dir / 'report.docx', title=task_id[:20])
    return {'path': f'{task_id}/exports/report.docx', 'format': 'docx'}

  raise HTTPException(status_code=400, detail=f'지원하지 않는 포맷: {fmt}')
