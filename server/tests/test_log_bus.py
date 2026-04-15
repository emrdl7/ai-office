# INFR-04: asyncio.Queue 이벤트 버스 테스트
import asyncio
import pytest
from log_bus.event_bus import EventBus, LogEvent


@pytest.fixture
def bus():
    return EventBus()


def _make_event(**kwargs) -> LogEvent:
    defaults = {
        'agent_id': 'planner',
        'event_type': 'log',
        'message': '테스트 이벤트',
    }
    defaults.update(kwargs)
    return LogEvent(**defaults)


async def test_publish_reaches_subscriber(bus):
    '''발행된 이벤트가 구독자 큐에 도달함 (INFR-04)'''
    q = bus.subscribe()
    event = _make_event(message='태스크 시작')

    await bus.publish(event)

    received = q.get_nowait()
    assert received.message == '태스크 시작'
    assert received.agent_id == 'planner'


async def test_unsubscribe_stops_delivery(bus):
    '''unsubscribe 후 이벤트가 전달되지 않음 (Pitfall 4 방지)'''
    q = bus.subscribe()
    bus.unsubscribe(q)

    await bus.publish(_make_event())

    assert q.empty()


async def test_multiple_subscribers_all_receive(bus):
    '''다수 구독자가 모두 이벤트를 수신함'''
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    q3 = bus.subscribe()

    await bus.publish(_make_event(message='브로드캐스트'))

    assert not q1.empty()
    assert not q2.empty()
    assert not q3.empty()
    assert q1.get_nowait().message == '브로드캐스트'


async def test_full_queue_does_not_block_bus(bus):
    '''꽉 찬 구독자 큐가 버스를 블록하지 않음 (QueueFull 처리)'''
    # maxsize=1로 작은 큐 생성 후 꽉 채움
    q_full = asyncio.Queue(maxsize=1)
    q_full.put_nowait(_make_event())  # 큐 꽉 참
    bus._subscribers.append(q_full)

    q_normal = bus.subscribe()

    # publish가 블록되지 않아야 함
    await asyncio.wait_for(bus.publish(_make_event(message='정상 수신')), timeout=1.0)

    # 정상 구독자는 이벤트 수신
    assert not q_normal.empty()
    assert q_normal.get_nowait().message == '정상 수신'


async def test_log_event_has_required_fields(bus):
    '''LogEvent가 필수 필드(id, timestamp)를 자동 생성'''
    event = _make_event()
    assert event.id  # uuid 자동 생성
    assert event.timestamp  # datetime 자동 생성
    assert event.data == {}  # 기본값

    d = event.to_dict()
    assert 'id' in d
    assert 'timestamp' in d
    assert 'agent_id' in d
    assert 'event_type' in d
    assert 'message' in d


async def test_subscriber_count(bus):
    '''subscriber_count가 정확한 수를 반환'''
    assert bus.subscriber_count == 0
    q1 = bus.subscribe()
    bus.subscribe()
    assert bus.subscriber_count == 2
    bus.unsubscribe(q1)
    assert bus.subscriber_count == 1
