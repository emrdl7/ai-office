# 로그 및 WebSocket 엔드포인트
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from log_bus.event_bus import LogEvent, event_bus

router = APIRouter()
logger = logging.getLogger(__name__)

# 긍정/부정 이모지 매핑
POSITIVE_EMOJIS = {'👍', '❤️', '🙌', '👏', '✨', '🔥', '💯', '🎉'}
NEGATIVE_EMOJIS = {'👎', '😡', '❌', '⚠️', '🤔'}
POSITIVE_THRESHOLD = 2
NEGATIVE_THRESHOLD = 1


@router.delete('/api/logs')
async def clear_logs_api() -> dict[str, int]:
  '''채팅 로그를 모두 삭제한다.'''
  from db.log_store import clear_logs
  count = clear_logs()
  return {'deleted': count}


@router.get('/api/logs/history')
async def get_log_history(request: Request, limit: int = 100) -> list[dict[str, Any]]:
  '''최근 로그 기록을 반환한다 (DASH-03 새로고침 복구용).

  limit: 반환할 최대 건수 (기본 100, 최대 500)
  '''
  from db.log_store import load_logs
  limit = min(limit, 500)
  return load_logs(limit=limit)


@router.post('/api/logs/{log_id}/react')
async def react_to_log(log_id: str, request: Request) -> Any:
  '''메시지에 이모지 리액션을 추가/토글한다.'''
  from db.log_store import update_log_reactions
  body = await request.json()
  emoji = body.get('emoji', '👍')
  user = body.get('user', 'user')
  reactions = update_log_reactions(log_id, emoji, user)
  if reactions is None:
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={'error': 'log not found'})

  await event_bus.publish(LogEvent(
    agent_id='system',
    event_type='reaction_update',
    message='',
    data={'log_id': log_id, 'reactions': reactions},
  ))

  try:
    await _apply_reaction_learning(log_id, reactions, emoji)
  except Exception:
    logger.warning("리액션 학습 훅 실패", exc_info=True)

  return {'reactions': reactions}


async def _apply_reaction_learning(log_id: str, reactions: dict, emoji: str) -> None:
  '''리액션이 임계치를 넘으면 학습 시스템에 시그널 기록.'''
  from db.log_store import get_log
  log = get_log(log_id)
  if not log:
    return
  if log['agent_id'] in ('user', 'system'):
    return
  if not log.get('message') or len(log['message'].strip()) < 10:
    return

  positive_total = sum(len(v) for k, v in reactions.items() if k in POSITIVE_EMOJIS)
  negative_total = sum(len(v) for k, v in reactions.items() if k in NEGATIVE_EMOJIS)
  agent_id = log['agent_id']
  msg_preview = log['message'][:200]

  existing_data = log.get('data') or {}
  already = existing_data.get('learning_logged', {})

  if emoji in POSITIVE_EMOJIS and positive_total >= POSITIVE_THRESHOLD and not already.get('positive'):
    from memory.team_memory import TeamMemory, SharedLesson
    from datetime import datetime, timezone
    try:
      TeamMemory().add_lesson(SharedLesson(
        id=f'react-pos-{log_id[:8]}',
        project_title='리액션 피드백',
        agent_name=agent_id,
        lesson=f'{agent_id}의 응답이 호응을 받음: "{msg_preview[:80]}"',
        category='success_pattern',
        timestamp=datetime.now(timezone.utc).isoformat(),
      ))
      _mark_learning_logged(log_id, 'positive')
      logger.info('리액션 학습: %s 긍정 패턴 기록 (%d표)', agent_id, positive_total)
    except Exception:
      logger.debug('TeamMemory 기록 실패', exc_info=True)

  if emoji in NEGATIVE_EMOJIS and negative_total >= NEGATIVE_THRESHOLD and not already.get('negative'):
    from harness.rejection_analyzer import record_rejection
    try:
      record_rejection(
        feedback=f'{agent_id} 응답에 👎 피드백: "{msg_preview[:120]}"',
        task_type=f'user_reaction_{agent_id}',
      )
      _mark_learning_logged(log_id, 'negative')
      logger.info('리액션 학습: %s 부정 패턴 기록 (%d표)', agent_id, negative_total)
    except Exception:
      logger.debug('rejection 기록 실패', exc_info=True)


def _mark_learning_logged(log_id: str, kind: str) -> None:
  '''해당 log_id의 data에 learning_logged 플래그를 세팅 — 중복 학습 방지.'''
  import sqlite3, json
  from db.log_store import DB_PATH
  c = sqlite3.connect(str(DB_PATH))
  c.row_factory = sqlite3.Row
  row = c.execute('SELECT data FROM chat_logs WHERE id=?', (log_id,)).fetchone()
  if row:
    data = json.loads(row['data']) if row['data'] else {}
    flags = data.get('learning_logged', {})
    flags[kind] = True
    data['learning_logged'] = flags
    c.execute('UPDATE chat_logs SET data=? WHERE id=?', (json.dumps(data, ensure_ascii=False), log_id))
    c.commit()
  c.close()


@router.get('/api/ws-token')
async def get_ws_token(request: Request) -> dict[str, str]:
  '''프론트엔드에서 WebSocket 연결 시 사용할 인증 토큰 반환.'''
  return {'token': request.app.state.ws_token}


@router.websocket('/ws/logs')
async def log_stream(ws: WebSocket, token: str = Query(default='')) -> None:
  '''실시간 에이전트 로그 스트림 (저장은 EventBus에서 처리)'''
  if token != ws.app.state.ws_token:
    await ws.close(code=4003, reason='Unauthorized')
    return
  await ws.accept()
  q = event_bus.subscribe()
  try:
    while True:
      event: LogEvent = await q.get()
      await ws.send_json(asdict(event))
  except WebSocketDisconnect:
    pass
  finally:
    event_bus.unsubscribe(q)
