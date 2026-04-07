# FastAPI 오케스트레이션 서버 진입점
from dotenv import load_dotenv
load_dotenv()

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bus.message_bus import MessageBus
from log_bus.event_bus import EventBus, LogEvent, event_bus
from orchestration.office import Office, OfficeState
from orchestration.router import MessageRouter
from orchestration.task_graph import TaskGraph
from workspace.manager import WorkspaceManager
from db.task_store import save_task, update_task_state, list_tasks, get_task

# 데이터 디렉토리 생성 (MessageBus SQLite 파일용)
Path('data').mkdir(exist_ok=True)

# 싱글턴 인스턴스
message_bus = MessageBus(db_path='data/bus.db')
# WorkspaceManager: 프로젝트 루트의 workspace/ 디렉토리 사용
WORKSPACE_ROOT = Path(__file__).parent.parent / 'workspace'
workspace = WorkspaceManager(task_id='', workspace_root=str(WORKSPACE_ROOT))


@asynccontextmanager
async def lifespan(app: FastAPI):
  '''FastAPI 생명주기 관리.'''
  office = Office(
    bus=message_bus,
    event_bus=event_bus,
    workspace=workspace,
  )
  app.state.office = office
  app.state.log_history: list[dict] = []

  await office.groq_runner.start()

  # 중단된 태스크 알림 (자동 재실행 없이 사용자에게 선택권)
  asyncio.create_task(office.restore_pending_tasks())
  yield
  await office.groq_runner.stop()
  message_bus.close()


app = FastAPI(title='AI Office', lifespan=lifespan)

# CORS 설정 — Vite 개발 서버(localhost:3100) 허용
app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:3100', 'http://127.0.0.1:3100'],
  allow_credentials=True,
  allow_methods=['*'],
  allow_headers=['*'],
)


# 요청/응답 Pydantic 모델
class TaskRequest(BaseModel):
  instruction: str  # 사용자 지시 텍스트


class TaskResponse(BaseModel):
  task_id: str
  status: str  # 'accepted'


@app.get('/health')
async def health():
  '''서버 상태 확인'''
  return {
    'status': 'ok',
    'log_bus_subscribers': event_bus.subscriber_count,
  }


@app.post('/api/chat', status_code=202)
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

  # 첨부파일 저장 + 내용 파싱
  attachments_text = ''
  file_urls: list[dict] = []
  IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp'}
  if files:
    upload_dir = WORKSPACE_ROOT / task_id / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
      if f.filename:
        file_path = upload_dir / f.filename
        content = await f.read()
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

  # 사용자 메시지를 이벤트 버스로 발행 (파일 URL 포함)
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
      # interrupted/pending 작업 재개 시 원래 workspace가 이미 복원되어 있으면 덮어쓰지 않음
      has_pending = (hasattr(office, '_interrupted_task_id') and office._interrupted_task_id) or \
                    (hasattr(office, '_pending_project') and office._pending_project)
      if not has_pending:
        task_workspace = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
        office.workspace = task_workspace
      office._current_task_id = task_id

      if to == 'all':
        # 팀 채널 → 팀장 판단 흐름
        result = await office.receive(full_message)
      else:
        # DM → 특정 팀원에게 직접 대화 (최근 산출물 컨텍스트 포함)
        agent = office.agents.get(to)
        if agent:
          # 해당 에이전트의 최근 산출물을 찾아 컨텍스트로 전달
          dm_context = ''
          try:
            for ws_dir in sorted(WORKSPACE_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
              for md_file in ws_dir.rglob(f'*{to}*result*.md'):
                dm_context = md_file.read_text(encoding='utf-8')[:3000]
                break
              if dm_context:
                break
          except Exception:
            pass
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

      # 결과물은 _execute_project 내에서 이미 채팅에 공유됨 — 중복 메시지 제거

      final_state = result.get('state', 'completed')
      update_task_state(task_id, final_state)
    except Exception as e:
      import traceback
      traceback.print_exc()
      update_task_state(task_id, f'error: {e}')
      office._state = OfficeState.IDLE
      await event_bus.publish(LogEvent(
        agent_id='teamlead',
        event_type='response',
        message=f'작업 중 문제가 발생했습니다: {str(e)[:100]}',
      ))

  asyncio.create_task(_run())
  return {'task_id': task_id, 'status': 'accepted', 'to': to, 'attachments': len(files)}


@app.post('/api/tasks', status_code=202)
async def create_task(
  request: Request,
  instruction: str = Form(...),
  files: list[UploadFile] = File(default=[]),
  base_task_id: str = Form(default=''),
):
  '''사용자 지시 + 첨부파일 + 이전 작업 참조를 받아 오케스트레이션을 시작한다.'''
  from harness.file_reader import read_file

  task_id = str(uuid.uuid4())
  office: Office = request.app.state.office
  file_names = ','.join(f.filename or '' for f in files if f.filename)
  save_task(task_id, instruction, 'idle', attachments=file_names)

  # 이전 작업 컨텍스트 수집 — 해당 태스크의 최종 산출물만 포함
  prev_context = ''
  if base_task_id:
    prev_task = get_task(base_task_id)
    if prev_task:
      prev_context = f'\n[이전 작업 지시]\n{prev_task["instruction"]}\n'
      task_final = WORKSPACE_ROOT / base_task_id / 'final' / 'result.md'
      if task_final.exists() and task_final.stat().st_size > 100:
        prev_context += f'\n[이전 최종 산출물]\n{task_final.read_text(errors="replace")}\n'
      if prev_context.strip():
        prev_context = f'\n[이전 작업 참고]\n{prev_context}'

  # 첨부파일 저장 + 내용 파싱
  attachments_text = ''
  upload_dir = WORKSPACE_ROOT / task_id / 'uploads'
  upload_dir.mkdir(parents=True, exist_ok=True)

  for f in files:
    if f.filename:
      file_path = upload_dir / f.filename
      content = await f.read()
      file_path.write_bytes(content)
      parsed = read_file(str(file_path))
      if parsed:
        attachments_text += f'\n[첨부파일: {f.filename}]\n{parsed}\n'

  # 전체 컨텍스트 조합
  full_instruction = instruction
  if attachments_text:
    full_instruction = f'{instruction}\n\n[첨부된 참조 자료 — 핵심 입력]\n{attachments_text}'
  if prev_context:
    full_instruction = f'{full_instruction}\n{prev_context}'

  async def _run():
    try:
      update_task_state(task_id, 'running')
      # 태스크별 workspace 격리
      task_workspace = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
      office.workspace = task_workspace
      result = await office.receive(full_instruction)
      final_state = result.get('state', 'completed')
      update_task_state(task_id, final_state)
    except Exception as e:
      import traceback
      traceback.print_exc()
      update_task_state(task_id, f'error: {e}')

  asyncio.create_task(_run())
  return {'task_id': task_id, 'status': 'accepted', 'attachments': len(files)}


@app.get('/api/tasks/{task_id}')
async def get_task_status_api(task_id: str):
  '''태스크 현재 상태를 반환한다'''
  task = get_task(task_id)
  if not task:
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  return {'task_id': task['task_id'], 'state': task['state'], 'instruction': task['instruction'], 'created_at': task['created_at']}


@app.delete('/api/tasks/{task_id}')
async def delete_task_api(task_id: str):
  '''태스크 삭제 — DB + workspace 폴더 모두 삭제'''
  import shutil
  task = get_task(task_id)
  if not task:
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  # DB 삭제
  from db.task_store import _conn
  c = _conn()
  c.execute('DELETE FROM tasks WHERE task_id=?', (task_id,))
  c.commit()
  c.close()
  # workspace 폴더 삭제
  task_dir = WORKSPACE_ROOT / task_id
  if task_dir.exists():
    shutil.rmtree(task_dir, ignore_errors=True)
  return {'deleted': task_id}


@app.get('/api/tasks')
async def list_tasks_api():
  '''전체 작업 지시 내역을 순서대로 반환한다 (DASH-05) — SQLite 영속'''
  tasks = list_tasks()
  return [
    {'task_id': t['task_id'], 'state': t['state'], 'instruction': t['instruction'], 'attachments': t.get('attachments', ''), 'created_at': t['created_at']}
    for t in tasks
  ]


@app.get('/api/dag')
async def get_dag(request: Request):
  '''TaskGraph를 React Flow 형식(nodes, edges)으로 반환한다 (WKFL-05).

  노드 위치는 depends_on 기반 depth 계산으로 결정한다.
  '''
  office: Office = request.app.state.office
  # TaskGraph는 현재 실행 중이 아니면 None
  graph: TaskGraph = getattr(office, '_task_graph', None)

  if graph is None:
    return {'nodes': [], 'edges': []}

  state_dict = graph.to_state_dict()

  # depth 계산 (BFS 기반)
  depth: dict[str, int] = {}

  def get_depth(task_id: str, visited: set) -> int:
    if task_id in depth:
      return depth[task_id]
    if task_id in visited:
      return 0  # 순환 의존성 방지
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

  # depth별 x 위치 카운터
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


@app.get('/api/agents')
async def get_agents(request: Request):
  '''에이전트별 현재 상태를 Office 상태에서 추론한다.'''
  office: Office = request.app.state.office
  state = office._state

  # 상태별 활성 에이전트 매핑
  state_to_active: dict[OfficeState, str] = {
    OfficeState.TEAMLEAD_THINKING: 'teamlead',
    OfficeState.MEETING: 'all',
    OfficeState.WORKING: office._active_agent or 'working',
    OfficeState.QA_REVIEW: 'qa',
    OfficeState.TEAMLEAD_REVIEW: 'teamlead',
    OfficeState.REVISION: 'planner',
  }

  active = state_to_active.get(state, '')

  # 에이전트별 실제 모델명 (러너에서 동적으로 가져옴)
  from runners.groq_runner import MODEL as GROQ_MODEL
  from runners.claude_runner import CLAUDE_MODEL
  agent_models: dict[str, str] = {
    'teamlead': f'Claude {CLAUDE_MODEL}' if CLAUDE_MODEL != 'claude' else 'Claude CLI',
    'planner': 'Gemini CLI',
    'designer': f'Claude {CLAUDE_MODEL}',
    'developer': 'Gemini CLI',
    'qa': 'Claude Haiku 4.5',
  }

  agents = []
  for agent_id in ['teamlead', 'planner', 'designer', 'developer', 'qa']:
    if active == 'all':
      status = 'meeting'
    elif active == agent_id:
      status = 'working'
    elif state in {OfficeState.IDLE, OfficeState.COMPLETED, OfficeState.ESCALATED}:
      status = 'idle'
    else:
      status = 'waiting'
    agents.append({
      'agent_id': agent_id,
      'status': status,
      'model': agent_models.get(agent_id, ''),
      'work_started_at': office._work_started_at if status in ('working', 'meeting') else '',
    })
  return agents


@app.get('/api/artifacts')
async def list_all_artifacts(task_id: str = ''):
  '''산출물 목록 반환. task_id 지정 시 해당 태스크만.'''
  if not WORKSPACE_ROOT.exists():
    return []
  result = []
  dirs = [WORKSPACE_ROOT / task_id] if task_id else sorted(WORKSPACE_ROOT.iterdir())
  for task_dir in dirs:
    if not task_dir.is_dir() or task_dir.name.startswith('.'):
      continue
    for f in sorted(task_dir.rglob('*')):
      if f.is_file() and f.name != '.gitkeep':
        rel = f.relative_to(WORKSPACE_ROOT)
        ext = f.suffix.lower()
        ftype = 'code' if ext in {'.py','.ts','.js','.tsx','.jsx','.sh','.html','.css'} else 'doc' if ext in {'.md','.txt'} else 'data' if ext in {'.json','.yaml','.yml','.csv'} else 'image' if ext in {'.png','.jpg','.svg'} else 'unknown'
        # uploads/ 폴더는 제외 (첨부파일이지 산출물이 아님)
        if 'uploads' in str(rel):
          continue
        result.append({
          'task_id': task_dir.name,
          'path': str(rel),
          'name': f.name,
          'type': ftype,
          'size': f.stat().st_size,
        })
  return result


@app.get('/api/uploads/{task_id}/{filename}')
async def get_upload_file(task_id: str, filename: str):
  '''업로드된 파일을 바이너리로 반환한다 (이미지 썸네일 등).'''
  if '..' in task_id or '..' in filename:
    raise HTTPException(status_code=400, detail='유효하지 않은 경로')
  target = WORKSPACE_ROOT / task_id / 'uploads' / filename
  if not target.exists() or not target.is_file():
    raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')
  from fastapi.responses import FileResponse
  return FileResponse(str(target), filename=filename)


@app.get('/api/artifacts/{file_path:path}')
async def get_artifact_content(file_path: str, request: Request):
  '''산출물 파일 내용을 반환한다.'''
  from fastapi.responses import HTMLResponse, PlainTextResponse
  if '..' in file_path:
    raise HTTPException(status_code=400, detail='유효하지 않은 경로')
  target = WORKSPACE_ROOT / file_path
  if not target.exists() or not target.is_file():
    raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')
  content = target.read_text(encoding='utf-8', errors='replace')

  # .html 파일은 그대로 서빙
  if file_path.endswith('.html'):
    return HTMLResponse(content=content)

  # 브라우저에서 직접 열면 마크다운을 HTML로 렌더링
  accept = request.headers.get('accept', '')
  if 'text/html' in accept and file_path.endswith('.md'):
    import markdown as md_lib
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

  # API 호출(JSON)
  return {'path': file_path, 'content': content}


@app.get('/api/files/{task_id}')
async def list_files(task_id: str):
  '''task_id의 산출물 파일 목록을 반환한다 (DASH-04).

  경로 순회 공격 방지: task_id에 '..' 또는 '/' 포함 시 400 반환.
  '''
  # 경로 순회 방지
  if '..' in task_id or '/' in task_id or '\\' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  task_dir = WORKSPACE_ROOT / task_id

  if not task_dir.exists():
    return []

  wm = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
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


@app.get('/api/files/{task_id}/{file_path:path}')
async def get_file(task_id: str, file_path: str):
  '''파일 내용을 반환한다 (DASH-04).

  WorkspaceManager.safe_path()로 경로 순회를 방지한다.
  '''
  if '..' in task_id or '/' in task_id or '\\' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  wm = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
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


@app.get('/api/logs/history')
async def get_log_history(request: Request, limit: int = 100):
  '''최근 로그 기록을 반환한다 (DASH-03 새로고침 복구용).

  limit: 반환할 최대 건수 (기본 100, 최대 500)
  '''
  from db.log_store import load_logs
  limit = min(limit, 500)
  return load_logs(limit=limit)


@app.websocket('/ws/logs')
async def log_stream(ws: WebSocket):
  '''실시간 에이전트 로그 스트림 (저장은 EventBus에서 처리)'''
  await ws.accept()
  q = event_bus.subscribe()
  try:
    while True:
      event: LogEvent = await q.get()
      await ws.send_json(asdict(event))
  except WebSocketDisconnect:
    pass
  finally:
    event_bus.unsubscribe(q)


# --- 정적 파일 서빙 (빌드된 프론트엔드) ---
DIST_DIR = Path(__file__).parent.parent / 'dashboard' / 'dist'
if DIST_DIR.exists():
  from fastapi.staticfiles import StaticFiles
  from fastapi.responses import FileResponse

  # /assets 등 정적 파일
  app.mount('/assets', StaticFiles(directory=str(DIST_DIR / 'assets')), name='static')

  # SPA fallback — API/WS가 아닌 모든 경로는 index.html 반환
  @app.get('/{path:path}')
  async def spa_fallback(path: str):
    file_path = DIST_DIR / path
    if file_path.exists() and file_path.is_file():
      return FileResponse(str(file_path))
    return FileResponse(str(DIST_DIR / 'index.html'))
