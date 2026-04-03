# SQLite WAL 기반 메시지 버스 (INFR-01)
# 실제 구현: 01-02-PLAN
from .schemas import AgentMessage

class MessageBus:
    def __init__(self, db_path: str = 'data/bus.db'):
        raise NotImplementedError('01-02-PLAN에서 구현 예정')

    def publish(self, message: AgentMessage) -> None:
        raise NotImplementedError

    def consume(self, to_agent: str, limit: int = 10) -> list[AgentMessage]:
        raise NotImplementedError

    def ack(self, message_id: str) -> None:
        raise NotImplementedError
