# FastAPI 오케스트레이션 서버 진입점 (INFR-04)
# WebSocket /ws/logs: 에이전트 이벤트 실시간 브로드캐스트
import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bus.message_bus import MessageBus
from log_bus.event_bus import EventBus, LogEvent, event_bus
from orchestration.loop import OrchestrationLoop, WorkflowState
from orchestration.router import MessageRouter
from orchestration.task_graph import TaskGraph
from runners.ollama_runner import OllamaRunner
from workspace.manager import WorkspaceManager

# OllamaRunner 싱글턴 (lifespan에서 start/stop)
ollama_runner = OllamaRunner()

# 데이터 디렉토리 생성 (MessageBus SQLite 파일용)
Path('data').mkdir(exist_ok=True)

# 싱글턴 인스턴스
message_bus = MessageBus(db_path='data/bus.db')
# WorkspaceManager: task_id='' → workspace_root 전체를 루트로 사용
workspace = WorkspaceManager(task_id='', workspace_root='workspace')


@asynccontextmanager
async def lifespan(app: FastAPI):
  '''FastAPI 생명주기 관리.

  Startup: OllamaRunner 워커 시작, OrchestrationLoop 초기화
  Shutdown: OllamaRunner 워커 종료, MessageBus 연결 해제
  '''
  await ollama_runner.start()
  router = MessageRouter(bus=message_bus, event_bus=event_bus)
  app.state.orch_loop = OrchestrationLoop(
    bus=message_bus,
    runner=ollama_runner,
    event_bus=event_bus,
    workspace=workspace,
    router=router,
  )
  app.state.active_tasks: dict[str, WorkflowState] = {}
  app.state.task_order: list[str] = []          # 작업 지시 순서 추적
  app.state.log_history: list[dict] = []         # 최근 로그 버퍼 (최대 500건)
  yield
  await ollama_runner.stop()
  message_bus.close()


app = FastAPI(title='AI Office', lifespan=lifespan)

# CORS 설정 — Vite 개발 서버(localhost:5173) 허용
app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
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


@app.post('/api/tasks', response_model=TaskResponse, status_code=202)
async def create_task(body: TaskRequest, request: Request):
  '''사용자 지시를 받아 오케스트레이션을 백그라운드로 시작한다 (ORCH-01)'''
  task_id = str(uuid.uuid4())
  loop: OrchestrationLoop = request.app.state.orch_loop
  request.app.state.active_tasks[task_id] = WorkflowState.IDLE
  request.app.state.task_order.append(task_id)  # 순서 기록

  async def _run():
    final_state = await loop.run(body.instruction)
    request.app.state.active_tasks[task_id] = final_state

  asyncio.create_task(_run())
  return TaskResponse(task_id=task_id, status='accepted')


@app.get('/api/tasks/{task_id}')
async def get_task_status(task_id: str, request: Request):
  '''태스크 현재 상태를 반환한다'''
  tasks = request.app.state.active_tasks
  if task_id not in tasks:
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  return {'task_id': task_id, 'state': tasks[task_id]}


@app.get('/api/tasks')
async def list_tasks(request: Request):
  '''전체 작업 지시 내역을 순서대로 반환한다 (DASH-05)'''
  tasks = request.app.state.active_tasks
  order = request.app.state.task_order
  return [
    {'task_id': tid, 'state': tasks.get(tid, WorkflowState.IDLE)}
    for tid in order
  ]


@app.get('/api/dag')
async def get_dag(request: Request):
  '''TaskGraph를 React Flow 형식(nodes, edges)으로 반환한다 (WKFL-05).

  노드 위치는 depends_on 기반 depth 계산으로 결정한다.
  '''
  loop: OrchestrationLoop = request.app.state.orch_loop
  # TaskGraph는 loop 내부 속성으로 접근
  graph: TaskGraph = getattr(loop, 'task_graph', None) or getattr(loop, '_task_graph', None)

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
  '''에이전트별 현재 상태를 반환한다 (DASH-02).

  알려진 에이전트 목록 기준으로 상태를 추론한다.
  '''
  tasks = request.app.state.active_tasks
  # 알려진 에이전트 목록
  known_agents = ['claude', 'planner', 'designer', 'developer', 'qa']

  # active_tasks에서 현재 진행 중인 태스크를 통해 에이전트 상태 추론
  # WorkflowState.IDLE이 아닌 태스크가 있으면 일부 에이전트가 작업 중
  has_active = any(
    v != WorkflowState.IDLE for v in tasks.values()
  )

  agents = []
  for agent_id in known_agents:
    agents.append({
      'agent_id': agent_id,
      'status': 'working' if has_active else 'idle',
    })
  return agents


@app.get('/api/files/{task_id}')
async def list_files(task_id: str):
  '''task_id의 산출물 파일 목록을 반환한다 (DASH-04).

  경로 순회 공격 방지: task_id에 '..' 또는 '/' 포함 시 400 반환.
  '''
  # 경로 순회 방지
  if '..' in task_id or '/' in task_id or '\\' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  workspace_root = Path('workspace')
  task_dir = workspace_root / task_id

  if not task_dir.exists():
    return []

  wm = WorkspaceManager(task_id=task_id, workspace_root='workspace')
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

  wm = WorkspaceManager(task_id=task_id, workspace_root='workspace')
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
  limit = min(limit, 500)
  history = request.app.state.log_history
  return history[-limit:]


@app.websocket('/ws/logs')
async def log_stream(ws: WebSocket):
  '''실시간 에이전트 로그 스트림 (INFR-04).

  연결 시: event_bus 구독
  이벤트 수신 시: JSON으로 클라이언트에 전송하고 log_history에도 저장
  연결 종료 시: finally에서 반드시 구독 해제 (Pitfall 4 방지)

  메시지 형식:
  {
    "id": "uuid",
    "agent_id": "planner",
    "event_type": "task_start",
    "message": "태스크 시작",
    "data": {},
    "timestamp": "2026-04-03T..."
  }
  '''
  await ws.accept()
  q = event_bus.subscribe()
  try:
    while True:
      event: LogEvent = await q.get()
      event_dict = asdict(event)
      await ws.send_json(event_dict)
      # log_history에 추가 (최대 500건 순환 버퍼)
      app.state.log_history.append(event_dict)
      if len(app.state.log_history) > 500:
        app.state.log_history = app.state.log_history[-500:]
  except WebSocketDisconnect:
    pass
  finally:
    event_bus.unsubscribe(q)  # 반드시 구독 해제 (메모리 누수 방지)
