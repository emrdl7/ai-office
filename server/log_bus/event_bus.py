# asyncio.Queue 기반 인-프로세스 이벤트 버스 (INFR-04)
# 결정 근거: SQLite 기반 로그 버스 대신 in-process asyncio.Queue 선택
# 이유: 폴링 레이어 없이 즉시 WebSocket 팬아웃 가능, FastAPI와 동일 프로세스
import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class LogEvent:
    '''에이전트 이벤트 레코드.

    event_type 값:
      'log'           — 일반 로그 메시지
      'status_change' — 에이전트 상태 변경 (작업중/대기/완료/에러)
      'task_start'    — 태스크 시작
      'task_done'     — 태스크 완료
      'error'         — 에러 발생
    '''
    agent_id: str
    event_type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    '''인-프로세스 pub/sub 이벤트 버스.

    구독자는 asyncio.Queue를 받아 이벤트를 소비한다.
    WebSocket 핸들러는 subscribe() → 이벤트 대기 → unsubscribe() 패턴으로 사용한다.

    주의사항 (Pitfall 4):
      WebSocket 연결 종료 시 반드시 finally 블록에서 unsubscribe() 호출.
      미호출 시 닫힌 큐에 계속 put_nowait 시도로 메모리 누수 발생.
    '''

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        '''새 구독자 큐 등록. WebSocket 연결 시 호출.

        Returns:
            maxsize=500의 asyncio.Queue (이벤트를 소비할 큐)
        '''
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        '''구독자 큐 제거. WebSocket 연결 종료 시 finally에서 호출.

        큐가 목록에 없어도 에러 없이 무시한다.
        '''
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass  # 이미 제거된 경우 무시

    async def publish(self, event: LogEvent) -> None:
        '''이벤트를 모든 구독자에게 브로드캐스트 + SQLite에 영구 저장.

        느린 구독자의 큐가 꽉 찬 경우 해당 구독자만 드롭하고 버스는 계속 동작.
        typing 이벤트는 저장하지 않음 (일시적 표시용).
        '''
        # SQLite에 즉시 저장 (WebSocket 연결 여부와 무관)
        if event.event_type != 'typing':
            try:
                from db.log_store import save_log
                save_log(asdict(event))
            except Exception:
                logger.debug("이벤트 SQLite 저장 실패", exc_info=True)

        for q in list(self._subscribers):  # 복사본으로 순회 (동시 수정 안전)
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 느린 클라이언트 드롭, 버스는 블록되지 않음

    @property
    def subscriber_count(self) -> int:
        '''현재 구독자 수 (모니터링용)'''
        return len(self._subscribers)


# FastAPI 앱에서 사용할 싱글턴 인스턴스
# from log_bus.event_bus import event_bus
event_bus = EventBus()
