# SQLite WAL 모드 연결 관리 (INFR-01)
# 실제 구현: 01-02-PLAN
import sqlite3
from pathlib import Path

DB_PATH = Path('data/bus.db')

def get_connection() -> sqlite3.Connection:
    raise NotImplementedError('01-02-PLAN에서 구현 예정')
