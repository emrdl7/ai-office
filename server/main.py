# FastAPI 오케스트레이션 서버 진입점
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bus.message_bus import MessageBus
from log_bus.event_bus import EventBus, LogEvent, event_bus
from orchestration.office import Office, OfficeState
from orchestration.router import MessageRouter
from orchestration.task_graph import TaskGraph
from workspace.manager import WorkspaceManager
from db.task_store import save_task, update_task_state, list_tasks, get_task

import logging
logger = logging.getLogger(__name__)

# WebSocket 인증 토큰 (환경변수 또는 서버 시작 시 자동 생성)
WS_AUTH_TOKEN = os.environ.get('WS_AUTH_TOKEN') or secrets.token_urlsafe(32)

# REST API 인증 토큰 (선택) — 설정 시 /api/* 경로가 Bearer 또는 ?token=로 보호됨
# 로컬 단독 실행 시 비워두면 현재 동작 유지(CORS로 외부 차단).
# 외부 노출(원격/프록시 뒤) 시 반드시 설정할 것.
REST_AUTH_TOKEN = os.environ.get('REST_AUTH_TOKEN', '').strip()

# 인증 면제 경로 — 헬스체크만 (ws-token은 보호하여 token 탈취 방지)
_AUTH_EXEMPT_PATHS = {'/health'}

# 파일 업로드 제한
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',  # 이미지
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',  # 문서
  '.txt', '.md', '.csv', '.json', '.yaml', '.yml',  # 텍스트/데이터
  '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css',  # 코드
  '.zip', '.tar', '.gz',  # 압축
}

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
  # 재기동 복구 — 코드 패치 중단으로 남은 orphan git 상태 정리
  asyncio.create_task(_recover_orphan_patches())

  # 에이전트 자발적 활동 백그라운드 루프 시작
  office._autonomous_task = asyncio.create_task(office.start_autonomous_loop())
  # 팀장 배치 리뷰 루프 시작 (주기적 대화 분석 + 건의 격상 + 요약 압축)
  office._teamlead_review_task = asyncio.create_task(office.start_teamlead_review_loop())
  # 메시지 버스 아카이브 루프 — 시작 시 1회 + 24h 주기 (완료 메시지 30일 이상 이관)
  archive_task = asyncio.create_task(_archive_loop())
  # draft 건의 자동 승격 루프 — 24h 경과 draft를 pending으로
  draft_promotion_task = asyncio.create_task(_draft_promotion_loop())
  yield
  archive_task.cancel()
  draft_promotion_task.cancel()
  office.stop_autonomous_loop()
  await office.groq_runner.stop()
  message_bus.close()


async def _archive_loop():
  '''서버 생존 동안 24시간 주기로 오래된 done 메시지 + 임계치 도달한 chat_logs를 archive로 이관.'''
  from db.log_store import maybe_archive_logs
  while True:
    try:
      moved = await asyncio.to_thread(message_bus.archive_old_messages)
      if moved:
        logger.info('message bus archive: moved %d rows', moved)
    except asyncio.CancelledError:
      raise
    except Exception:
      logger.exception('message bus archive failed')
    try:
      moved_logs = await asyncio.to_thread(maybe_archive_logs, 30)
      if moved_logs:
        logger.info('chat_logs archive: moved %d rows', moved_logs)
    except asyncio.CancelledError:
      raise
    except Exception:
      logger.exception('chat_logs archive failed')
    try:
      await asyncio.sleep(24 * 60 * 60)
    except asyncio.CancelledError:
      break


async def _draft_promotion_loop():
  '''1시간 주기로 24h 경과 draft 건의를 pending으로 자동 승격.

  draft → pending 승격 후 auto_triage_new_suggestion을 호출해 정상 흐름 진입.
  '''
  from db.suggestion_store import auto_promote_drafts, list_suggestions
  while True:
    try:
      await asyncio.sleep(60 * 60)
    except asyncio.CancelledError:
      break
    try:
      before = {s['id'] for s in list_suggestions(status='pending')}
      promoted = await asyncio.to_thread(auto_promote_drafts, 24)
      if promoted:
        logger.info('draft 자동 승격: %d건', promoted)
        after = list_suggestions(status='pending')
        for s in after:
          if s['id'] not in before:
            try:
              asyncio.create_task(auto_triage_new_suggestion(s['id']))
            except Exception:
              logger.debug('auto_triage 호출 실패: %s', s['id'], exc_info=True)
    except Exception:
      logger.exception('draft 자동 승격 실패')


app = FastAPI(title='AI Office', lifespan=lifespan)


@app.middleware('http')
async def _rest_auth_middleware(request: Request, call_next):
  '''REST_AUTH_TOKEN이 설정된 경우 /api/* 경로를 Bearer 또는 ?token=으로 보호.

  WS 엔드포인트는 기존 WS_AUTH_TOKEN 쿼리 파라미터로 별도 보호.
  로컬 개발(토큰 미설정) 시 현재 동작 유지.
  '''
  if not REST_AUTH_TOKEN:
    return await call_next(request)
  path = request.url.path
  if not path.startswith('/api/') or path in _AUTH_EXEMPT_PATHS:
    return await call_next(request)
  # Authorization: Bearer <token> 우선
  auth = request.headers.get('authorization', '')
  token = ''
  if auth.lower().startswith('bearer '):
    token = auth[7:].strip()
  else:
    token = request.query_params.get('token', '')
  # 상수시간 비교
  if not token or not secrets.compare_digest(token, REST_AUTH_TOKEN):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
  return await call_next(request)


# CORS 설정 — Vite 개발 서버(localhost:3100) 허용
app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:3100', 'http://127.0.0.1:3100'],
  allow_credentials=True,
  allow_methods=['*'],
  allow_headers=['*'],
)

from routes.admin import router as admin_router
from routes.team import router as team_router
from routes.search import router as search_router
app.include_router(admin_router)
app.include_router(team_router)
app.include_router(search_router)


def _validate_upload(f: UploadFile, content: bytes) -> str | None:
  '''업로드 파일 검증. 문제가 있으면 에러 메시지 반환, 없으면 None.'''
  ext = Path(f.filename or '').suffix.lower()
  if ext not in ALLOWED_EXTENSIONS:
    return f'허용되지 않는 파일 형식: {ext} ({f.filename})'
  if len(content) > MAX_UPLOAD_SIZE:
    return f'파일 크기 초과 ({len(content) // (1024*1024)}MB > {MAX_UPLOAD_SIZE // (1024*1024)}MB): {f.filename}'
  return None


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
      # workspace는 Office.receive()에서 프로젝트 세션에 따라 설정됨
      # DM이나 fallback용 기본 workspace만 설정
      has_pending = (hasattr(office, '_interrupted_task_id') and office._interrupted_task_id) or \
                    (hasattr(office, '_pending_project') and office._pending_project)
      if not has_pending and to != 'all':
        task_workspace = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
        office.workspace = task_workspace
      office._current_task_id = task_id

      if to == 'all':
        # 작업 중 사용자 메시지 → 중간 참여 처리
        if office._state not in (OfficeState.IDLE, OfficeState.COMPLETED, OfficeState.ESCALATED):
          await office.handle_mid_work_input(full_message)
          update_task_state(task_id, 'completed')
          return
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
            logger.warning('DM 컨텍스트 산출물 조회 실패 (agent=%s)', to, exc_info=True)

          # 이전 DM 대화 기록을 컨텍스트에 추가 (대화 연속성)
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

      # 결과물은 _execute_project 내에서 이미 채팅에 공유됨 — 중복 메시지 제거

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

  # 이전 작업 컨텍스트 수집 — 공통 함수로 모든 단계별 산출물 포함
  prev_context = _build_prev_context(base_task_id)

  # 첨부파일 저장 + 내용 파싱
  attachments_text = ''
  upload_dir = WORKSPACE_ROOT / task_id / 'uploads'
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
      logger.warning('태스크 실행 중 오류 발생 (task_id=%s): %s', task_id, e, exc_info=True)
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



@app.get('/api/artifacts')
async def list_all_artifacts(task_id: str = ''):
  '''산출물 목록 반환. task_id 지정 시 해당 태스크만.

  workspace 디렉토리명이 project_id인 경우 projects 테이블에서 메타데이터를 가져온다.
  task_id인 경우 tasks 테이블에서 instruction을 가져온다.
  '''
  if not WORKSPACE_ROOT.exists():
    return []

  # 프로젝트/태스크 메타데이터 캐시 구축
  from db.task_store import list_projects
  project_map = {p['project_id']: p for p in list_projects()}
  task_list = list_tasks()
  task_map = {t['task_id']: t for t in task_list}
  # task의 project_id → task 역매핑 (project_id로 원본 instruction 찾기)
  project_to_task = {}
  for t in task_list:
    pid = t.get('project_id', '')
    if pid and pid not in project_to_task:
      project_to_task[pid] = t

  result = []
  dirs = [WORKSPACE_ROOT / task_id] if task_id else sorted(WORKSPACE_ROOT.iterdir())
  for task_dir in dirs:
    if not task_dir.is_dir() or task_dir.name.startswith('.'):
      continue
    dir_id = task_dir.name

    # 이 workspace의 메타데이터 결정
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
        rel = f.relative_to(WORKSPACE_ROOT)
        ext = f.suffix.lower()
        ftype = 'code' if ext in {'.py','.ts','.js','.tsx','.jsx','.sh','.html','.css'} else 'doc' if ext in {'.md','.txt'} else 'data' if ext in {'.json','.yaml','.yml','.csv'} else 'image' if ext in {'.png','.jpg','.svg'} else 'unknown'
        # uploads/ 폴더는 제외 (첨부파일이지 산출물이 아님)
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

  # .pdf 파일은 바이너리로 서빙 (read_text 전에 분기)
  if file_path.endswith('.pdf'):
    from fastapi.responses import FileResponse
    return FileResponse(str(target), media_type='application/pdf', filename=target.name)

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


@app.get('/api/project/active')
async def get_active_project_api(request: Request):
  '''현재 활성 프로젝트 정보를 반환한다.'''
  office: Office = request.app.state.office
  if office._active_project_id:
    return {
      'project_id': office._active_project_id,
      'title': office._active_project_title,
    }
  return {'project_id': '', 'title': ''}


@app.get('/api/exports/{task_id}')
async def get_exportable_formats(task_id: str):
  '''태스크의 내보내기 가능 포맷 목록을 반환한다.'''
  from harness.export_engine import get_exportable_formats
  task_dir = WORKSPACE_ROOT / task_id
  return {'formats': get_exportable_formats(task_dir)}


@app.post('/api/exports/{task_id}/{fmt}')
async def export_artifact(task_id: str, fmt: str):
  '''온디맨드 내보내기 — PDF, DOCX, ZIP 생성.'''
  from harness.export_engine import md_to_pdf, md_to_docx, folder_to_zip

  task_dir = WORKSPACE_ROOT / task_id
  if not task_dir.exists():
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')

  export_dir = task_dir / 'exports'
  export_dir.mkdir(parents=True, exist_ok=True)

  if fmt == 'zip':
    out = folder_to_zip(task_dir, export_dir / 'bundle.zip')
    return {'path': f'{task_id}/exports/bundle.zip', 'format': 'zip'}

  # MD 파일들을 합쳐서 변환
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


@app.delete('/api/logs')
async def clear_logs_api():
  '''채팅 로그를 모두 삭제한다.'''
  from db.log_store import clear_logs
  count = clear_logs()
  return {'deleted': count}


@app.get('/api/logs/history')
async def get_log_history(request: Request, limit: int = 100):
  '''최근 로그 기록을 반환한다 (DASH-03 새로고침 복구용).

  limit: 반환할 최대 건수 (기본 100, 최대 500)
  '''
  from db.log_store import load_logs
  limit = min(limit, 500)
  return load_logs(limit=limit)


@app.post('/api/logs/{log_id}/react')
async def react_to_log(log_id: str, request: Request):
  '''메시지에 이모지 리액션을 추가/토글한다.

  user 필드에 'user'(기본) 또는 agent_id('planner' 등)를 받는다.
  리액션이 임계치를 넘으면 TeamMemory/rejection_analyzer에 학습 시그널로 기록.
  '''
  from db.log_store import update_log_reactions, get_log
  body = await request.json()
  emoji = body.get('emoji', '👍')
  user = body.get('user', 'user')
  reactions = update_log_reactions(log_id, emoji, user)
  if reactions is None:
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={'error': 'log not found'})

  # 리액션 변경을 WebSocket으로 브로드캐스트 (채팅창 뱃지 갱신만, 저장 X)
  await event_bus.publish(LogEvent(
    agent_id='system',
    event_type='reaction_update',
    message='',
    data={'log_id': log_id, 'reactions': reactions},
  ))

  # 학습 시그널 — 이모지 종류/누적 수에 따라 자동 기록
  try:
    await _apply_reaction_learning(log_id, reactions, emoji)
  except Exception:
    logger.warning("리액션 학습 훅 실패", exc_info=True)

  return {'reactions': reactions}


# 긍정/부정 이모지 매핑
POSITIVE_EMOJIS = {'👍', '❤️', '🙌', '👏', '✨', '🔥', '💯', '🎉'}
NEGATIVE_EMOJIS = {'👎', '😡', '❌', '⚠️', '🤔'}
POSITIVE_THRESHOLD = 2  # 2표 이상이면 성공 패턴
NEGATIVE_THRESHOLD = 1  # 1표 받으면 rejection 기록


async def _apply_reaction_learning(log_id: str, reactions: dict, emoji: str) -> None:
  '''리액션이 임계치를 넘으면 학습 시스템에 시그널 기록.

  - 긍정 이모지 누적 ≥ 임계치 → TeamMemory에 success_pattern 교훈 저장
  - 부정 이모지 누적 ≥ 임계치 → rejection_analyzer에 실패 패턴 기록
  '''
  from db.log_store import get_log
  log = get_log(log_id)
  if not log:
    return
  # 에이전트 메시지만 학습 대상 (user/system 제외)
  if log['agent_id'] in ('user', 'system'):
    return
  # 빈 메시지 또는 너무 짧은 건 학습 제외
  if not log.get('message') or len(log['message'].strip()) < 10:
    return

  positive_total = sum(len(v) for k, v in reactions.items() if k in POSITIVE_EMOJIS)
  negative_total = sum(len(v) for k, v in reactions.items() if k in NEGATIVE_EMOJIS)
  agent_id = log['agent_id']
  msg_preview = log['message'][:200]

  # 이미 기록된 log_id는 재기록 방지 (data.learning_logged 플래그 사용)
  existing_data = log.get('data') or {}
  already = existing_data.get('learning_logged', {})

  # 👍 누적 → 성공 패턴 (Task #7)
  if emoji in POSITIVE_EMOJIS and positive_total >= POSITIVE_THRESHOLD and not already.get('positive'):
    from memory.team_memory import TeamMemory, SharedLesson
    from datetime import datetime, timezone
    try:
      TeamMemory().add_lesson(SharedLesson(
        id=f'react-pos-{log_id[:8]}',
        project_title='리액션 피드백',
        agent_name=agent_id,
        lesson=f'{agent_id}의 응답이 호응을 받음: "{msg_preview[:80]}"',
        category='success_pattern',
        timestamp=datetime.now(timezone.utc).isoformat(),
      ))
      _mark_learning_logged(log_id, 'positive')
      logger.info('리액션 학습: %s 긍정 패턴 기록 (%d표)', agent_id, positive_total)
    except Exception:
      logger.debug('TeamMemory 기록 실패', exc_info=True)

  # 👎 누적 → rejection 패턴 (Task #8)
  if emoji in NEGATIVE_EMOJIS and negative_total >= NEGATIVE_THRESHOLD and not already.get('negative'):
    from harness.rejection_analyzer import record_rejection
    try:
      record_rejection(
        feedback=f'{agent_id} 응답에 👎 피드백: "{msg_preview[:120]}"',
        task_type=f'user_reaction_{agent_id}',
      )
      _mark_learning_logged(log_id, 'negative')
      logger.info('리액션 학습: %s 부정 패턴 기록 (%d표)', agent_id, negative_total)
    except Exception:
      logger.debug('rejection 기록 실패', exc_info=True)


def _mark_learning_logged(log_id: str, kind: str) -> None:
  '''해당 log_id의 data에 learning_logged 플래그를 세팅 — 중복 학습 방지.'''
  import sqlite3, json
  from db.log_store import DB_PATH
  c = sqlite3.connect(str(DB_PATH))
  c.row_factory = sqlite3.Row
  row = c.execute('SELECT data FROM chat_logs WHERE id=?', (log_id,)).fetchone()
  if row:
    data = json.loads(row['data']) if row['data'] else {}
    flags = data.get('learning_logged', {})
    flags[kind] = True
    data['learning_logged'] = flags
    c.execute('UPDATE chat_logs SET data=? WHERE id=?', (json.dumps(data, ensure_ascii=False), log_id))
    c.commit()
  c.close()



@app.get('/api/ws-token')
async def get_ws_token():
  '''프론트엔드에서 WebSocket 연결 시 사용할 인증 토큰 반환 (same-origin CORS로 보호)'''
  return {'token': WS_AUTH_TOKEN}


@app.websocket('/ws/logs')
async def log_stream(ws: WebSocket, token: str = Query(default='')):
  '''실시간 에이전트 로그 스트림 (저장은 EventBus에서 처리)'''
  if token != WS_AUTH_TOKEN:
    await ws.close(code=4003, reason='Unauthorized')
    return
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


# --- 건의게시판 API ---


@app.post('/api/suggestions')
async def create_suggestion_api(request: Request):
  '''건의를 등록한다.'''
  from db.suggestion_store import create_suggestion
  body = await request.json()
  result = create_suggestion(
    agent_id=body.get('agent_id', 'user'),
    title=body.get('title', ''),
    content=body.get('content', ''),
    category=body.get('category', 'general'),
  )
  return result


@app.post('/api/suggestions/{suggestion_id}/promote')
async def promote_suggestion_api(suggestion_id: str):
  '''draft 건의를 pending으로 수동 승격하고 auto_triage를 돌린다.'''
  from db.suggestion_store import promote_draft, get_suggestion
  if not promote_draft(suggestion_id):
    current = get_suggestion(suggestion_id)
    if current is None:
      raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다.')
    raise HTTPException(status_code=400, detail=f'draft 상태가 아닙니다 (현재: {current["status"]}).')
  try:
    asyncio.create_task(auto_triage_new_suggestion(suggestion_id))
  except Exception:
    logger.debug('promote 후 auto_triage 호출 실패', exc_info=True)
  return get_suggestion(suggestion_id)


@app.patch('/api/suggestions/{suggestion_id}')
async def update_suggestion_api(suggestion_id: str, request: Request):
  '''건의 상태/답변을 업데이트한다.

  status 값:
    - 'accepted':  승인 — 건의의 suggestion_type에 따라 자동 분기
                   (prompt → TeamMemory/PromptEvolver / code → code_patcher)
    - 'rejected':  반려 — 제안자 AgentMemory에 억제 시그널
    - 기타 문자열: 단순 상태 변경
  '''
  from db.suggestion_store import update_suggestion, get_suggestion
  body = await request.json()
  new_status = body.get('status', '')
  success = update_suggestion(
    suggestion_id,
    status=new_status,
    response=body.get('response', ''),
  )
  if not success:
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')

  suggestion = get_suggestion(suggestion_id)

  # 승인/반려 감사 이벤트
  if new_status in ('accepted', 'rejected') and suggestion:
    from db.suggestion_store import log_event as _le
    _le(suggestion_id, 'approved' if new_status == 'accepted' else 'rejected', {
      'response': (body.get('response') or '')[:200],
    })

  # 승인 — 저장된 suggestion_type 보고 자동 분기
  if new_status == 'accepted' and suggestion:
    stype = suggestion.get('suggestion_type') or 'prompt'
    auto_merge_req = bool(body.get('auto_merge', True))  # 기본 on
    if stype == 'code':
      async def _run_patch():
        from improvement.code_patcher import apply_suggestion
        from db.suggestion_store import update_suggestion as _upd
        ok = await apply_suggestion(suggestion)
        if ok:
          _upd(suggestion_id, status='review_pending')
          if auto_merge_req:
            # 자동 병합 파이프라인 진입 (risky/rollback 시 중단)
            asyncio.create_task(_auto_merge_pipeline(suggestion_id))
        else:
          _upd(suggestion_id, status='pending')
      asyncio.create_task(_run_patch())
    else:
      # prompt 타입 — 즉시 반영
      await _apply_suggestion_to_prompts(suggestion)
      # done으로 마킹
      update_suggestion(suggestion_id, status='done')

  # 반려 — 제안자 에이전트 메모리에 "유사 건의 반복 금지" 시그널
  elif new_status == 'rejected' and suggestion:
    try:
      from memory.agent_memory import AgentMemory, MemoryRecord
      from datetime import datetime as _dt, timezone as _tz
      reject_reason = (suggestion.get('response') or '').strip()
      reason_suffix = f' — 반려 이유: {reject_reason}' if reject_reason else ''
      AgentMemory(suggestion['agent_id']).record(MemoryRecord(
        task_id=f'suggestion-{suggestion_id}',
        task_type='suggestion_rejected',
        success=False,
        feedback=f'건의 반려됨 — 유사 건의 반복 금지: "{suggestion["title"]}"{reason_suffix}',
        tags=['suggestion_rejected', suggestion.get('category', 'general')],
        timestamp=_dt.now(_tz.utc).isoformat(),
      ))
      if reject_reason:
        from config.team import display_name as _dn
        await event_bus.publish(LogEvent(
          agent_id='teamlead',
          event_type='response',
          message=f'❌ {_dn(suggestion["agent_id"])}의 건의 "{suggestion["title"][:40]}" 반려\n💬 이유: {reject_reason[:200]}',
        ))
    except Exception:
      logger.debug('반려 메모리 기록 실패', exc_info=True)

  return {'success': True}


async def auto_triage_new_suggestion(suggestion_id: str):
  '''새 건의가 등록되면 LLM이 실행 가치를 판정해 자동 accept/reject/hold.

  - accept: code → 자동 패치 + 자동 병합 파이프라인 / prompt|rule → 즉시 auto_apply
  - reject: 명확히 부적절·중복 → 즉시 rejected + 사유
  - hold: 애매하면 pending 유지 (사람 판단)

  Safety:
  - 이미 pending이 아니면 no-op (중복 트리거 방지)
  - 24h 트리거 한도 15건 (폭주 방지)
  - 회로 차단기: 24h 롤백 1+ → hold
  - SUGGESTION_AUTO_TRIAGE_OFF=1 이면 비활성화 (수동 모드)
  '''
  import os as _os
  import asyncio as _a
  import json as _j
  import re as _re
  from datetime import datetime, timezone, timedelta
  from db.suggestion_store import (
    get_suggestion, update_suggestion, log_event, count_rollbacks_since, _conn as _sconn,
  )
  from runners.claude_runner import run_claude_isolated

  if _os.environ.get('SUGGESTION_AUTO_TRIAGE_OFF', '').lower() in ('1', 'true', 'yes'):
    return

  # 갓 생성된 DB 트랜잭션 충돌 피하려 1초 유예
  await _a.sleep(1.0)

  s = get_suggestion(suggestion_id)
  if not s or s.get('status') != 'pending':
    return  # 이미 누가 처리함

  # 일일 triage 한도 체크 (24h 15건)
  cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
  c = _sconn()
  row = c.execute(
    'SELECT COUNT(*) FROM suggestion_events WHERE kind IN (?,?) AND ts>=? AND payload LIKE ?',
    ('auto_triage_accept', 'auto_triage_reject', cutoff, '%'),
  ).fetchone()
  c.close()
  if row and row[0] >= 15:
    log_event(suggestion_id, 'auto_triage_hold', {'reason': 'daily_budget_exhausted'})
    return

  # 회로 차단기
  if count_rollbacks_since(hours=24) > 0:
    log_event(suggestion_id, 'auto_triage_hold', {'reason': 'recent_rollback'})
    return

  # LLM 판정 (Haiku, 저비용)
  title = s.get('title', '')
  content = s.get('content', '')[:1200]
  stype = s.get('suggestion_type', 'prompt')
  target = s.get('target_agent', '') or '팀 전체'

  prompt = (
    f'건의가 접수됐습니다. 실행 가치를 보수적으로 판정하세요.\n\n'
    f'[타입] {stype}\n[대상] {target}\n[제목] {title}\n[내용]\n{content}\n\n'
    f'판정 기준:\n'
    f'- accept: 구체·실행 가능하고 범위 명확하며 이미 해결된 주제가 아닐 때\n'
    f'- reject: 추상 방법론만 언급, 이미 반영된 주제의 재탕, 범위 너무 큼, 아키텍처 의사결정 필요, 토론·질문 성격\n'
    f'- hold: 판단이 애매하거나 사람의 추가 맥락이 필요할 때 (보수적 기본값)\n\n'
    f'JSON만 출력: {{"decision":"accept|reject|hold","reason":"1문장"}}'
  )
  decision = 'hold'
  reason = 'LLM 응답 없음'
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=30.0)
    m = _re.search(r'\{[\s\S]*?\}', raw)
    if m:
      d = _j.loads(m.group())
      decision = (d.get('decision') or 'hold').strip()
      reason = (d.get('reason') or '').strip()
  except Exception as e:
    logger.warning('auto_triage LLM 실패: %s', e)
    return

  if decision == 'reject':
    update_suggestion(suggestion_id, status='rejected', response=f'자동 판정 반려: {reason}')
    log_event(suggestion_id, 'auto_triage_reject', {'reason': reason})
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'🚫 자동 반려 #{suggestion_id}: {reason[:150]}',
    ))
    return

  if decision != 'accept':
    log_event(suggestion_id, 'auto_triage_hold', {'reason': reason})
    return

  # accept — 타입별 분기
  log_event(suggestion_id, 'auto_triage_accept', {'reason': reason, 'suggestion_type': stype})
  await event_bus.publish(LogEvent(
    agent_id='teamlead', event_type='system_notice',
    message=f'✅ 자동 승인 #{suggestion_id}: {reason[:150]}',
  ))

  if stype in ('prompt', 'rule'):
    from improvement.auto_apply import apply_prompt_or_rule
    ok = await apply_prompt_or_rule(s, user_comment='')
    if ok:
      now_iso = datetime.now(timezone.utc).isoformat()
      cc = _sconn()
      cc.execute(
        'UPDATE suggestions SET status=?, auto_applied=1, auto_applied_at=? WHERE id=?',
        ('done', now_iso, suggestion_id),
      )
      cc.commit(); cc.close()
      log_event(suggestion_id, 'auto_applied', {'via': 'triage', 'target_agent': s.get('target_agent')})
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🤖 자동 반영 #{suggestion_id} — 24h 내 되돌리기 가능',
      ))
  else:  # code
    update_suggestion(suggestion_id, status='accepted')
    log_event(suggestion_id, 'approved', {'via': 'triage'})
    async def _run():
      from improvement.code_patcher import apply_suggestion
      from db.suggestion_store import update_suggestion as _upd
      ok = await apply_suggestion(s)
      if ok:
        _upd(suggestion_id, status='review_pending')
        _a.create_task(_auto_merge_pipeline(suggestion_id))
      else:
        _upd(suggestion_id, status='pending')
    _a.create_task(_run())


async def _auto_merge_pipeline(suggestion_id: str, max_iters: int = 3):
  '''승인 후 Claude 패치가 끝난 상태에서 호출.

  AI 리뷰 → merge/needs_fix/discard 판정에 따라 자동 분기:
  - merge: 자동 병합 (risky/스코프/회로차단기/일일한도 통과 시만)
  - needs_fix: 최대 N회 자동 보완, 중간에 merge 되면 병합
  - discard: 자동 폐기
  - risky/한도 초과/회로차단: review_pending 유지 (수동)
  '''
  import asyncio as _a
  from datetime import datetime, timezone, timedelta
  from db.suggestion_store import (
    get_suggestion, update_suggestion, log_event, count_rollbacks_since, _conn as _sconn,
  )
  from improvement.code_patcher import _PATCH_LOCK, _git, _current_branch, _check_scope

  branch = f'improvement/{suggestion_id}'

  # 회로 차단기 — 최근 24h 코드 롤백(어떤 건의든) 있으면 자동 병합 전면 중단
  recent_rollbacks = count_rollbacks_since(hours=24)
  if recent_rollbacks > 0:
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'⚠️ 최근 24h 롤백 {recent_rollbacks}건 — 자동 병합 중단, 수동 검토로 전환 (#{suggestion_id})',
    ))
    return

  # 일일 한도 — 24h 자동 병합 5건 초과 시 중단
  cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
  c = _sconn()
  row = c.execute(
    'SELECT COUNT(*) FROM suggestion_events WHERE kind=? AND ts>=? AND payload LIKE ?',
    ('branch_merged', cutoff, '%"auto":true%'),
  ).fetchone()
  c.close()
  today_auto = row[0] if row else 0
  if today_auto >= 5:
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'🛑 일일 자동 병합 한도(5/24h) 도달 — 이후는 수동 검토 (#{suggestion_id})',
    ))
    return

  async def _try_merge() -> bool:
    '''AI 리뷰 후 조건 만족 시 병합. 성공 True.'''
    try:
      explain = await explain_suggestion_branch(suggestion_id)
    except Exception as e:
      logger.warning('auto-merge explain 실패: %s', e)
      return False
    if not isinstance(explain, dict) or explain.get('error'):
      return False

    verdict = explain.get('verdict', 'review_needed')
    rec = explain.get('recommendation', 'needs_fix')
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'🤖 자동 파이프라인 판정 #{suggestion_id}: verdict={verdict}, recommend={rec}',
    ))

    if rec == 'discard':
      # 자동 폐기
      _git(['branch', '-D', branch])
      update_suggestion(suggestion_id, status='rejected', response='자동 파이프라인 폐기 권장')
      log_event(suggestion_id, 'branch_discarded', {'auto': True, 'verdict': verdict})
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🗑️ 자동 폐기 #{suggestion_id} — {explain.get("recommendation_reason", "")[:150]}',
      ))
      return True

    if rec != 'merge':
      return False
    if verdict == 'risky':
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'⚠️ 자동 병합 중단 #{suggestion_id} — AI가 risky 판정. 수동 검토 필요.',
      ))
      return False

    # 스코프 재확인
    _, files_out = _run_git(['diff', '--name-only', f'main...{branch}'])
    _, stat_out = _run_git(['diff', '--stat', f'main...{branch}'])
    scope_ok, scope_reason = _check_scope(
      get_suggestion(suggestion_id) or {},
      [f for f in files_out.splitlines() if f], stat_out,
    )
    if not scope_ok:
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🚫 자동 병합 중단 #{suggestion_id} — 스코프 위반: {scope_reason}',
      ))
      return False

    # 실제 병합 (PATCH_LOCK 내부)
    async with _PATCH_LOCK:
      _, cur = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
      if cur.strip() != 'main':
        _run_git(['checkout', 'main'])
      _, tip = _run_git(['rev-parse', branch])
      tip = tip.strip()
      code, out = _run_git(['merge', '--no-ff', '-m', f'merge: improvement/{suggestion_id} (auto)', branch])
      if code != 0:
        _run_git(['merge', '--abort'])
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'❌ 자동 병합 실패 #{suggestion_id}: {out[:200]}',
        ))
        return False
      _run_git(['branch', '-d', branch])
      update_suggestion(suggestion_id, status='done')
      log_event(suggestion_id, 'branch_merged', {'tip': tip, 'auto': True, 'verdict': verdict})

      # risks를 follow-up으로 등록 (기존 merge 엔드포인트와 동일)
      risks = explain.get('risks') or []
      from db.suggestion_store import create_suggestion
      fu = 0
      for risk in risks[:5]:
        r = (risk or '').strip()
        if len(r) < 15:
          continue
        try:
          create_suggestion(
            agent_id='teamlead',
            title=f'[follow-up #{suggestion_id}] {r[:60]}'[:80],
            content=f'{r}\n\n[자동 파이프라인 — 원 건의 #{suggestion_id} 병합 후 잔존 위험]',
            category='프로세스 개선', target_agent='',
          )
          fu += 1
        except Exception:
          pass
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='response',
        message=(
          f'🔀 자동 병합 완료 #{suggestion_id} → main에 반영됨.'
          + (f'\n🔗 follow-up {fu}건 등록' if fu else '')
          + '\n⚠️ 서버 재시작이 필요합니다 (사이드바 재시작 버튼).'
        ),
      ))
      return True

  # 1차 시도
  if await _try_merge():
    return

  # needs_fix면 자동 보완 루프 진입
  update_suggestion(suggestion_id, status='supplementing')
  import time as _time
  loop_start = _time.monotonic()
  LOOP_BUDGET = 25 * 60  # 25분 예산
  prev_risks_sig = ''

  try:
    for it in range(1, max_iters + 1):
      if _time.monotonic() - loop_start > LOOP_BUDGET:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'⏱️ [자동] #{suggestion_id} 전체 보완 예산(25분) 초과 — 중단',
        ))
        break

      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🛠️ [자동] 보완 {it}/{max_iters} 시작 #{suggestion_id}',
      ))
      ok, risks_sig = await _run_one_supplement_iter(suggestion_id, branch, it, max_iters)
      if not ok:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'⏹️ [자동] 보완 {it}회 실패 또는 변화 없음 — 루프 종료',
        ))
        break
      # 수렴 실패 감지
      if prev_risks_sig and risks_sig == prev_risks_sig:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'🔁 [자동] #{suggestion_id} 위험사항 변화 없음 — 수렴 실패, 중단',
        ))
        break
      prev_risks_sig = risks_sig
      # 병합 재시도
      if await _try_merge():
        return
  finally:
    s = get_suggestion(suggestion_id)
    if s and s.get('status') == 'supplementing':
      update_suggestion(suggestion_id, status='review_pending')
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=(
          f'ℹ️ 자동 파이프라인 #{suggestion_id} 종료 — review_pending으로 전환. '
          f'"변경사항 보기"에서 수동 결정 바랍니다.'
        ),
      ))


async def _run_one_supplement_iter(suggestion_id: str, branch: str, it: int, max_iters: int) -> tuple[bool, str]:
  '''supplement 1회 실행. (성공, risks_signature) 반환.

  성공 = Claude가 커밋 생성 + 새 explain 완료.
  '''
  from db.suggestion_store import get_suggestion, log_event
  from improvement.code_patcher import _PATCH_LOCK, _git, _current_branch, _check_scope
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError
  from pathlib import Path as _P

  async with _PATCH_LOCK:
    suggestion = get_suggestion(suggestion_id) or {}
    _, cur_tip = _run_git(['rev-parse', branch])
    cur_tip = cur_tip.strip()
    explain = _BRANCH_EXPLAIN_CACHE.get(cur_tip) or {}
    risks = explain.get('risks') or []
    prev_intent = explain.get('intent', '')

    original_branch = _current_branch()
    rc, out = _git(['checkout', branch])
    if rc != 0:
      return (False, '')

    prompt = (
      f'# AI Office 자가개선 — 자동 보완 반복 {it}/{max_iters}\n\n'
      f'프로젝트 루트: {_P(__file__).parent.parent}\n\n'
      f'## 원 건의 #{suggestion_id}\n'
      f'제목: {suggestion.get("title", "")}\n내용: {suggestion.get("content", "")[:1500]}\n\n'
      f'## 이전 구현 요약\n{prev_intent or "(없음)"}\n\n'
      f'## 보완해야 할 위험·부족분\n'
      + ('\n'.join(f'- {r}' for r in risks) if risks else '(없음)')
      + f'\n\n## 작업 지침\n'
      f'- 기존 구현에 **추가·보완**만. 덮어쓰지 마라.\n'
      f'- 위 위험·부족분만 해결. 범위 벗어난 건 건드리지 마라.\n'
      f'- 스코프 제약(금지 파일·15파일 500줄 한도) 엄격 준수.\n'
      f'- 변경 파일·이유 요약.'
    )
    try:
      result = await run_claude_isolated(prompt=prompt, timeout=600.0, max_turns=20)
    except ClaudeRunnerError as e:
      _git(['checkout', original_branch])
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'❌ [자동 {it}/{max_iters}] Claude 오류: {e}',
      ))
      return (False, '')

    _, changed = _git(['diff', '--name-only', 'HEAD'])
    _, untracked = _git(['ls-files', '--others', '--exclude-standard'])
    if not (changed.strip() or untracked.strip()):
      _git(['checkout', original_branch])
      return (False, '')

    # 스코프 체크 — 위반 시 이 iter만 폐기 (브랜치 유지)
    file_list = [f for f in changed.strip().splitlines() if f]
    _, stat_out = _git(['diff', '--stat', 'HEAD'])
    scope_ok, scope_reason = _check_scope(suggestion, file_list, stat_out)
    if not scope_ok:
      _git(['checkout', '.'])  # 변경 폐기
      _git(['checkout', original_branch])
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🚫 [자동 {it}/{max_iters}] 스코프 위반으로 iter 폐기: {scope_reason}',
      ))
      return (False, '')

    _git(['add', '-A'])
    _git(['commit', '-m', f'supplement(#{suggestion_id}): auto iter {it}/{max_iters}'])
    _, new_tip = _run_git(['rev-parse', branch])
    new_tip = new_tip.strip()
    _BRANCH_EXPLAIN_CACHE.pop(cur_tip, None)
    log_event(suggestion_id, 'branch_supplemented', {
      'iter': it, 'old_tip': cur_tip, 'new_tip': new_tip, 'auto': True,
    })
    _git(['checkout', original_branch])

  # 락 해제 후 explain (다른 iter 차단 불필요)
  try:
    new_explain = await explain_suggestion_branch(suggestion_id)
  except Exception:
    return (True, '')
  new_risks = (new_explain or {}).get('risks') or []
  sig = '|'.join(sorted((r or '')[:60] for r in new_risks))
  return (True, sig)


def _extract_rule_body(content: str) -> str:
  '''자동 등록 건의의 content에서 실제 발언 본문만 추출. 메타 헤더·트리거·카테고리 안내 제거.'''
  import re
  m = re.search(r'의 발언:\s*"([^"]+)"', content)
  if m:
    return m.group(1).strip()
  # 수동 건의 등 — 앞쪽 문단만 사용 (첫 메타 라인 이후 잘라냄)
  lines = []
  for line in content.splitlines():
    s = line.strip()
    if not s:
      if lines:
        break
      continue
    if s.startswith('[') or s.startswith('단계:') or s.startswith('카테고리:') or s.startswith('트리거'):
      continue
    lines.append(s)
  return ' '.join(lines)[:400] if lines else content[:300]


async def _apply_suggestion_to_prompts(suggestion: dict) -> None:
  '''프롬프트 수준 반영 — team_memory(전체 공유) + prompt_evolver(제안자 개인 규칙).'''
  from memory.team_memory import TeamMemory, SharedLesson
  from improvement.prompt_evolver import PromptEvolver, PromptRule
  from datetime import datetime, timezone

  sid = suggestion['id']
  agent_id = suggestion['agent_id']
  target_agent = (suggestion.get('target_agent') or '').strip()
  apply_to = target_agent or agent_id  # target 있으면 대상, 없으면 제안자 본인
  title = suggestion['title']
  content = suggestion['content']
  category = suggestion.get('category', 'general')
  user_comment = (suggestion.get('response') or '').strip()
  now_iso = datetime.now(timezone.utc).isoformat()
  rule_body = _extract_rule_body(content)  # 메타 제거한 발언 본문
  comment_suffix = f'\n[사용자 코멘트] {user_comment}' if user_comment else ''

  # 1. 팀 공유 메모리에 교훈으로 등록 → 모든 에이전트 시스템 프롬프트에 자동 주입
  try:
    TeamMemory().add_lesson(SharedLesson(
      id=f'suggestion-{sid}',
      project_title='건의 수용',
      agent_name=apply_to,
      lesson=f'{rule_body}{comment_suffix}',
      category='process_improvement',
      timestamp=now_iso,
    ))
  except Exception:
    logger.debug('TeamMemory add_lesson 실패', exc_info=True)

  # 2. 대상 에이전트의 PromptEvolver에 규칙 추가
  try:
    evolver = PromptEvolver()
    existing = evolver.load_rules(apply_to)
    existing.append(PromptRule(
      id=f'suggestion-{sid}',
      created_at=now_iso,
      source='manual',
      category=category,
      rule=f'{rule_body}{comment_suffix}',
      evidence=f'사용자 승인된 건의 #{sid} (제안자: {agent_id})' + (f' — {user_comment[:120]}' if user_comment else ''),
      priority='high',
      active=True,
    ))
    # 활성 규칙 10개 초과 시 hit_count 높은(=효과 낮은) 순으로 비활성화 (보존)
    from improvement.prompt_evolver import MAX_RULES_PER_AGENT as _MAX
    active = [r for r in existing if r.active]
    inactive = [r for r in existing if not r.active]
    if len(active) > _MAX:
      sorted_rules = sorted(active, key=lambda r: (r.hit_count, r.created_at))
      for r in sorted_rules[_MAX:]:
        r.active = False
      existing = sorted_rules + inactive
    else:
      existing = active + inactive
    evolver.save_rules(apply_to, existing)
  except Exception:
    logger.debug('PromptEvolver save_rules 실패', exc_info=True)

  # 3. 채팅에 공지
  from config.team import display_name
  comment_line = f'\n💬 코멘트: {user_comment[:200]}' if user_comment else ''
  target_line = f' ({display_name(apply_to)} 규칙에 적용)' if target_agent else ''
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=(
      f'✅ {display_name(agent_id)}의 건의 "{title[:40]}" 수용{target_line} → '
      f'팀 메모리 + 에이전트 프롬프트에 즉시 반영했습니다.{comment_line}'
    ),
  ))


@app.get('/api/suggestions/{suggestion_id}/events')
async def get_suggestion_events(suggestion_id: str):
  '''건의의 감사 이벤트 시계열.'''
  from db.suggestion_store import list_events
  return list_events(suggestion_id=suggestion_id, limit=200)


@app.get('/api/suggestion-events')
async def get_all_events(limit: int = 200):
  '''전체 감사 이벤트 최신순 (분석용).'''
  from db.suggestion_store import list_events
  return list_events(limit=limit)


@app.delete('/api/suggestions/{suggestion_id}')
async def delete_suggestion_api(suggestion_id: str):
  '''건의를 삭제한다.'''
  from db.suggestion_store import delete_suggestion
  if not delete_suggestion(suggestion_id):
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')
  return {'deleted': suggestion_id}


# --- 자가개선 브랜치 검토/병합/폐기 ---

def _run_git(args: list[str]) -> tuple[int, str]:
  import subprocess
  from pathlib import Path
  root = Path(__file__).parent.parent
  r = subprocess.run(['git'] + args, cwd=str(root), capture_output=True, text=True)
  return r.returncode, (r.stdout + r.stderr).strip()


@app.get('/api/suggestions/{suggestion_id}/branch')
async def get_suggestion_branch_diff(suggestion_id: str):
  '''improvement/{id} 브랜치의 diff + 파일 목록을 반환.'''
  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')
  _, files = _run_git(['diff', '--name-only', f'main...{branch}'])
  _, stat = _run_git(['diff', '--stat', f'main...{branch}'])
  _, patch = _run_git(['diff', f'main...{branch}'])
  return {
    'branch': branch,
    'files': files.splitlines() if files else [],
    'stat': stat,
    'diff': patch[:80000],  # 너무 크면 잘라냄
  }


_BRANCH_EXPLAIN_CACHE: dict[str, dict] = {}

@app.get('/api/suggestions/{suggestion_id}/branch/explain')
async def explain_suggestion_branch(suggestion_id: str):
  '''변경사항의 의도·효과·위험을 AI로 분석해 반환 (커밋 해시 기준 캐시).'''
  from db.suggestion_store import get_suggestion
  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')
  _, tip = _run_git(['rev-parse', branch])
  tip = tip.strip()
  cached = _BRANCH_EXPLAIN_CACHE.get(tip)
  if cached:
    return cached

  _, stat = _run_git(['diff', '--stat', f'main...{branch}'])
  _, patch = _run_git(['diff', f'main...{branch}'])
  _, log = _run_git(['log', f'main..{branch}', '--pretty=%s%n%b', '-n', '3'])
  suggestion = get_suggestion(suggestion_id) or {}

  from runners.gemini_runner import run_gemini
  from runners.claude_runner import run_claude_isolated
  import json as _j, re as _re

  prompt = (
    f'당신은 시니어 엔지니어 리뷰어입니다. 아래 변경사항을 분석해 JSON만 출력하세요.\n\n'
    f'[원 건의]\n'
    f'제목: {suggestion.get("title", "(미상)")}\n'
    f'내용: {suggestion.get("content", "")[:800]}\n\n'
    f'[커밋 메시지]\n{log[:600]}\n\n'
    f'[변경 통계]\n{stat}\n\n'
    f'[패치]\n{patch[:30000]}\n\n'
    f'출력 스키마:\n'
    f'{{\n'
    f'  "intent": "이 변경의 의도 (건의를 어떻게 해석해서 무엇을 고쳤는지) 2-3문장",\n'
    f'  "effects": ["기대 효과 1", "기대 효과 2"],\n'
    f'  "risks": ["위험/주의점 1", "위험/주의점 2"],\n'
    f'  "verdict": "merge_safe|review_needed|risky",\n'
    f'  "verdict_reason": "판단 근거 한 문장",\n'
    f'  "recommendation": "merge|discard|needs_fix",\n'
    f'  "recommendation_reason": "왜 그 행동을 권장하는지 2-3문장 (구체 이유)"\n'
    f'}}\n'
    f'규칙:\n'
    f'- 의도/효과/위험은 구체적으로. 일반론 금지.\n'
    f'- 실제 수정된 함수·파일·동작 변화를 근거로 작성.\n'
    f'- 위험이 없어 보여도 최소 1개는 찾아서 기술 (테스트 누락/엣지 케이스/되돌리기 어려움 등).\n'
    f'- verdict는 엄격하게: 어지간하면 review_needed.\n'
    f'- recommendation:\n'
    f'  · merge: 의도대로 잘 구현됐고 위험이 경미해 바로 병합해도 OK\n'
    f'  · needs_fix: 방향은 맞지만 수정·보완 필요 (폐기하고 재시도 또는 수동 보강)\n'
    f'  · discard: 건의 의도와 다르거나 잘못 구현돼 버리는 게 맞음\n'
    f'- recommendation_reason은 사용자가 결정할 때 참고할 수 있도록 실질적으로 작성.'
  )
  data = None
  last_err = ''
  # 1차: Claude Haiku (큰 컨텍스트에 안정적)
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=90.0)
    m = _re.search(r'\{[\s\S]*\}', raw)
    if m:
      data = _j.loads(m.group())
  except Exception as e:
    last_err = f'claude: {type(e).__name__}: {str(e)[:120]}'
    logger.warning('Claude explain 실패 → Gemini 폴백: %s', last_err)

  # 2차: Gemini 폴백
  if not isinstance(data, dict):
    try:
      raw = await run_gemini(prompt=prompt, timeout=120.0)
      m = _re.search(r'\{[\s\S]*\}', raw)
      if m:
        data = _j.loads(m.group())
    except Exception as e:
      last_err = last_err + f' | gemini: {type(e).__name__}: {str(e)[:120]}'
      logger.warning('Gemini explain 실패: %s', last_err)

  if not isinstance(data, dict):
    return {'error': f'AI 분석 실패 — {last_err or "응답 없음"}'}

  from db.suggestion_store import list_events as _list_ev
  supplement_count = sum(1 for ev in _list_ev(suggestion_id=suggestion_id, limit=50) if ev.get('kind') == 'branch_supplemented')

  result = {
    'intent': (data.get('intent') or '').strip(),
    'effects': [str(x).strip() for x in (data.get('effects') or []) if x],
    'risks': [str(x).strip() for x in (data.get('risks') or []) if x],
    'verdict': data.get('verdict', 'review_needed'),
    'verdict_reason': (data.get('verdict_reason') or '').strip(),
    'recommendation': data.get('recommendation', 'needs_fix'),
    'recommendation_reason': (data.get('recommendation_reason') or '').strip(),
    'supplement_count': supplement_count,
    'commit': tip,
  }
  _BRANCH_EXPLAIN_CACHE[tip] = result
  return result


@app.post('/api/suggestions/{suggestion_id}/branch/merge')
async def merge_suggestion_branch(suggestion_id: str, request: Request):
  '''improvement/{id}를 현재 브랜치(main)로 병합 + 상태 done + 위험 follow-up 자동 등록.

  게이트:
  - AI 리뷰 verdict='risky'면 409 (쿼리 ?confirm_risky=true로 우회)
  - pytest/ruff 체크 (쿼리 ?skip_tests=true로 생략 가능)
  '''
  from db.suggestion_store import update_suggestion, get_suggestion, create_suggestion, log_event
  confirm_risky = request.query_params.get('confirm_risky') == 'true'
  # 게이트는 명시적 opt-in일 때만 동작 (ruff/pytest가 프로젝트 준비 안 돼있으면 항상 실패)
  run_tests = request.query_params.get('run_tests') == 'true'
  skip_tests = not run_tests

  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')
  _, cur = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
  if cur.strip() != 'main':
    raise HTTPException(status_code=409, detail=f'현재 브랜치가 main이 아닙니다: {cur}')

  # 병합 전에 브랜치 tip을 확보 — explain 캐시 키
  _, tip = _run_git(['rev-parse', branch])
  tip = tip.strip()

  # risky 게이트
  explain_cache = _BRANCH_EXPLAIN_CACHE.get(tip)
  if explain_cache and explain_cache.get('verdict') == 'risky' and not confirm_risky:
    raise HTTPException(
      status_code=409,
      detail='RISKY_UNCONFIRMED: AI 리뷰가 위험으로 판정했습니다. ?confirm_risky=true로 강제하세요.',
    )

  # 스코프 게이트 — 병합 직전에도 최종 확인
  from improvement.code_patcher import _check_scope
  suggestion_full = get_suggestion(suggestion_id) or {}
  _, files_out = _run_git(['diff', '--name-only', f'main...{branch}'])
  _, stat_out = _run_git(['diff', '--stat', f'main...{branch}'])
  scope_ok, scope_reason = _check_scope(suggestion_full, [f for f in files_out.splitlines() if f], stat_out)
  if not scope_ok and not confirm_risky:
    raise HTTPException(
      status_code=409,
      detail=f'SCOPE_VIOLATION: {scope_reason}. 확인 후 ?confirm_risky=true로 강제하거나 폐기하세요.',
    )

  # 테스트/린트 게이트
  if not skip_tests:
    import asyncio as _a
    import subprocess as _sp

    async def _check(cmd: list[str], cwd: str) -> tuple[int, str]:
      proc = await _a.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=_sp.PIPE, stderr=_sp.STDOUT,
      )
      try:
        out, _ = await _a.wait_for(proc.communicate(), timeout=300)
      except _a.TimeoutError:
        proc.kill()
        return (124, 'timeout')
      return (proc.returncode, (out or b'').decode(errors='ignore')[-3000:])

    from pathlib import Path as _P
    root = _P(__file__).parent.parent.parent
    server_dir = _P(__file__).parent

    # 병합 전에 브랜치를 임시 worktree로 체크아웃 (현재 main을 변경하지 않음)
    import tempfile as _tf
    tmpdir = _tf.mkdtemp(prefix='improvement-wt-')
    _, wt_out = _run_git(['worktree', 'add', '--detach', tmpdir, branch])
    try:
      wt_server = str(_P(tmpdir) / 'server')
      rc_lint, out_lint = await _check(['uv', 'run', 'ruff', 'check', '.'], wt_server)
      rc_test, out_test = (0, 'skipped')
      # tests 경로가 있으면 실행
      if (_P(wt_server) / 'tests').exists():
        rc_test, out_test = await _check(['uv', 'run', 'pytest', '-x', '-q'], wt_server)
      if rc_lint != 0 or rc_test != 0:
        log_event(suggestion_id, 'test_failed', {
          'lint_rc': rc_lint, 'test_rc': rc_test,
          'lint_tail': out_lint[-500:], 'test_tail': out_test[-500:],
        })
        update_suggestion(
          suggestion_id,
          response=f'테스트/린트 실패 — lint_rc={rc_lint}, test_rc={rc_test}',
        )
        raise HTTPException(
          status_code=409,
          detail=f'TEST_FAILED: lint_rc={rc_lint}, test_rc={rc_test}. 확인 후 수정하거나 ?skip_tests=true로 우회.',
        )
    finally:
      _run_git(['worktree', 'remove', '--force', tmpdir])

  code, out = _run_git(['merge', '--no-ff', '-m', f'merge: improvement/{suggestion_id}', branch])
  if code != 0:
    _run_git(['merge', '--abort'])
    raise HTTPException(status_code=500, detail=f'병합 실패 — 수동 확인 필요: {out[:300]}')
  _run_git(['branch', '-d', branch])
  update_suggestion(suggestion_id, status='done')
  suggestion = get_suggestion(suggestion_id)
  log_event(suggestion_id, 'branch_merged', {'tip': tip})

  # 병합 후 follow-up 자동 등록 — AI 리뷰의 risks를 새 건의로 승격
  follow_ups = 0
  explain = _BRANCH_EXPLAIN_CACHE.get(tip)
  if explain and isinstance(explain.get('risks'), list):
    for risk in explain['risks'][:5]:
      risk = (risk or '').strip()
      if not risk or len(risk) < 15:
        continue
      try:
        title = f'[follow-up #{suggestion_id}] {risk[:60]}'
        content = (
          f'{risk}\n\n'
          f'[후속 조치 필요 — 자동 등록]\n'
          f'원 건의: #{suggestion_id} "{(suggestion or {}).get("title", "")[:60]}"\n'
          f'AI 리뷰 판정: {explain.get("verdict", "review_needed")}\n'
          f'근거: {explain.get("verdict_reason", "")}\n'
        )
        fu_created = create_suggestion(
          agent_id='teamlead', title=title[:80], content=content,
          category='프로세스 개선', target_agent='',
        )
        follow_ups += 1
        # follow-up도 auto_triage
        asyncio.create_task(auto_triage_new_suggestion(fu_created['id']))
      except Exception:
        logger.debug('follow-up 등록 실패', exc_info=True)

  followup_line = f'\n🔗 후속 조치 {follow_ups}건 자동 등록됨 (건의게시판 확인)' if follow_ups else ''
  from config.team import display_name  # noqa: F401
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=(
      f'🔀 건의 #{suggestion_id} 브랜치 병합 완료 → main에 반영됐습니다.{followup_line}\n'
      f'⚠️ 서버 재시작이 필요합니다 (Python 모듈 재로딩).'
    ),
  ))
  return {'merged': True, 'suggestion_id': suggestion_id, 'follow_ups': follow_ups}


@app.post('/api/suggestions/{suggestion_id}/rollback')
async def rollback_auto_applied(suggestion_id: str):
  '''자동 반영된 건의를 되돌린다 — 24시간 유예 내에서만 가능.'''
  from db.suggestion_store import get_suggestion, update_suggestion, _conn as _sconn
  from improvement.auto_apply import rollback_prompt_or_rule
  from datetime import datetime, timezone, timedelta
  suggestion = get_suggestion(suggestion_id)
  if not suggestion:
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')
  if int(suggestion.get('auto_applied') or 0) != 1:
    raise HTTPException(status_code=400, detail='자동 반영된 건의만 롤백 가능합니다')
  applied_at = suggestion.get('auto_applied_at') or ''
  try:
    applied_dt = datetime.fromisoformat(applied_at.replace('Z', '+00:00'))
    if datetime.now(timezone.utc) - applied_dt > timedelta(hours=24):
      raise HTTPException(status_code=410, detail='24시간 롤백 유예 기간이 지났습니다')
  except HTTPException:
    raise
  except Exception:
    raise HTTPException(status_code=400, detail='반영 시각 파싱 실패')

  removed = rollback_prompt_or_rule(suggestion_id)
  c = _sconn()
  c.execute(
    "UPDATE suggestions SET status='rejected', auto_applied=0, response=? WHERE id=?",
    ('자동 반영 롤백 (사용자 되돌리기)', suggestion_id),
  )
  c.commit(); c.close()
  from db.suggestion_store import log_event as _logev
  _logev(suggestion_id, 'rollback', {
    'target_agent': suggestion.get('target_agent') or '',
    'removed_rules': removed.get('rules', 0),
    'removed_lessons': removed.get('lessons', 0),
  })
  from config.team import display_name
  await event_bus.publish(LogEvent(
    agent_id='teamlead', event_type='system_notice',
    message=(
      f'↩️ 자동 반영 롤백: #{suggestion_id} "{suggestion["title"][:40]}" '
      f'— 규칙 {removed["rules"]}건 · 교훈 {removed["lessons"]}건 제거'
    ),
  ))
  return {'rolled_back': True, 'removed': removed}


@app.post('/api/suggestions/{suggestion_id}/branch/supplement')
async def supplement_suggestion_branch(suggestion_id: str, request: Request):
  '''improvement/{id} 브랜치에 Claude를 최대 max_iterations 반복 실행해 보완.

  각 반복:
    1) Claude 재실행(지난 risks + 사용자 지시)
    2) 변경 커밋
    3) 새 explain 생성
    4) recommendation이 merge 또는 discard면 즉시 중단
  '''
  from db.suggestion_store import get_suggestion, log_event, update_suggestion
  from improvement.code_patcher import _PATCH_LOCK, _git, _current_branch
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError
  body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
  extra_instruction = (body.get('instruction') or '').strip()
  try:
    max_iters = int(body.get('max_iterations') or 3)
  except Exception:
    max_iters = 3
  max_iters = max(1, min(max_iters, 5))

  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')

  if _PATCH_LOCK.locked():
    raise HTTPException(status_code=409, detail='다른 코드 패치 진행 중 — 완료 후 재시도')

  async def _run():
    from pathlib import Path as _P
    root = _P(__file__).parent.parent.parent
    async with _PATCH_LOCK:
      # UI 상태: supplementing
      update_suggestion(suggestion_id, status='supplementing')
      suggestion = get_suggestion(suggestion_id) or {}
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🛠️ 건의 #{suggestion_id} 보완 시작 — 최대 {max_iters}회 반복',
      ))
      original_branch = _current_branch()

      success_iters = 0
      final_verdict = 'needs_fix'
      prev_risks_sig = ''
      import time as _time
      loop_start = _time.monotonic()
      LOOP_BUDGET_SEC = 25 * 60  # 전체 보완 루프 최대 25분

      for it in range(1, max_iters + 1):
        if _time.monotonic() - loop_start > LOOP_BUDGET_SEC:
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'⏱️ [{it}/{max_iters}] 전체 보완 예산(25분) 초과 — 루프 중단',
          ))
          break
        _, cur_tip = _run_git(['rev-parse', branch])
        cur_tip = cur_tip.strip()
        explain = _BRANCH_EXPLAIN_CACHE.get(cur_tip) or {}
        risks = explain.get('risks') or []
        prev_intent = explain.get('intent', '')

        rc, out = _git(['checkout', branch])
        if rc != 0:
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'❌ [{it}/{max_iters}] 보완 중단 — 체크아웃 오류: {out[:200]}',
          ))
          break

        prompt = (
          f'# AI Office 자가개선 — 보완 반복 {it}/{max_iters}\n\n'
          f'프로젝트 루트: {root}\n\n'
          f'## 원 건의 #{suggestion_id}\n'
          f'제목: {suggestion.get("title", "")}\n'
          f'내용: {suggestion.get("content", "")[:1500]}\n\n'
          f'## 이전 구현 요약\n{prev_intent or "(없음)"}\n\n'
          f'## 보완해야 할 위험·부족분 (AI 리뷰)\n'
          + ('\n'.join(f'- {r}' for r in risks) if risks else '(없음)')
          + (f'\n\n## 사용자 추가 지시 (초기)\n{extra_instruction}' if extra_instruction and it == 1 else '')
          + (
            f'\n\n## 작업 지침\n'
            f'- 이미 브랜치에 구현이 있다. 덮어쓰지 말고 **추가·보완**.\n'
            f'- 위 위험·부족분을 우선 해결. 범위 벗어난 건 건드리지 마라.\n'
            f'- 기존 스타일 유지. 변경 파일·이유 마지막에 요약.'
          )
        )

        try:
          result = await run_claude_isolated(prompt=prompt, timeout=600.0, max_turns=20)
        except ClaudeRunnerError as e:
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'❌ [{it}/{max_iters}] Claude 오류: {e}',
          ))
          break

        _, changed = _git(['diff', '--name-only', 'HEAD'])
        _, untracked = _git(['ls-files', '--others', '--exclude-standard'])
        if not (changed.strip() or untracked.strip()):
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'ℹ️ [{it}/{max_iters}] 추가 변경 없음 — 루프 종료',
          ))
          break

        _git(['add', '-A'])
        _git(['commit', '-m', f'supplement(#{suggestion_id}): iter {it}/{max_iters} — AI 리뷰 위험 보완'])
        _, new_tip = _run_git(['rev-parse', branch])
        new_tip = new_tip.strip()
        _BRANCH_EXPLAIN_CACHE.pop(cur_tip, None)
        log_event(suggestion_id, 'branch_supplemented', {
          'iter': it, 'old_tip': cur_tip, 'new_tip': new_tip,
        })
        success_iters += 1

        # 원 브랜치 복귀 후 새 explain 수행 (recommendation 판정용)
        _git(['checkout', original_branch])
        try:
          new_explain = await _compute_branch_explain(suggestion_id, branch)
          final_verdict = new_explain.get('recommendation', 'needs_fix')
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=(
              f'🛠️ [{it}/{max_iters}] 보완 커밋 완료 — AI 판단: {final_verdict}\n'
              f'Claude 요약: {result[:200]}'
            ),
          ))
          if final_verdict in ('merge', 'discard'):
            break
          # 수렴 실패 감지 — risks가 같거나 오히려 늘면 루프 가치 없음
          new_risks = new_explain.get('risks') or []
          sig = '|'.join(sorted(r[:60] for r in new_risks))
          if prev_risks_sig and sig == prev_risks_sig:
            await event_bus.publish(LogEvent(
              agent_id='teamlead', event_type='system_notice',
              message=f'🔁 [{it}/{max_iters}] 위험사항이 변하지 않음 — 수렴 실패로 중단. 수동 확인 권장.',
            ))
            break
          prev_risks_sig = sig
        except Exception as e:
          logger.warning('보완 루프 explain 실패: %s', e)
          # explain 실패해도 계속 진행하지 않고 정지 (무한 보완 방지)
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'⚠️ [{it}/{max_iters}] AI 리뷰 생성 실패 — 루프 중단. 수동 확인 필요.',
          ))
          break

      # 마무리: status 복원
      update_suggestion(suggestion_id, status='review_pending')
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=(
          f'✅ 건의 #{suggestion_id} 보완 종료 — 총 {success_iters}회 커밋, 최종 판단={final_verdict}. '
          f'"변경사항 보기"에서 확인하세요.'
        ),
      ))

  asyncio.create_task(_run())
  return {'queued': True, 'max_iterations': max_iters, 'message': f'최대 {max_iters}회 반복 보완 대기열 투입'}


async def _compute_branch_explain(suggestion_id: str, branch: str) -> dict:
  '''보완 루프 내부에서 explain 로직 재사용 — 캐시에 저장하고 반환.'''
  from db.suggestion_store import get_suggestion
  from runners.gemini_runner import run_gemini
  from runners.claude_runner import run_claude_isolated
  import json as _j, re as _re
  _, stat = _run_git(['diff', '--stat', f'main...{branch}'])
  _, patch = _run_git(['diff', f'main...{branch}'])
  _, log = _run_git(['log', f'main..{branch}', '--pretty=%s%n%b', '-n', '5'])
  suggestion = get_suggestion(suggestion_id) or {}
  prompt = (
    f'당신은 시니어 엔지니어 리뷰어입니다. 변경사항을 분석해 JSON만 출력하세요.\n\n'
    f'[원 건의]\n제목: {suggestion.get("title", "")}\n내용: {suggestion.get("content", "")[:800]}\n\n'
    f'[커밋 메시지]\n{log[:600]}\n\n[변경 통계]\n{stat}\n\n[패치]\n{patch[:30000]}\n\n'
    f'스키마: {{"intent":"2-3문장","effects":["..."],"risks":["..."],"verdict":"merge_safe|review_needed|risky",'
    f'"verdict_reason":"...","recommendation":"merge|discard|needs_fix","recommendation_reason":"..."}}\n'
    f'규칙: 구체적으로, 위험 최소 1개, verdict는 엄격하게.'
  )
  data = None
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=90.0)
    m = _re.search(r'\{[\s\S]*\}', raw)
    if m: data = _j.loads(m.group())
  except Exception:
    try:
      raw = await run_gemini(prompt=prompt, timeout=120.0)
      m = _re.search(r'\{[\s\S]*\}', raw)
      if m: data = _j.loads(m.group())
    except Exception:
      pass
  if not isinstance(data, dict):
    return {}
  _, tip = _run_git(['rev-parse', branch])
  tip = tip.strip()
  from db.suggestion_store import list_events as _list_ev
  supplement_count = sum(1 for ev in _list_ev(suggestion_id=suggestion_id, limit=50) if ev.get('kind') == 'branch_supplemented')

  result = {
    'intent': (data.get('intent') or '').strip(),
    'effects': [str(x).strip() for x in (data.get('effects') or []) if x],
    'risks': [str(x).strip() for x in (data.get('risks') or []) if x],
    'verdict': data.get('verdict', 'review_needed'),
    'verdict_reason': (data.get('verdict_reason') or '').strip(),
    'recommendation': data.get('recommendation', 'needs_fix'),
    'recommendation_reason': (data.get('recommendation_reason') or '').strip(),
    'supplement_count': supplement_count,
    'commit': tip,
  }
  _BRANCH_EXPLAIN_CACHE[tip] = result
  return result


@app.post('/api/suggestions/{suggestion_id}/branch/discard')
async def discard_suggestion_branch(suggestion_id: str):
  '''improvement/{id} 브랜치를 폐기하고 건의를 rejected로.'''
  from db.suggestion_store import update_suggestion, log_event
  branch = f'improvement/{suggestion_id}'
  _run_git(['branch', '-D', branch])
  update_suggestion(suggestion_id, status='rejected', response='브랜치 폐기')
  log_event(suggestion_id, 'branch_discarded', {})
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=f'🗑️ 건의 #{suggestion_id} 브랜치 폐기 — 변경사항 반영되지 않았습니다.',
  ))
  return {'discarded': True}


# --- 자가개선 API ---

@app.get('/api/improvement/report')
async def get_improvement_report(request: Request):
  '''최신 자가개선 분석 보고서를 반환한다.'''
  office: Office = request.app.state.office
  return office.improvement_engine.get_report()


async def _recover_orphan_patches():
  '''서버 기동 시 호출. 코드 패치 중단으로 남은 git/DB 불일치 정리.'''
  import subprocess as _sp
  import asyncio as _a
  from pathlib import Path as _P
  from db.suggestion_store import list_suggestions, update_suggestion

  await _a.sleep(2)  # 다른 init 끝난 뒤

  root = _P(__file__).parent.parent

  def g(args):
    r = _sp.run(['git'] + args, cwd=str(root), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

  recovered = []

  # 1. 현재 HEAD가 improvement/* 위에 있으면 main으로 강제 복귀
  _, cur = g(['rev-parse', '--abbrev-ref', 'HEAD'])
  cur = cur.strip()
  if cur.startswith('improvement/'):
    logger.warning('기동 시 HEAD가 %s 위에 있음 — main 복귀', cur)
    # 워킹트리 변경 있으면 stash (분실 방지)
    _, status = g(['status', '--porcelain'])
    if status.strip():
      g(['stash', 'push', '-u', '-m', f'auto-recover-from-{cur}'])
      recovered.append(f'워킹트리 변경 stash: {cur}')
    # 브랜치에 커밋이 있어도 무조건 main으로 복귀 (서버는 main에서만 동작)
    rc_co, out_co = g(['checkout', 'main'])
    if rc_co == 0:
      recovered.append(f'HEAD {cur} → main (브랜치 {cur}는 유지 — 사용자 검토용)')
    else:
      # main 체크아웃 실패 시 강제 (워킹트리 더러워도)
      g(['checkout', '-f', 'main'])
      recovered.append(f'HEAD {cur} → main (강제 체크아웃)')

  # 2. accepted 상태로 멈춘 code 건의 → pending 롤백 + 남은 improvement 브랜치 삭제
  try:
    stuck = [
      s for s in list_suggestions(status='accepted')
      if (s.get('suggestion_type') or 'prompt') == 'code'
    ]
    for s in stuck:
      sid = s['id']
      branch = f'improvement/{sid}'
      code, _ = g(['rev-parse', '--verify', branch])
      if code == 0:
        # 브랜치가 main과 차이 없으면 삭제, 아니면 유지 (사용자 판단)
        _, ahead = g(['rev-list', '--count', f'main..{branch}'])
        if ahead.strip() == '0':
          g(['branch', '-D', branch])
          recovered.append(f'빈 브랜치 삭제: {branch}')
      update_suggestion(sid, status='pending', response='기동 시 자동 롤백 (패치 중단)')
      recovered.append(f'건의 #{sid} 상태 accepted → pending')
  except Exception:
    logger.debug('stuck 건의 복구 실패', exc_info=True)

  if recovered:
    msg = '♻️ 기동 시 자동 복구:\n' + '\n'.join(f'- {r}' for r in recovered)
    logger.info(msg)
    try:
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice', message=msg,
      ))
    except Exception:
      pass


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
