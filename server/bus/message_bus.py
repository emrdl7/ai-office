# SQLite WAL 기반 메시지 버스 (INFR-01)
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .schemas import AgentMessage
from db.client import get_connection, init_schema


DEFAULT_ARCHIVE_AFTER_DAYS = 30


class MessageBus:
    def __init__(self, db_path: str | Path = 'data/bus.db'):
        self._conn = get_connection(db_path)
        init_schema(self._conn)

    def publish(self, message: AgentMessage) -> None:
        '''메시지를 버스에 발행 (status=pending)'''
        data = message.model_dump(by_alias=False)
        self._conn.execute(
            '''INSERT INTO messages
               (id, type, from_agent, to_agent, payload, reply_to,
                priority, tags, metadata, created_at, ack_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                data['id'],
                data['type'],
                data['from_agent'],
                data['to_agent'],
                json.dumps(data['payload']),
                data['reply_to'],
                data['priority'],
                json.dumps(data['tags']),
                json.dumps(data['metadata']),
                data['created_at'].isoformat() if isinstance(data['created_at'], datetime) else data['created_at'],
                data['ack_at'].isoformat() if data['ack_at'] and isinstance(data['ack_at'], datetime) else data['ack_at'],
                data['status'],
            ),
        )
        self._conn.commit()

    def consume(self, to_agent: str, limit: int = 10) -> list[AgentMessage]:
        '''pending 메시지를 수신 (created_at 오름차순)'''
        rows = self._conn.execute(
            '''SELECT * FROM messages
               WHERE to_agent = ? AND status = 'pending'
               ORDER BY created_at ASC
               LIMIT ?''',
            (to_agent, limit),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def ack(self, message_id: str) -> None:
        '''메시지 처리 완료 표시 (status=done, ack_at=now)'''
        self._conn.execute(
            "UPDATE messages SET status='done', ack_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), message_id),
        )
        self._conn.commit()

    def _row_to_message(self, row: sqlite3.Row) -> AgentMessage:
        return AgentMessage.model_validate({
            'id': row['id'],
            'type': row['type'],
            'from': row['from_agent'],
            'to': row['to_agent'],
            'payload': json.loads(row['payload']),
            'reply_to': row['reply_to'],
            'priority': row['priority'],
            'tags': json.loads(row['tags']),
            'metadata': json.loads(row['metadata']),
            'created_at': row['created_at'],
            'ack_at': row['ack_at'],
            'status': row['status'],
        })

    def archive_old_messages(self, days: int = DEFAULT_ARCHIVE_AFTER_DAYS) -> int:
        '''완료(status=done)된 N일 이전 메시지를 messages_archive로 이관.

        ack_at이 없으면 created_at 기준. 트랜잭션 하나로 INSERT + DELETE 하여
        부분 실패 시 롤백. 이관된 행 수를 반환.
        '''
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()
        try:
            cur.execute('BEGIN IMMEDIATE')
            # status=done AND COALESCE(ack_at, created_at) < cutoff
            cur.execute(
                '''INSERT INTO messages_archive
                   (id, type, from_agent, to_agent, payload, reply_to,
                    priority, tags, metadata, created_at, ack_at, status, archived_at)
                   SELECT id, type, from_agent, to_agent, payload, reply_to,
                          priority, tags, metadata, created_at, ack_at, status, ?
                   FROM messages
                   WHERE status = 'done'
                     AND COALESCE(ack_at, created_at) < ?''',
                (now, cutoff),
            )
            moved = cur.rowcount
            cur.execute(
                '''DELETE FROM messages
                   WHERE status = 'done'
                     AND COALESCE(ack_at, created_at) < ?''',
                (cutoff,),
            )
            self._conn.commit()
            return moved
        except sqlite3.Error:
            self._conn.rollback()
            raise

    def close(self):
        self._conn.close()
