# 관리자/자가개선 관련 엔드포인트
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from log_bus.event_bus import LogEvent, event_bus
from orchestration.office import Office

router = APIRouter()


@router.post('/api/server/restart')
async def restart_server(request: Request) -> dict[str, Any]:
  '''백엔드 프로세스를 종료 — serve.sh 감독 루프가 3초 내 재기동.

  코드 패치 진행 중이면 거절 (force=true 쿼리로 강제).
  '''
  import os as _os
  import asyncio as _a
  from improvement.code_patcher import _PATCH_LOCK
  force = request.query_params.get('force') == 'true'
  if _PATCH_LOCK.locked() and not force:
    raise HTTPException(
      status_code=409,
      detail='코드 패치가 진행 중입니다. 완료 후 재시작하거나 ?force=true로 강제하세요',
    )
  async def _bye() -> None:
    await _a.sleep(0.5)
    _os._exit(0)
  _a.create_task(_bye())
  return {'restarting': True, 'eta_sec': 5}


@router.get('/api/improvement/rules/{agent}')
async def get_agent_rules(agent: str, request: Request) -> list[dict[str, Any]]:
  '''에이전트별 학습된 품질 규칙 목록을 반환한다.'''
  office: Office = request.app.state.office
  rules = office.improvement_engine.prompt_evolver.load_rules(agent)
  return [asdict(r) for r in rules]


@router.get('/api/cost/today')
async def get_cost_today() -> dict[str, Any]:
  '''오늘 LLM 호출 통계 + Opus 잔여 횟수 + tier별 집계를 반환한다.'''
  from runners.cost_tracker import get_today_stats
  from runners.model_router import _DEEP_TIER_DAILY_LIMIT
  stats = get_today_stats()

  # tier별 집계 — 모델명 패턴으로 tier 추정
  tier_map: dict[str, dict[str, Any]] = {
    'nano/fast': {'label': 'nano/fast (Haiku)', 'calls': 0, 'cost_usd': 0.0, 'color': 'blue'},
    'standard':  {'label': 'standard (Sonnet)', 'calls': 0, 'cost_usd': 0.0, 'color': 'green'},
    'deep':      {'label': 'deep (Opus)',        'calls': 0, 'cost_usd': 0.0, 'color': 'purple'},
    'research':  {'label': 'research (Gemini)',  'calls': 0, 'cost_usd': 0.0, 'color': 'cyan'},
  }
  for m in stats['by_model']:
    model = (m.get('model') or '').lower()
    if 'haiku' in model:
      tier_map['nano/fast']['calls'] += m['calls']
      tier_map['nano/fast']['cost_usd'] += m['cost_usd']
    elif 'opus' in model:
      tier_map['deep']['calls'] += m['calls']
      tier_map['deep']['cost_usd'] += m['cost_usd']
    elif 'sonnet' in model:
      tier_map['standard']['calls'] += m['calls']
      tier_map['standard']['cost_usd'] += m['cost_usd']
    elif 'gemini' in model or m.get('runner') == 'gemini':
      tier_map['research']['calls'] += m['calls']
      tier_map['research']['cost_usd'] += m['cost_usd']

  opus_calls = tier_map['deep']['calls']
  stats['opus_calls_today'] = opus_calls
  stats['opus_daily_limit'] = _DEEP_TIER_DAILY_LIMIT
  stats['opus_remaining'] = max(0, _DEEP_TIER_DAILY_LIMIT - opus_calls)
  stats['by_tier'] = [
    {'tier': k, **v, 'cost_usd': round(v['cost_usd'], 4)}
    for k, v in tier_map.items()
  ]
  return stats


@router.post('/api/improvement/rules/{agent}/toggle')
async def toggle_agent_rule(agent: str, request: Request) -> dict[str, Any]:
  '''규칙 활성화/비활성화 토글.'''
  body = await request.json()
  rule_id = body.get('rule_id', '')
  active = body.get('active', True)
  office: Office = request.app.state.office
  success = office.improvement_engine.prompt_evolver.toggle_rule(agent, rule_id, active)
  if not success:
    raise HTTPException(status_code=404, detail='규칙을 찾을 수 없습니다')
  return {'success': True, 'rule_id': rule_id, 'active': active}
