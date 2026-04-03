# FastAPI 오케스트레이션 서버 진입점 (INFR-04)
# WebSocket /ws/logs: 에이전트 이벤트 실시간 브로드캐스트
import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from bus.message_bus import MessageBus
from log_bus.event_bus import EventBus, LogEvent, event_bus
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
  yield
  await ollama_runner.stop()
  message_bus.close()


app = FastAPI(title='AI Office', lifespan=lifespan)


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
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail='태스크를 찾을 수 없습니다')
  return {'task_id': task_id, 'state': tasks[task_id]}


@app.websocket('/ws/logs')
async def log_stream(ws: WebSocket):
  '''실시간 에이전트 로그 스트림 (INFR-04).

  연결 시: event_bus 구독
  이벤트 수신 시: JSON으로 클라이언트에 전송
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
      await ws.send_json(asdict(event))
  except WebSocketDisconnect:
    pass
  finally:
    event_bus.unsubscribe(q)  # 반드시 구독 해제 (메모리 누수 방지)
