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

  # 에이전트 자발적 활동 백그라운드 루프 시작
  office._autonomous_task = asyncio.create_task(office.start_autonomous_loop())
  yield
  office.stop_autonomous_loop()
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

  # 에이전트별 모델명 — 상태에 따라 동적 표시
  # idle(잡담/자발적 대화): Gemini (토큰 비용 절감용)
  # working(실제 업무): 역할별 실제 사용 모델
  is_working = state in {
    OfficeState.TEAMLEAD_THINKING, OfficeState.MEETING,
    OfficeState.WORKING, OfficeState.QA_REVIEW,
    OfficeState.TEAMLEAD_REVIEW, OfficeState.REVISION,
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

    # idle/대기 시에는 자발적 대화 루프가 Gemini 사용
    if not is_working:
      model = 'Gemini'
    elif agent_id == 'teamlead':
      model = 'Claude Haiku'
    elif agent_id == 'qa':
      model = 'Claude Haiku'
    elif agent_id == 'planner':
      model = 'Gemini'  # planner 업무도 Gemini 1차
    elif agent_id == 'developer':
      model = 'Gemini'  # developer 업무도 Gemini 1차
    elif agent_id == 'designer':
      model = 'Claude Sonnet'
    else:
      model = 'Claude Sonnet'

    agents.append({
      'agent_id': agent_id,
      'status': status,
      'model': model,
      'work_started_at': office._work_started_at if status in ('working', 'meeting') else '',
      'current_phase': office._current_phase if status == 'working' and active == agent_id else '',
      'active_project_title': office._active_project_title if status in ('working', 'meeting', 'waiting') else '',
    })
  return agents


@app.get('/api/agents/quotes')
async def get_daily_quotes():
  '''오늘의 한마디 반환. 없으면 Haiku로 생성 후 캐싱.'''
  from db.daily_quote_store import get_quotes, save_quotes, AGENT_PERSONAS
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError

  cached = get_quotes()
  if len(cached) >= 5:
    return cached

  # 생성 프롬프트
  persona_block = '\n'.join(
    f'- {agent_id}: {persona}'
    for agent_id, persona in AGENT_PERSONAS.items()
  )
  prompt = (
    '아래 5명의 직장인 캐릭터가 오늘 아침 출근하며 한마디씩 합니다.\n'
    '각 캐릭터의 성격을 살려, 짧고 인상적인 한마디를 만들어 주세요.\n'
    '일상적인 감상, 일에 대한 생각, 오늘 날씨, 인생 통찰 등 자유롭게.\n'
    '20자 이내, 구어체, 말줄임표 사용 가능, 직접 인용처럼.\n\n'
    f'{persona_block}\n\n'
    '아래 JSON 형식으로만 답하세요 (설명 없이):\n'
    '{"teamlead":"...", "planner":"...", "designer":"...", "developer":"...", "qa":"..."}'
  )

  try:
    result = await run_claude_isolated(
      prompt,
      model='claude-haiku-4-5-20251001',
      timeout=30.0,
      max_turns=1,
    )
    from runners.json_parser import parse_json
    parsed = parse_json(result)
    if parsed and isinstance(parsed, dict) and len(parsed) >= 5:
      quotes = {k: str(v) for k, v in parsed.items() if k in AGENT_PERSONAS}
      save_quotes(quotes)
      return quotes
  except (ClaudeRunnerError, Exception):
    pass

  # 폴백 — config/team.py에서 중앙 관리
  from config.team import TEAM
  fallback = {m.agent_id: m.fallback_quote for m in TEAM}
  save_quotes(fallback)
  return fallback


@app.get('/api/team')
async def get_team():
  '''팀 구성 조회 — 프론트엔드에서 이름/역할/페르소나 등을 동기화한다.'''
  from config.team import to_api_dict
  return to_api_dict()


@app.get('/api/team-memory')
async def get_team_memory():
  '''팀 공유 메모리 조회 — 교훈, 협업 패턴, 프로젝트 이력'''
  from memory.team_memory import TeamMemory
  tm = TeamMemory()
  return {
    'lessons': [
      {'id': l.id, 'project': l.project_title, 'agent': l.agent_name,
       'lesson': l.lesson, 'category': l.category, 'timestamp': l.timestamp}
      for l in tm.get_all_lessons(limit=15)
    ],
    'projects': [
      {'id': p.project_id, 'title': p.title, 'type': p.project_type,
       'outcome': p.outcome, 'decisions': p.key_decisions, 'timestamp': p.timestamp}
      for p in tm.get_recent_projects(limit=10)
    ],
  }


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


@app.get('/api/reactions/stats')
async def get_reaction_stats_api(days: int = 30):
  '''에이전트별 리액션 통계 (최근 N일).'''
  from db.log_store import get_reaction_stats
  return get_reaction_stats(limit_days=days)


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

@app.get('/api/suggestions')
async def list_suggestions_api(status: str = ''):
  '''건의 목록을 반환한다.'''
  from db.suggestion_store import list_suggestions
  return list_suggestions(status)


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

  # 승인 — 저장된 suggestion_type 보고 자동 분기
  if new_status == 'accepted' and suggestion:
    stype = suggestion.get('suggestion_type') or 'prompt'
    if stype == 'code':
      async def _run_patch():
        from improvement.code_patcher import apply_suggestion
        from db.suggestion_store import update_suggestion as _upd
        ok = await apply_suggestion(suggestion)
        if ok:
          _upd(suggestion_id, status='done')
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
      AgentMemory(suggestion['agent_id']).record(MemoryRecord(
        task_id=f'suggestion-{suggestion_id}',
        task_type='suggestion_rejected',
        success=False,
        feedback=f'건의 반려됨 — 유사 건의 반복 금지: "{suggestion["title"]}"',
        tags=['suggestion_rejected', suggestion.get('category', 'general')],
        timestamp=_dt.now(_tz.utc).isoformat(),
      ))
    except Exception:
      logger.debug('반려 메모리 기록 실패', exc_info=True)

  return {'success': True}


async def _apply_suggestion_to_prompts(suggestion: dict) -> None:
  '''프롬프트 수준 반영 — team_memory(전체 공유) + prompt_evolver(제안자 개인 규칙).'''
  from memory.team_memory import TeamMemory, SharedLesson
  from improvement.prompt_evolver import PromptEvolver, PromptRule
  from datetime import datetime, timezone

  sid = suggestion['id']
  agent_id = suggestion['agent_id']
  title = suggestion['title']
  content = suggestion['content']
  category = suggestion.get('category', 'general')
  now_iso = datetime.now(timezone.utc).isoformat()

  # 1. 팀 공유 메모리에 교훈으로 등록 → 모든 에이전트 시스템 프롬프트에 자동 주입
  try:
    TeamMemory().add_lesson(SharedLesson(
      id=f'suggestion-{sid}',
      project_title='건의 수용',
      agent_name=agent_id,
      lesson=f'{title} — {content[:200]}',
      category='process_improvement',
      timestamp=now_iso,
    ))
  except Exception:
    logger.debug('TeamMemory add_lesson 실패', exc_info=True)

  # 2. 제안자 에이전트의 PromptEvolver에 규칙 추가 → 본인 시스템 프롬프트에 주입
  try:
    evolver = PromptEvolver()
    existing = evolver.load_rules(agent_id)
    existing.append(PromptRule(
      id=f'suggestion-{sid}',
      created_at=now_iso,
      source='manual',
      category=category,
      rule=f'{title}: {content[:300]}',
      evidence=f'사용자 승인된 건의 #{sid}',
      priority='high',
      active=True,
    ))
    if len(existing) > 10:
      existing = existing[-10:]
    evolver.save_rules(agent_id, existing)
  except Exception:
    logger.debug('PromptEvolver save_rules 실패', exc_info=True)

  # 3. 채팅에 공지
  from config.team import display_name
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=(
      f'✅ {display_name(agent_id)}의 건의 "{title[:40]}" 수용 → '
      f'팀 메모리 + 에이전트 프롬프트에 즉시 반영했습니다.'
    ),
  ))


@app.delete('/api/suggestions/{suggestion_id}')
async def delete_suggestion_api(suggestion_id: str):
  '''건의를 삭제한다.'''
  from db.suggestion_store import delete_suggestion
  if not delete_suggestion(suggestion_id):
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')
  return {'deleted': suggestion_id}


# --- 자가개선 API ---

@app.get('/api/improvement/report')
async def get_improvement_report(request: Request):
  '''최신 자가개선 분석 보고서를 반환한다.'''
  office: Office = request.app.state.office
  return office.improvement_engine.get_report()


@app.get('/api/improvement/metrics')
async def get_improvement_metrics(request: Request):
  '''프로젝트별 성과 메트릭을 반환한다.'''
  office: Office = request.app.state.office
  return office.improvement_engine.get_metrics_summary()


@app.get('/api/improvement/rules/{agent}')
async def get_agent_rules(agent: str, request: Request):
  '''에이전트별 학습된 품질 규칙 목록을 반환한다.'''
  office: Office = request.app.state.office
  rules = office.improvement_engine.prompt_evolver.load_rules(agent)
  from dataclasses import asdict
  return [asdict(r) for r in rules]


@app.post('/api/improvement/rules/{agent}/toggle')
async def toggle_agent_rule(agent: str, request: Request):
  '''규칙 활성화/비활성화 토글.'''
  body = await request.json()
  rule_id = body.get('rule_id', '')
  active = body.get('active', True)
  office: Office = request.app.state.office
  success = office.improvement_engine.prompt_evolver.toggle_rule(agent, rule_id, active)
  if not success:
    raise HTTPException(status_code=404, detail='규칙을 찾을 수 없습니다')
  return {'success': True, 'rule_id': rule_id, 'active': active}


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
