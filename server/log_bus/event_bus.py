# asyncio.Queue 기반 인-프로세스 이벤트 버스 (INFR-04)
# 실제 구현: 01-06-PLAN
import asyncio
from dataclasses import dataclass, field
from typing import Any

@dataclass
class LogEvent:
    agent_id: str
    event_type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

class EventBus:
    def subscribe(self) -> asyncio.Queue:
        raise NotImplementedError('01-06-PLAN에서 구현 예정')

    def unsubscribe(self, q: asyncio.Queue):
        raise NotImplementedError

    async def publish(self, event: LogEvent):
        raise NotImplementedError
