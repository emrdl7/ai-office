# INFR-01: SQLite WAL 메시지 버스 테스트
import pytest
from bus.message_bus import MessageBus
from bus.schemas import AgentMessage


@pytest.fixture
def bus(tmp_path):
    '''임시 DB 경로를 사용하는 MessageBus'''
    db_path = tmp_path / 'test_bus.db'
    b = MessageBus(db_path=str(db_path))
    yield b
    b.close()


def _make_message(**kwargs) -> AgentMessage:
    defaults = {
        'type': 'task_request',
        'from': 'claude',
        'to': 'planner',
        'payload': {'task': 'test'},
    }
    defaults.update(kwargs)
    return AgentMessage.model_validate(defaults)


def test_publish_and_consume(bus):
    '''메시지 발행 후 소비 왕복 테스트 (INFR-01)'''
    msg = _make_message(payload={'task': 'design homepage'})
    bus.publish(msg)

    consumed = bus.consume(to_agent='planner')

    assert len(consumed) == 1
    assert consumed[0].id == msg.id
    assert consumed[0].payload == {'task': 'design homepage'}


def test_ack_removes_from_pending(bus):
    '''ACK 후 메시지가 pending 소비에서 제거됨 (INFR-01)'''
    msg = _make_message()
    bus.publish(msg)

    before_ack = bus.consume(to_agent='planner')
    assert len(before_ack) == 1

    bus.ack(msg.id)

    after_ack = bus.consume(to_agent='planner')
    assert len(after_ack) == 0


def test_consume_filters_by_recipient(bus):
    '''다른 에이전트의 메시지는 소비되지 않음'''
    msg_planner = _make_message(**{'to': 'planner'})
    msg_developer = _make_message(**{'to': 'developer'})
    bus.publish(msg_planner)
    bus.publish(msg_developer)

    planner_msgs = bus.consume(to_agent='planner')
    developer_msgs = bus.consume(to_agent='developer')

    assert len(planner_msgs) == 1
    assert len(developer_msgs) == 1
    assert planner_msgs[0].id == msg_planner.id


def test_consume_respects_limit(bus):
    '''limit 파라미터로 반환 수 제한'''
    for i in range(5):
        bus.publish(_make_message(payload={'i': i}))

    result = bus.consume(to_agent='planner', limit=2)
    assert len(result) == 2


def test_atomic_write_pattern(bus, tmp_path):
    '''메시지 발행 후 DB 파일이 존재하고 tmp 파일이 없음'''
    import glob
    bus.publish(_make_message())
    tmp_files = glob.glob(str(tmp_path / '*.tmp.*'))
    assert len(tmp_files) == 0, f'임시 파일 잔존: {tmp_files}'
