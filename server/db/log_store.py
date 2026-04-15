# 채팅 로그 영속 저장소 — SQLite 기반
import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / 'data' / 'logs.db'


def _conn() -> sqlite3.Connection:
  DB_PATH.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(str(DB_PATH))
  conn.row_factory = sqlite3.Row
  conn.execute('PRAGMA journal_mode=WAL')
  conn.execute('''
    CREATE TABLE IF NOT EXISTS chat_logs (
      id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      message TEXT NOT NULL,
      data TEXT DEFAULT '{}',
      timestamp TEXT NOT NULL
    )
  ''')
  # 최근 조회·정렬에 쓰는 timestamp DESC 인덱스 (로그 10만건 넘어도 빠름)
  conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_logs_ts ON chat_logs(timestamp DESC)')
  # 아카이브 테이블 — 임계치 도달 시 30일+ 로그를 이관 (메시지 버스 archive 동일 패턴)
  conn.execute('''
    CREATE TABLE IF NOT EXISTS chat_logs_archive (
      id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      message TEXT NOT NULL,
      data TEXT DEFAULT '{}',
      timestamp TEXT NOT NULL,
      archived_at TEXT NOT NULL
    )
  ''')
  conn.execute('CREATE INDEX IF NOT EXISTS idx_chat_logs_archive_ts ON chat_logs_archive(timestamp DESC)')
  conn.commit()
  return conn


# 임계치 — 둘 중 하나라도 충족하면 아카이브 트리거
ARCHIVE_TRIGGER_OLD_COUNT = 10_000   # 30일+ 로그가 이만큼 쌓이면
ARCHIVE_TRIGGER_DB_SIZE = 50 * 1024 * 1024  # 또는 DB 50MB 초과면


def archive_old_logs(days: int = 30) -> int:
  '''N일 이전 chat_logs를 chat_logs_archive로 이관. 트랜잭션으로 INSERT+DELETE.'''
  from datetime import datetime, timezone, timedelta
  cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
  now = datetime.now(timezone.utc).isoformat()
  c = _conn()
  try:
    c.execute('BEGIN IMMEDIATE')
    c.execute(
      'INSERT OR IGNORE INTO chat_logs_archive '
      '(id, agent_id, event_type, message, data, timestamp, archived_at) '
      'SELECT id, agent_id, event_type, message, data, timestamp, ? '
      'FROM chat_logs WHERE timestamp < ?',
      (now, cutoff),
    )
    moved = c.execute('SELECT changes()').fetchone()[0]
    c.execute('DELETE FROM chat_logs WHERE timestamp < ?', (cutoff,))
    c.commit()
    return moved
  except Exception:
    c.rollback()
    raise
  finally:
    c.close()


def maybe_archive_logs(days: int = 30) -> int:
  '''임계치(30일+ 1만건 또는 DB 50MB 초과) 도달 시에만 아카이브.'''
  stats = log_storage_stats()
  if stats['old_30d'] >= ARCHIVE_TRIGGER_OLD_COUNT or stats['db_size_bytes'] >= ARCHIVE_TRIGGER_DB_SIZE:
    return archive_old_logs(days=days)
  return 0


# placeholder 오염 감지 — 테스트용 mock 문자열이 프로덕션에 유입되면 warning
_PLACEHOLDER_PATTERNS = (
  '초안 내용입니다',
  '샘플 응답입니다',
  'lorem ipsum',
  'Lorem ipsum',
  'TODO: fill',
  'PLACEHOLDER',
)


def _check_placeholder_contamination(log_dict: dict) -> None:
  msg = log_dict.get('message', '') or ''
  agent = log_dict.get('agent_id', '')
  # 테스트/mock 에이전트 이벤트는 예상된 placeholder — 제외
  if agent in ('system', 'user'):
    return
  for pat in _PLACEHOLDER_PATTERNS:
    if pat in msg:
      logger.warning(
        'placeholder 오염 감지 — agent=%s event=%s pattern=%r msg_preview=%r',
        agent, log_dict.get('event_type', ''), pat, msg[:120],
      )
      return


def save_log(log_dict: dict) -> None:
  '''로그를 저장한다.'''
  _check_placeholder_contamination(log_dict)
  c = _conn()
  c.execute(
    'INSERT OR IGNORE INTO chat_logs (id, agent_id, event_type, message, data, timestamp) '
    'VALUES (?, ?, ?, ?, ?, ?)',
    (
      log_dict.get('id', ''),
      log_dict.get('agent_id', ''),
      log_dict.get('event_type', ''),
      log_dict.get('message', ''),
      json.dumps(log_dict.get('data', {}), ensure_ascii=False),
      log_dict.get('timestamp', ''),
    ),
  )
  c.commit()
  c.close()


def log_storage_stats() -> dict:
  '''로그 저장 현황 — 총 건수/30일+ 건수/DB 파일 크기(바이트).'''
  from datetime import datetime, timezone, timedelta
  from pathlib import Path as _P
  c = _conn()
  total = c.execute('SELECT COUNT(*) FROM chat_logs').fetchone()[0]
  cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
  old = c.execute('SELECT COUNT(*) FROM chat_logs WHERE timestamp < ?', (cutoff,)).fetchone()[0]
  c.close()
  db_file = _P(__file__).parent.parent / 'data' / 'logs.db'
  size = db_file.stat().st_size if db_file.exists() else 0
  return {'total': total, 'old_30d': old, 'db_size_bytes': size}


def clear_logs() -> int:
  '''모든 로그를 삭제하고 삭제된 건수를 반환한다.'''
  c = _conn()
  count = c.execute('SELECT COUNT(*) FROM chat_logs').fetchone()[0]
  c.execute('DELETE FROM chat_logs')
  c.commit()
  c.close()
  return count


def update_log_reactions(log_id: str, emoji: str, user: str = 'user') -> dict | None:
  '''로그에 이모지 리액션을 추가/토글한다.'''
  c = _conn()
  row = c.execute('SELECT data FROM chat_logs WHERE id = ?', (log_id,)).fetchone()
  if not row:
    c.close()
    return None
  data = json.loads(row['data']) if row['data'] else {}
  reactions: dict[str, list[str]] = data.get('reactions', {})
  if emoji in reactions:
    if user in reactions[emoji]:
      reactions[emoji].remove(user)
      if not reactions[emoji]:
        del reactions[emoji]
    else:
      reactions[emoji].append(user)
  else:
    reactions[emoji] = [user]
  data['reactions'] = reactions
  c.execute('UPDATE chat_logs SET data = ? WHERE id = ?', (json.dumps(data, ensure_ascii=False), log_id))
  c.commit()
  c.close()
  return reactions


def get_log(log_id: str) -> dict | None:
  '''단일 로그 조회 (에이전트/메시지/데이터 포함).'''
  c = _conn()
  row = c.execute(
    'SELECT id, agent_id, event_type, message, data, timestamp '
    'FROM chat_logs WHERE id = ?', (log_id,)
  ).fetchone()
  c.close()
  if not row:
    return None
  return {
    'id': row['id'],
    'agent_id': row['agent_id'],
    'event_type': row['event_type'],
    'message': row['message'],
    'data': json.loads(row['data']) if row['data'] else {},
    'timestamp': row['timestamp'],
  }


def get_reaction_stats(limit_days: int = 30) -> dict:
  '''에이전트별 받은 리액션 집계 — 통계 대시보드용.

  Returns:
    {'per_agent': {agent_id: {emoji: count}}, 'totals': {emoji: count}}
  '''
  from datetime import datetime, timezone, timedelta
  cutoff = (datetime.now(timezone.utc) - timedelta(days=limit_days)).isoformat()
  c = _conn()
  rows = c.execute(
    'SELECT agent_id, data FROM chat_logs WHERE timestamp >= ?', (cutoff,)
  ).fetchall()
  c.close()

  per_agent: dict[str, dict[str, int]] = {}
  totals: dict[str, int] = {}
  for r in rows:
    try:
      data = json.loads(r['data']) if r['data'] else {}
    except json.JSONDecodeError:
      continue
    reactions = data.get('reactions') or {}
    if not reactions:
      continue
    agent = r['agent_id']
    agent_bucket = per_agent.setdefault(agent, {})
    for emoji, users in reactions.items():
      count = len(users) if isinstance(users, list) else 0
      agent_bucket[emoji] = agent_bucket.get(emoji, 0) + count
      totals[emoji] = totals.get(emoji, 0) + count
  return {'per_agent': per_agent, 'totals': totals}


def load_logs(limit: int = 200) -> list[dict]:
  '''최근 로그를 반환한다.'''
  c = _conn()
  rows = c.execute(
    'SELECT id, agent_id, event_type, message, data, timestamp '
    'FROM chat_logs ORDER BY timestamp DESC LIMIT ?',
    (limit,),
  ).fetchall()
  c.close()
  result = []
  for r in reversed(rows):
    result.append({
      'id': r['id'],
      'agent_id': r['agent_id'],
      'event_type': r['event_type'],
      'message': r['message'],
      'data': json.loads(r['data']) if r['data'] else {},
      'timestamp': r['timestamp'],
    })
  return result


def search_logs(
  q: str = '',
  agent_id: str = '',
  include_archive: bool = False,
  limit: int = 100,
  event_types: list[str] | None = None,
) -> list[dict]:
  '''채팅 로그 검색. q는 message LIKE, agent_id는 정확 매치.

  include_archive=True면 chat_logs_archive도 UNION으로 함께 검색.
  event_types가 주어지면 해당 타입만 (실패 이벤트 프리셋용).
  결과는 timestamp DESC, 최대 limit건.
  '''
  q_trim = (q or '').strip()
  c = _conn()
  params: list = []
  where = []
  if q_trim:
    where.append('message LIKE ?')
    params.append(f'%{q_trim}%')
  if agent_id:
    where.append('agent_id = ?')
    params.append(agent_id)
  if event_types:
    placeholders = ','.join('?' * len(event_types))
    where.append(f'event_type IN ({placeholders})')
    params.extend(event_types)
  where_sql = f'WHERE {" AND ".join(where)}' if where else ''
  base = (
    f'SELECT id, agent_id, event_type, message, data, timestamp '
    f'FROM chat_logs {where_sql}'
  )
  if include_archive:
    base = (
      base + ' UNION ALL '
      + f'SELECT id, agent_id, event_type, message, data, timestamp '
      + f'FROM chat_logs_archive {where_sql}'
    )
    params = params + list(params)  # WHERE 두 번 바인딩
  sql = base + ' ORDER BY timestamp DESC LIMIT ?'
  params.append(limit)
  rows = c.execute(sql, params).fetchall()
  c.close()
  return [
    {
      'id': r['id'],
      'agent_id': r['agent_id'],
      'event_type': r['event_type'],
      'message': r['message'],
      'data': json.loads(r['data']) if r['data'] else {},
      'timestamp': r['timestamp'],
    }
    for r in rows
  ]
