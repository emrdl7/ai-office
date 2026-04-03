# 메시지 라우터 — 라우팅 + 기획자 broadcast 복사 (WKFL-03, WKFL-04)
# 모든 에이전트 간 메시지에 대해 기획자에게 자동 broadcast 복사를 발행한다.
import uuid

from bus.message_bus import MessageBus
from bus.schemas import AgentMessage
from log_bus.event_bus import EventBus, LogEvent


class MessageRouter:
  '''메시지 라우터.

  에이전트 간 메시지를 MessageBus에 발행하고,
  기획자가 PM으로서 전체 흐름을 추적할 수 있도록 자동 broadcast 복사를 발행한다 (WKFL-04).

  사용 예시:
      router = MessageRouter(bus=message_bus, event_bus=event_bus)
      await router.route(msg)
  '''

  def __init__(self, bus: MessageBus, event_bus: EventBus):
    self.bus = bus
    self.event_bus = event_bus

  async def route(self, msg: AgentMessage) -> None:
    '''메시지를 라우팅한다.

    1. 원본 메시지를 bus에 발행한다.
    2. to_agent가 'planner' 또는 'broadcast'가 아닌 경우,
       기획자에게 broadcast 복사를 자동 발행한다 (WKFL-04).
    3. 이벤트 버스에 라우팅 이벤트를 발행한다.

    Args:
        msg: 라우팅할 AgentMessage
    '''
    # 1. 원본 메시지 발행
    self.bus.publish(msg)

    # 2. 기획자 broadcast 복사 (planner/broadcast로 보내는 메시지는 중복 복사 생략)
    if msg.to_agent not in ('planner', 'broadcast'):
      copy = msg.model_copy(update={
        'id': str(uuid.uuid4()),
        'to_agent': 'planner',
        'metadata': {**msg.metadata, 'is_broadcast_copy': True},
      })
      self.bus.publish(copy)

    # 3. 이벤트 버스에 라우팅 로그 발행
    await self.event_bus.publish(LogEvent(
      agent_id=msg.from_agent,
      event_type='log',
      message=f'{msg.from_agent} → {msg.to_agent}: {msg.type}',
    ))
