# pytest 공유 fixture: 인메모리 SQLite, 임시 workspace 디렉토리
import pytest
import sqlite3
import tempfile
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_prod_dbs(tmp_path_factory, monkeypatch):
    '''모든 테스트에서 프로덕션 DB 경로를 임시 파일로 치환하는 안전망.

    테스트가 EventBus.publish / save_log / create_suggestion 등을 호출할 때
    실제 `data/*.db`에 쓰는 사고를 방지한다. 개별 테스트가 tmp_path로
    재설정하면 해당 값이 우선 적용된다(monkeypatch 스택이 나중 것 우선).

    과거 사고: test_project_runner_e2e가 log_store를 격리하지 않아
    프로덕션 chat_logs에 "샘플 프로젝트 만들어줘" + 스크립트 placeholder
    응답이 기록됨.
    '''
    tmp_root = tmp_path_factory.mktemp('isolated_db')
    try:
        import db.log_store as _ls
        monkeypatch.setattr(_ls, 'DB_PATH', tmp_root / 'logs.db')
    except Exception:
        pass
    try:
        import db.suggestion_store as _ss
        monkeypatch.setattr(_ss, 'DB_PATH', tmp_root / 'sugg.db')
    except Exception:
        pass
    try:
        import db.task_store as _ts
        monkeypatch.setattr(_ts, 'DB_PATH', tmp_root / 'tasks.db')
    except Exception:
        pass
    # workspace 격리 — restore_pending_tasks 등이 하드코딩 경로로 prod 디렉토리를
    # 잡지 못하게 core.paths.WORKSPACE_ROOT를 임시 디렉토리로 치환.
    try:
        from core import paths as _paths
        ws = tmp_root / 'workspace'
        ws.mkdir(exist_ok=True)
        monkeypatch.setattr(_paths, 'WORKSPACE_ROOT', ws)
        mem = tmp_root / 'memory'
        mem.mkdir(exist_ok=True)
        monkeypatch.setattr(_paths, 'MEMORY_ROOT', mem)
    except Exception:
        pass
    yield


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
