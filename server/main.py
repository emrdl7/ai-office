# FastAPI 오케스트레이션 서버 진입점 (INFR-04)
# WebSocket /ws/logs: 에이전트 이벤트 실시간 브로드캐스트
# 대시보드 API: DAG, 파일, 에이전트, 로그 히스토리, 태스크 목록 (DASH-04, DASH-05, WKFL-05)
import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from bus.message_bus import MessageBus
from log_bus.event_bus import LogEvent, event_bus
from orchestration.loop import OrchestrationLoop, WorkflowState
from orchestration.router import MessageRouter
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

# 알려진 에이전트 목록
KNOWN_AGENTS = ['claude', 'planner', 'designer', 'developer', 'qa']

# 로그 히스토리 최대 보관 건수
LOG_HISTORY_MAX = 500


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
  # 작업 지시 순서 추적 리스트 (DASH-05)
  app.state.task_order: list[str] = []
  # 최근 로그 버퍼 (새로고침 후 복구용, DASH-03)
  app.state.log_history: list[dict] = []
  yield
  await ollama_runner.stop()
  message_bus.close()


app = FastAPI(title='AI Office', lifespan=lifespan)

# CORS 미들웨어 — Vite dev 서버(localhost:5173) 허용 (대시보드 연동)
app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:5173'],
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
  # 작업 지시 순서 기록 (DASH-05)
  request.app.state.task_order.append(task_id)

  async def _run():
    final_state = await loop.run(body.instruction)
    request.app.state.active_tasks[task_id] = final_state

  asyncio.create_task(_run())
  return TaskResponse(task_id=task_id, status='accepted')


@app.get('/api/tasks')
async def list_tasks(request: Request):
  '''작업 지시 내역 목록을 순서대로 반환한다 (DASH-05).

  task_order 리스트 기준으로 정렬된 태스크 목록을 반환한다.
  '''
  tasks = request.app.state.active_tasks
  order = request.app.state.task_order
  return [
    {'task_id': tid, 'state': tasks[tid].value if hasattr(tasks[tid], 'value') else str(tasks[tid])}
    for tid in order
    if tid in tasks
  ]


@app.get('/api/tasks/{task_id}')
async def get_task_status(task_id: str, request: Request):
  '''태스크 현재 상태를 반환한다'''
  tasks = request.app.state.active_tasks
  if task_id not in tasks:
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  state = tasks[task_id]
  return {'task_id': task_id, 'state': state.value if hasattr(state, 'value') else str(state)}


@app.get('/api/agents')
async def list_agents():
  '''알려진 에이전트 목록과 기본 상태를 반환한다 (DASH-02).

  실시간 상태 업데이트는 WebSocket /ws/logs의 status_change 이벤트로 처리된다.
  이 엔드포인트는 초기 에이전트 목록 렌더링에 사용된다.
  '''
  return [
    {'agent_id': agent_id, 'status': 'idle'}
    for agent_id in KNOWN_AGENTS
  ]


@app.get('/api/logs/history')
async def get_log_history(
  request: Request,
  limit: Annotated[int, Query(ge=1, le=LOG_HISTORY_MAX)] = 100,
):
  '''최근 로그 히스토리를 반환한다 (DASH-03 새로고침 복구용).

  WebSocket 연결 전에 이 엔드포인트로 이전 로그를 미리 로드한다.
  '''
  history = request.app.state.log_history
  # 최신 limit건만 반환
  return history[-limit:]


@app.get('/api/workspace/{task_id}/files')
async def list_workspace_files(task_id: str):
  '''태스크 workspace 파일 트리를 반환한다 (DASH-04).

  워크스페이스 디렉토리 내 모든 파일을 재귀적으로 열거한다.
  '''
  # 경로 순회 방지: task_id에 '..' 또는 '/' 포함 시 거부
  if '..' in task_id or '/' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  task_ws = WorkspaceManager(task_id=task_id, workspace_root='workspace')
  artifacts = task_ws.list_artifacts()

  result = []
  for path in artifacts:
    relative = path.relative_to(task_ws.task_dir)
    result.append({
      'path': str(relative),
      'type': task_ws.artifact_type(str(relative)),
      'size': path.stat().st_size,
    })
  return result


@app.get('/api/workspace/{task_id}/files/{file_path:path}')
async def get_workspace_file(task_id: str, file_path: str):
  '''태스크 workspace 파일 내용을 반환한다 (DASH-04).

  파일 내용을 text/plain으로 반환한다.
  경로 순회 공격은 WorkspaceManager.safe_path()에서 차단된다.
  '''
  # 경로 순회 방지: task_id에 '..' 또는 '/' 포함 시 거부
  if '..' in task_id or '/' in task_id:
    raise HTTPException(status_code=400, detail='유효하지 않은 task_id입니다')

  task_ws = WorkspaceManager(task_id=task_id, workspace_root='workspace')
  try:
    target = task_ws.safe_path(file_path)
  except ValueError:
    raise HTTPException(status_code=400, detail='경로 순회가 감지되었습니다')

  if not target.exists() or not target.is_file():
    raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')

  content = target.read_text(encoding='utf-8', errors='replace')
  return PlainTextResponse(content=content)


@app.get('/api/dag')
async def get_dag(request: Request):
  '''TaskGraph를 React Flow 형식의 노드/엣지로 반환한다 (WKFL-05).

  TaskGraph.to_state_dict()를 React Flow nodes/edges 형식으로 변환한다.
  위치는 의존성 깊이(topological depth) 기반으로 계산된다.
  '''
  loop: OrchestrationLoop = request.app.state.orch_loop
  # _task_graph는 오케스트레이션 시작 시 초기화됨 (실행 전이면 None)
  if loop._task_graph is None:
    return {'nodes': [], 'edges': []}
  state_dict = loop._task_graph.to_state_dict()

  # 빈 그래프
  if not state_dict:
    return {'nodes': [], 'edges': []}

  # topological depth 계산 — 위치 배치에 사용
  def calc_depth(task_id: str, visited: set) -> int:
    if task_id in visited:
      return 0
    visited.add(task_id)
    task = state_dict.get(task_id)
    if not task or not task['depends_on']:
      return 0
    return 1 + max(calc_depth(dep, visited) for dep in task['depends_on'])

  # 깊이별 노드 그룹화 (x축: 깊이, y축: 같은 깊이 내 순서)
  depth_map: dict[str, int] = {}
  for task_id in state_dict:
    depth_map[task_id] = calc_depth(task_id, set())

  # 깊이별 카운터 (y 위치 계산용)
  depth_counter: dict[int, int] = {}

  nodes = []
  for task_id, task in state_dict.items():
    depth = depth_map[task_id]
    idx = depth_counter.get(depth, 0)
    depth_counter[depth] = idx + 1

    nodes.append({
      'id': task_id,
      'data': {
        'label': task['description'][:40] + '...' if len(task['description']) > 40 else task['description'],
        'status': task['status'],
        'assigned_to': task['assigned_to'],
        'artifact_paths': task['artifact_paths'],
      },
      'position': {'x': depth * 250, 'y': idx * 100},
    })

  # 엣지: 의존성 관계
  edges = []
  for task_id, task in state_dict.items():
    for dep_id in task['depends_on']:
      edges.append({
        'id': f'{dep_id}->{task_id}',
        'source': dep_id,
        'target': task_id,
      })

  return {'nodes': nodes, 'edges': edges}


@app.websocket('/ws/logs')
async def log_stream(ws: WebSocket):
  '''실시간 에이전트 로그 스트림 (INFR-04).

  연결 시: event_bus 구독
  이벤트 수신 시: JSON으로 클라이언트에 전송 + log_history에 저장
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
      # 로그 히스토리에 추가 (최대 LOG_HISTORY_MAX건 순환 버퍼)
      # app 싱글턴의 state를 직접 참조 (WebSocket scope에서 안전)
      app.state.log_history.append(event_dict)
      if len(app.state.log_history) > LOG_HISTORY_MAX:
        del app.state.log_history[0]  # 오래된 항목 제거
  except WebSocketDisconnect:
    pass
  finally:
    event_bus.unsubscribe(q)  # 반드시 구독 해제 (메모리 누수 방지)
