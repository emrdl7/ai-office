'''사용자 토론 토픽 제시 API

사용자가 "Next.js 15 React Compiler에 대해 토론해줘" 같은 토픽을 등록하면
다음 자율 사이클에서 _choose_topic 결과를 강제로 덮어쓴다 (1회성).

큐 기반: 등록은 파일 append, 자율 루프는 pop.
'''
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

_QUEUE_PATH = Path(__file__).parent.parent / 'data' / 'user_topics_queue.json'


def _load_queue() -> list[dict[str, Any]]:
  try:
    return json.loads(_QUEUE_PATH.read_text(encoding='utf-8'))
  except Exception:
    return []


def _save_queue(items: list[dict[str, Any]]) -> None:
  _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
  _QUEUE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')


def pop_next_topic() -> str:
  '''자율 루프에서 호출 — 가장 오래된 미사용 토픽을 pop & 마킹.'''
  items = _load_queue()
  for it in items:
    if not it.get('consumed'):
      it['consumed'] = True
      it['consumed_at'] = datetime.now(timezone.utc).isoformat()
      _save_queue(items)
      return it.get('topic', '')
  return ''


class TopicRequest(BaseModel):
  topic: str


@router.post('/api/topics/discuss')
async def submit_topic(req: TopicRequest) -> dict[str, Any]:
  '''사용자가 토론 토픽 등록 — 다음 자율 사이클에서 강제 주제로 사용.'''
  topic = req.topic.strip()
  if not topic or len(topic) < 5:
    return {'ok': False, 'error': '토픽은 5자 이상'}
  if len(topic) > 500:
    topic = topic[:500]

  items = _load_queue()
  items.append({
    'topic': topic,
    'submitted_at': datetime.now(timezone.utc).isoformat(),
    'consumed': False,
  })
  # 최근 50개만 유지
  items = items[-50:]
  _save_queue(items)
  logger.info('사용자 토픽 등록: %s', topic[:80])
  return {'ok': True, 'queued': len([i for i in items if not i.get('consumed')])}


@router.get('/api/topics/discuss')
async def list_topics() -> dict[str, Any]:
  '''등록된 토픽 큐 조회.'''
  items = _load_queue()
  pending = [i for i in items if not i.get('consumed')]
  consumed = [i for i in items if i.get('consumed')]
  return {
    'pending': pending,
    'recent_consumed': consumed[-5:],
  }
