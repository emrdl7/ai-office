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
