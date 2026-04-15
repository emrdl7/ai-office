# 채팅/태스크/DAG 엔드포인트
import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from db.task_store import get_task, list_tasks, save_task, update_task_state
from log_bus.event_bus import LogEvent, event_bus
from orchestration.office import Office, OfficeState
from orchestration.task_graph import TaskGraph
from workspace.manager import WorkspaceManager

router = APIRouter()
logger = logging.getLogger(__name__)

from core import paths

# 업로드 제한은 main.py의 _validate_upload와 동일 규격
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.txt', '.md', '.csv', '.json', '.yaml', '.yml',
  '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css',
  '.zip', '.tar', '.gz',
}


def _validate_upload(f: UploadFile, content: bytes) -> str | None:
  ext = Path(f.filename or '').suffix.lower()
  if ext not in ALLOWED_EXTENSIONS:
    return f'허용되지 않는 파일 형식: {ext} ({f.filename})'
  if len(content) > MAX_UPLOAD_SIZE:
    return f'파일 크기 초과 ({len(content) // (1024*1024)}MB > {MAX_UPLOAD_SIZE // (1024*1024)}MB): {f.filename}'
  return None


@router.post('/api/chat', status_code=202)
async def chat(
  request: Request,
  message: str = Form(default=''),
  to: str = Form(default='all'),
  files: list[UploadFile] = File(default=[]),
):
  '''메신저 채팅 — 팀 채널 또는 특정 팀원에게 메시지 전송 (파일 첨부 지원)'''
  from harness.file_reader import read_file

  office: Office = request.app.state.office
  task_id = str(uuid.uuid4())
  file_names = [f.filename for f in files if f.filename]
  save_task(task_id, message, 'idle', attachments=','.join(file_names))

  attachments_text = ''
  file_urls: list[dict] = []
  IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp'}
  if files:
    upload_dir = paths.WORKSPACE_ROOT / task_id / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
      if f.filename:
        content = await f.read()
        err = _validate_upload(f, content)
        if err:
          logger.warning('파일 업로드 거부: %s', err)
          continue
        file_path = upload_dir / f.filename
        file_path.write_bytes(content)
        ext = Path(f.filename).suffix.lower()
        file_urls.append({
          'name': f.filename,
          'url': f'/api/uploads/{task_id}/{f.filename}',
          'size': len(content),
          'isImage': ext in IMAGE_EXTS,
        })
        parsed = read_file(str(file_path))
        if parsed:
          attachments_text += f'\n[첨부파일: {f.filename}]\n{parsed}\n'

  await event_bus.publish(LogEvent(
    agent_id='user',
    event_type='message',
    message=message,
    data={'to': to, 'attachments': file_names, 'files': file_urls},
  ))

  full_message = message
  if attachments_text:
    full_message = f'{message}\n\n[첨부된 참조 자료]\n{attachments_text}'

  async def _run():
    try:
      update_task_state(task_id, 'running')
      has_pending = (hasattr(office, '_interrupted_task_id') and office._interrupted_task_id) or \
                    (hasattr(office, '_pending_project') and office._pending_project)
      if not has_pending and to != 'all':
        task_workspace = WorkspaceManager(task_id=task_id, workspace_root=str(paths.WORKSPACE_ROOT))
        office.workspace = task_workspace
      office._current_task_id = task_id

      if to == 'all':
        if office._state not in (OfficeState.IDLE, OfficeState.COMPLETED, OfficeState.ESCALATED):
          await office.handle_mid_work_input(full_message)
          update_task_state(task_id, 'completed')
          return
        result = await office.receive(full_message)
      else:
        agent = office.agents.get(to)
        if agent:
          dm_context = ''
          try:
            for ws_dir in sorted(paths.WORKSPACE_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
              for md_file in ws_dir.rglob(f'*{to}*result*.md'):
                dm_context = md_file.read_text(encoding='utf-8')[:3000]
                break
              if dm_context:
                break
          except Exception:
            logger.warning('DM 컨텍스트 산출물 조회 실패 (agent=%s)', to, exc_info=True)

          try:
            from db.log_store import load_logs
            recent = load_logs(limit=50)
            dm_history_lines = []
            for log in recent:
              if (log['agent_id'] == to and (log.get('data') or {}).get('dm')) or \
                 (log['agent_id'] == 'user' and (log.get('data') or {}).get('to') == to):
                dm_history_lines.append(f'[{log["agent_id"]}] {log["message"][:200]}')
            if dm_history_lines:
              dm_context = '[이전 DM 대화]\n' + '\n'.join(dm_history_lines[-10:]) + '\n\n' + dm_context
          except Exception:
            logger.warning('DM 대화 기록 로드 실패 (agent=%s)', to, exc_info=True)

          response = await agent.handle(full_message, context=dm_context)
          await event_bus.publish(LogEvent(
            agent_id=to,
            event_type='response',
            message=response,
            data={'dm': True},
          ))
          result = {'state': 'completed', 'response': response}
        else:
          result = {'state': 'error', 'response': f'{to}를 찾을 수 없습니다.'}

      final_state = result.get('state', 'completed')
      update_task_state(task_id, final_state)
    except Exception as e:
      logger.warning('채팅 처리 중 오류 발생 (task_id=%s): %s', task_id, e, exc_info=True)
      update_task_state(task_id, f'error: {e}')
      office._state = OfficeState.IDLE
      office._active_agent = ''
      office._work_started_at = ''
      await event_bus.publish(LogEvent(
        agent_id='teamlead',
        event_type='response',
        message=f'작업 중 문제가 발생했습니다: {str(e)[:100]}',
      ))

  task = asyncio.create_task(_run())
  def _handle_task_error(t):
    if t.exception():
      logger.warning('비동기 태스크 미처리 예외 발생: %s', t.exception(), exc_info=t.exception())
  task.add_done_callback(_handle_task_error)
  return {'task_id': task_id, 'status': 'accepted', 'to': to, 'attachments': len(files)}


@router.post('/api/tasks', status_code=202)
async def create_task(
  request: Request,
  instruction: str = Form(...),
  files: list[UploadFile] = File(default=[]),
):
  '''사용자 지시 + 첨부파일을 받아 오케스트레이션을 시작한다.'''
  from harness.file_reader import read_file

  task_id = str(uuid.uuid4())
  office: Office = request.app.state.office
  file_names = ','.join(f.filename or '' for f in files if f.filename)
  save_task(task_id, instruction, 'idle', attachments=file_names)

  attachments_text = ''
  upload_dir = paths.WORKSPACE_ROOT / task_id / 'uploads'
  upload_dir.mkdir(parents=True, exist_ok=True)

  for f in files:
    if f.filename:
      content = await f.read()
      err = _validate_upload(f, content)
      if err:
        logger.warning('파일 업로드 거부: %s', err)
        continue
      file_path = upload_dir / f.filename
      file_path.write_bytes(content)
      parsed = read_file(str(file_path))
      if parsed:
        attachments_text += f'\n[첨부파일: {f.filename}]\n{parsed}\n'

  full_instruction = instruction
  if attachments_text:
    full_instruction = f'{instruction}\n\n[첨부된 참조 자료 — 핵심 입력]\n{attachments_text}'

  async def _run():
    try:
      update_task_state(task_id, 'running')
      task_workspace = WorkspaceManager(task_id=task_id, workspace_root=str(paths.WORKSPACE_ROOT))
      office.workspace = task_workspace
      result = await office.receive(full_instruction)
      final_state = result.get('state', 'completed')
      update_task_state(task_id, final_state)
    except Exception as e:
      logger.warning('태스크 실행 중 오류 발생 (task_id=%s): %s', task_id, e, exc_info=True)
      update_task_state(task_id, f'error: {e}')

  asyncio.create_task(_run())
  return {'task_id': task_id, 'status': 'accepted', 'attachments': len(files)}


@router.get('/api/tasks/{task_id}')
async def get_task_status_api(task_id: str):
  '''태스크 현재 상태를 반환한다'''
  task = get_task(task_id)
  if not task:
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  return {'task_id': task['task_id'], 'state': task['state'], 'instruction': task['instruction'], 'created_at': task['created_at']}


@router.delete('/api/tasks/{task_id}')
async def delete_task_api(task_id: str):
  '''태스크 삭제 — DB + workspace 폴더 모두 삭제'''
  import shutil
  task = get_task(task_id)
  if not task:
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  from db.task_store import _conn
  c = _conn()
  c.execute('DELETE FROM tasks WHERE task_id=?', (task_id,))
  c.commit()
  c.close()
  task_dir = paths.WORKSPACE_ROOT / task_id
  if task_dir.exists():
    shutil.rmtree(task_dir, ignore_errors=True)
  return {'deleted': task_id}


@router.get('/api/tasks')
async def list_tasks_api():
  '''전체 작업 지시 내역을 순서대로 반환한다 (DASH-05) — SQLite 영속'''
  tasks = list_tasks()
  return [
    {'task_id': t['task_id'], 'state': t['state'], 'instruction': t['instruction'], 'attachments': t.get('attachments', ''), 'created_at': t['created_at']}
    for t in tasks
  ]


@router.get('/api/dag')
async def get_dag(request: Request):
  '''TaskGraph를 React Flow 형식(nodes, edges)으로 반환한다 (WKFL-05).'''
  office: Office = request.app.state.office
  graph: TaskGraph | None = getattr(office, '_task_graph', None)

  if graph is None:
    return {'nodes': [], 'edges': []}

  state_dict = graph.to_state_dict()

  depth: dict[str, int] = {}

  def get_depth(task_id: str, visited: set) -> int:
    if task_id in depth:
      return depth[task_id]
    if task_id in visited:
      return 0
    visited = visited | {task_id}
    task_data = state_dict.get(task_id, {})
    deps = task_data.get('depends_on', [])
    if not deps:
      depth[task_id] = 0
    else:
      depth[task_id] = max(get_depth(d, visited) for d in deps) + 1
    return depth[task_id]

  for tid in state_dict:
    get_depth(tid, set())

  x_counter: dict[int, int] = {}

  nodes = []
  for tid, task_data in state_dict.items():
    d = depth.get(tid, 0)
    x_counter[d] = x_counter.get(d, 0) + 1
    x = d * 250
    y = (x_counter[d] - 1) * 120

    nodes.append({
      'id': tid,
      'data': {
        'label': task_data.get('description', tid)[:40],
        'status': task_data.get('status', 'pending'),
        'assigned_to': task_data.get('assigned_to', ''),
        'artifact_paths': task_data.get('artifact_paths', []),
      },
      'position': {'x': x, 'y': y},
    })

  edges = []
  for tid, task_data in state_dict.items():
    for dep_id in task_data.get('depends_on', []):
      edges.append({
        'id': f'{dep_id}->{tid}',
        'source': dep_id,
        'target': tid,
      })

  return {'nodes': nodes, 'edges': edges}
