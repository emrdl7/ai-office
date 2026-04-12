# 채팅 로그 영속 저장소 — SQLite 기반
import json
import sqlite3
from pathlib import Path

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
  conn.commit()
  return conn


def save_log(log_dict: dict) -> None:
  '''로그를 저장한다.'''
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
