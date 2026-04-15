# chat_logs 아카이빙 — 임계치 트리거 + 라운드트립.
import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture
def isolated_log_db(tmp_path, monkeypatch):
  import db.log_store as ls
  monkeypatch.setattr(ls, 'DB_PATH', tmp_path / 'logs.db')
  yield ls


def _save(ls, n: int, days_ago: int):
  ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
  for i in range(n):
    ls.save_log({
      'id': f'd{days_ago}-{i}',
      'agent_id': 'developer',
      'event_type': 'response',
      'message': f'msg{i}',
      'data': {},
      'timestamp': ts,
    })


def test_archive_old_logs_moves_only_old(isolated_log_db):
  ls = isolated_log_db
  _save(ls, 3, days_ago=40)
  _save(ls, 2, days_ago=5)

  moved = ls.archive_old_logs(days=30)
  assert moved == 3

  # chat_logs에는 최근 2건만 남음
  c = ls._conn()
  remaining = c.execute('SELECT COUNT(*) FROM chat_logs').fetchone()[0]
  archived = c.execute('SELECT COUNT(*) FROM chat_logs_archive').fetchone()[0]
  c.close()
  assert remaining == 2
  assert archived == 3


def test_maybe_archive_skips_when_below_threshold(isolated_log_db):
  ls = isolated_log_db
  _save(ls, 5, days_ago=40)  # 30일+ 5건 < 1만건 임계
  moved = ls.maybe_archive_logs(days=30)
  assert moved == 0


def test_maybe_archive_triggers_when_count_exceeded(isolated_log_db, monkeypatch):
  ls = isolated_log_db
  monkeypatch.setattr(ls, 'ARCHIVE_TRIGGER_OLD_COUNT', 3)  # 임계치를 낮춰 트리거 유도
  _save(ls, 5, days_ago=40)
  moved = ls.maybe_archive_logs(days=30)
  assert moved == 5
