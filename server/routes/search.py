# 건의 리스트 + 통합 검색 엔드포인트
from typing import Any
from fastapi import APIRouter

router = APIRouter()


@router.get('/api/suggestions')
async def list_suggestions_api(
  status: str = '',
  category: str = '',
  target_agent: str = '',
  q: str = '',
  limit: int = 0,
) -> list[dict[str, Any]]:
  '''건의 목록을 반환한다. status/category/target_agent 매치, q는 title+content LIKE.'''
  from db.suggestion_store import list_suggestions
  return list_suggestions(
    status=status, category=category, target_agent=target_agent, q=q, limit=limit,
  )


# 실패/경고 이벤트 프리셋 — 'preset=errors' 지정 시 아래 타입만 필터
_ERROR_EVENT_TYPES = ['error', 'system_notice']


@router.get('/api/search')
async def unified_search_api(
  q: str = '',
  type: str = 'all',
  agent_id: str = '',
  include_archive: bool = False,
  limit: int = 50,
  preset: str = '',
) -> dict[str, Any]:
  '''chat_logs / suggestions / dynamics 통합 검색.

  type: 'logs' | 'suggestions' | 'dynamics' | 'all'
  preset: 'errors' → logs만 event_type in (error, system_notice)로 제한
  '''
  from db.log_store import search_logs
  from db.suggestion_store import list_suggestions
  result: dict[str, Any] = {'q': q, 'type': type, 'preset': preset}
  t = (type or 'all').lower()
  event_types = _ERROR_EVENT_TYPES if preset == 'errors' else None
  if preset == 'errors':
    t = 'logs'  # 실패 프리셋은 logs만 의미 있음
    result['type'] = 'logs'
  if t in ('logs', 'all'):
    result['logs'] = search_logs(
      q=q, agent_id=agent_id, include_archive=include_archive, limit=limit,
      event_types=event_types,
    )
  if t in ('suggestions', 'all'):
    result['suggestions'] = list_suggestions(q=q, target_agent=agent_id, limit=limit)
  if t in ('dynamics', 'all'):
    try:
      from memory.team_memory import TeamMemory
      tm = TeamMemory()
      data = tm._load()
      dynamics = data.get('dynamics', [])
      q_trim = (q or '').strip().lower()
      filtered = []
      for d in dynamics:
        if agent_id and d.get('from_agent') != agent_id and d.get('to_agent') != agent_id:
          continue
        if q_trim:
          hay = ((d.get('description') or '') + ' ' + (d.get('dynamic_type') or '')).lower()
          if q_trim not in hay:
            continue
        filtered.append(d)
      filtered.sort(key=lambda d: d.get('timestamp', ''), reverse=True)
      result['dynamics'] = filtered[:limit]
    except Exception:
      result['dynamics'] = []
  return result
