# WKFL-04: 기획자 PM 추적 테스트
import pytest
from bus.message_bus import MessageBus
from bus.schemas import AgentMessage
from log_bus.event_bus import EventBus
from orchestration.router import MessageRouter


@pytest.fixture
def setup(tmp_path):
  '''테스트용 버스 및 라우터 픽스처'''
  bus = MessageBus(db_path=str(tmp_path / 'test.db'))
  ev_bus = EventBus()
  router = MessageRouter(bus=bus, event_bus=ev_bus)
  return bus, router


@pytest.mark.asyncio
async def test_planner_receives_broadcast_copy(setup):
  '''모든 에이전트 간 메시지의 broadcast 복사가 기획자에게 전달된다 (WKFL-04)'''
  bus, router = setup

  # developer → designer 메시지 라우팅
  msg = AgentMessage(
    type='task_request',
    **{'from': 'developer', 'to': 'designer'},
    payload={'description': '디자인 요청'},
  )
  await router.route(msg)

  # 기획자가 복사 메시지를 받아야 함
  planner_msgs = bus.consume(to_agent='planner')
  assert len(planner_msgs) == 1
  assert planner_msgs[0].metadata.get('is_broadcast_copy') is True


@pytest.mark.asyncio
async def test_planner_not_duplicated_when_already_planner(setup):
  '''msg.to=planner 이면 복사 발행하지 않는다 (WKFL-04)'''
  bus, router = setup

  # developer → planner 직접 메시지
  msg = AgentMessage(
    type='task_result',
    **{'from': 'developer', 'to': 'planner'},
    payload={'result': '완료'},
  )
  await router.route(msg)

  # planner에게 메시지가 1개만 있어야 함 (중복 없음)
  planner_msgs = bus.consume(to_agent='planner')
  assert len(planner_msgs) == 1
  # broadcast_copy 메타데이터가 없어야 함
  assert not planner_msgs[0].metadata.get('is_broadcast_copy')
