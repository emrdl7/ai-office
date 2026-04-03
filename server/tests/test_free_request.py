# WKFL-03: 에이전트 간 자유 작업 요청 테스트
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
async def test_developer_can_request_designer(setup):
  '''개발자가 디자이너에게 작업 요청을 보낼 수 있다 (WKFL-03, D-06)'''
  bus, router = setup

  msg = AgentMessage(
    type='task_request',
    **{'from': 'developer', 'to': 'designer'},
    payload={'description': '아이콘 디자인 요청'},
  )
  await router.route(msg)

  # designer에게 메시지가 저장돼야 함
  designer_msgs = bus.consume(to_agent='designer')
  assert len(designer_msgs) == 1
  assert designer_msgs[0].from_agent == 'developer'


@pytest.mark.asyncio
async def test_free_request_goes_through_message_bus(setup):
  '''자유 요청은 메시지 버스를 경유한다 (WKFL-03, D-06)'''
  bus, router = setup

  msg = AgentMessage(
    type='task_request',
    **{'from': 'developer', 'to': 'designer'},
    payload={'description': '레이아웃 요청'},
  )
  await router.route(msg)

  # bus.consume으로 메시지를 확인할 수 있어야 함
  msgs = bus.consume(to_agent='designer')
  assert len(msgs) == 1
  assert msgs[0].to_agent == 'designer'
