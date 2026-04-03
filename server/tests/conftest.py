# pytest 공유 fixture: 인메모리 SQLite, 임시 workspace 디렉토리
import pytest
import sqlite3
import tempfile
from pathlib import Path

@pytest.fixture
def in_memory_db():
    '''인메모리 SQLite 연결 — WAL 모드 테스트용'''
    conn = sqlite3.connect(':memory:')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

@pytest.fixture
def tmp_workspace(tmp_path):
    '''임시 workspace 루트 디렉토리'''
    ws = tmp_path / 'workspace'
    ws.mkdir()
    return ws
