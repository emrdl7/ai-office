# FastAPI 오케스트레이션 서버 진입점 (INFR-04)
# WebSocket /ws/logs: 에이전트 이벤트 실시간 브로드캐스트
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from log_bus.event_bus import EventBus, LogEvent, event_bus
from runners.ollama_runner import OllamaRunner

# OllamaRunner 싱글턴 (lifespan에서 start/stop)
ollama_runner = OllamaRunner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    '''FastAPI 생명주기 관리.

    Startup: OllamaRunner 워커 시작
    Shutdown: OllamaRunner 워커 종료
    '''
    await ollama_runner.start()
    yield
    await ollama_runner.stop()


app = FastAPI(title='AI Office', lifespan=lifespan)


@app.get('/health')
async def health():
    '''서버 상태 확인'''
    return {
        'status': 'ok',
        'log_bus_subscribers': event_bus.subscriber_count,
    }


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
