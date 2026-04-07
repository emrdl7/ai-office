# SQLite WAL 모드 연결 관리 (INFR-01)
from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path('data/bus.db')

def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    '''SQLite WAL 모드 연결 반환.

    PRAGMA 설정:
    - journal_mode=WAL: 다중 에이전트 동시 읽기/쓰기 안전
    - synchronous=NORMAL: WAL 모드에서 FULL 대비 2-3x 빠름
    - foreign_keys=ON: 참조 무결성 강제
    - busy_timeout=5000: 5초 대기 후 SQLITE_BUSY 에러 (Pitfall 3 방지)
    '''
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    '''메시지 버스 테이블 및 인덱스 생성'''
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            from_agent  TEXT NOT NULL,
            to_agent    TEXT NOT NULL,
            payload     TEXT NOT NULL,
            reply_to    TEXT,
            priority    TEXT NOT NULL DEFAULT 'normal',
            tags        TEXT NOT NULL DEFAULT '[]',
            metadata    TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL,
            ack_at      TEXT,
            status      TEXT NOT NULL DEFAULT 'pending'
        );

        CREATE INDEX IF NOT EXISTS idx_messages_to_status
            ON messages(to_agent, status, created_at);
    ''')
    conn.commit()
