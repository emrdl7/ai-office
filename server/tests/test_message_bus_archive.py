# archive_old_messages 동작 검증
# - 30일 경과 done 메시지만 messages_archive로 이동
# - pending/recent done은 유지
# - archived_at 기록

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json

import pytest

from bus.message_bus import MessageBus
from bus.schemas import AgentMessage


def _msg(to: str = 'planner', status: str = 'done', ack_at: datetime | None = None,
         created_at: datetime | None = None) -> AgentMessage:
  now = datetime.now(timezone.utc)
  return AgentMessage.model_validate({
    'id': str(uuid.uuid4()),
    'type': 'conversation',
    'from': 'teamlead',
    'to': to,
    'payload': {'text': 'test'},
    'priority': 'normal',
    'tags': [],
    'metadata': {},
    'created_at': (created_at or now).isoformat(),
    'ack_at': ack_at.isoformat() if ack_at else None,
    'status': status,
  })


def _publish_raw(bus: MessageBus, msg: AgentMessage) -> None:
  '''publish 우회: ack_at·created_at을 과거로 강제 주입하기 위해 직접 INSERT.'''
  data = msg.model_dump(by_alias=False)
  bus._conn.execute(
    '''INSERT INTO messages
       (id, type, from_agent, to_agent, payload, reply_to,
        priority, tags, metadata, created_at, ack_at, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    (
      data['id'], data['type'], data['from_agent'], data['to_agent'],
      json.dumps(data['payload']), data['reply_to'],
      data['priority'], json.dumps(data['tags']), json.dumps(data['metadata']),
      data['created_at'] if isinstance(data['created_at'], str) else data['created_at'].isoformat(),
      data['ack_at'] if isinstance(data['ack_at'], (str, type(None))) else data['ack_at'].isoformat(),
      data['status'],
    ),
  )
  bus._conn.commit()


@pytest.fixture
def bus(tmp_path):
  b = MessageBus(db_path=tmp_path / 'test.db')
  yield b
  b.close()


def test_archives_old_done_messages(bus):
  now = datetime.now(timezone.utc)
  old = now - timedelta(days=45)
  _publish_raw(bus, _msg(status='done', ack_at=old, created_at=old - timedelta(days=1)))

  moved = bus.archive_old_messages(days=30)

  assert moved == 1
  hot = bus._conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
  arc = bus._conn.execute('SELECT COUNT(*) FROM messages_archive').fetchone()[0]
  assert hot == 0
  assert arc == 1
  row = bus._conn.execute('SELECT archived_at FROM messages_archive').fetchone()
  assert row['archived_at']  # 기록됨


def test_keeps_recent_done_messages(bus):
  now = datetime.now(timezone.utc)
  recent = now - timedelta(days=5)
  _publish_raw(bus, _msg(status='done', ack_at=recent))

  moved = bus.archive_old_messages(days=30)

  assert moved == 0
  assert bus._conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1


def test_keeps_pending_messages_regardless_of_age(bus):
  # pending은 오래 돼도 이관 금지 (처리 전)
  old = datetime.now(timezone.utc) - timedelta(days=365)
  _publish_raw(bus, _msg(status='pending', ack_at=None, created_at=old))

  moved = bus.archive_old_messages(days=30)

  assert moved == 0
  assert bus._conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1


def test_uses_created_at_when_ack_at_missing(bus):
  # ack_at이 없어도 created_at이 30일 이전이면 이관
  old = datetime.now(timezone.utc) - timedelta(days=60)
  _publish_raw(bus, _msg(status='done', ack_at=None, created_at=old))

  moved = bus.archive_old_messages(days=30)

  assert moved == 1


def test_custom_retention_days(bus):
  day5 = datetime.now(timezone.utc) - timedelta(days=5)
  _publish_raw(bus, _msg(status='done', ack_at=day5))

  # 3일 보관이면 5일 전 done은 이관 대상
  moved = bus.archive_old_messages(days=3)
  assert moved == 1
