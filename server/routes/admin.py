# 관리자/자가개선 관련 엔드포인트
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from log_bus.event_bus import LogEvent, event_bus
from orchestration.office import Office

router = APIRouter()


@router.post('/api/server/restart')
async def restart_server(request: Request):
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
  async def _bye():
    await _a.sleep(1.0)
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message='♻️ 서버 재시작 중... (약 5초 후 재연결)',
    ))
    await _a.sleep(0.5)
    _os._exit(0)
  _a.create_task(_bye())
  return {'restarting': True, 'eta_sec': 5}


@router.post('/api/teamlead/review')
async def trigger_teamlead_review(request: Request):
  '''팀장 배치 리뷰를 수동 트리거. 이미 실행 중이면 거절.'''
  import asyncio
  office: Office = request.app.state.office
  if not hasattr(office, '_review_lock'):
    office._review_lock = asyncio.Lock()
  if office._review_lock.locked():
    return {'queued': False, 'message': '이미 리뷰가 실행 중입니다'}
  async def _run_once():
    async with office._review_lock:
      await office._run_single_review(force=True)
  asyncio.create_task(_run_once())
  return {'queued': True, 'message': '팀장 리뷰 대기열 투입'}


@router.get('/api/improvement/metrics')
async def get_improvement_metrics(request: Request):
  '''프로젝트별 성과 메트릭을 반환한다.'''
  office: Office = request.app.state.office
  return office.improvement_engine.get_metrics_summary()


@router.get('/api/improvement/rules/{agent}')
async def get_agent_rules(agent: str, request: Request):
  '''에이전트별 학습된 품질 규칙 목록을 반환한다.'''
  office: Office = request.app.state.office
  rules = office.improvement_engine.prompt_evolver.load_rules(agent)
  return [asdict(r) for r in rules]


@router.post('/api/improvement/rules/{agent}/toggle')
async def toggle_agent_rule(agent: str, request: Request):
  '''규칙 활성화/비활성화 토글.'''
  body = await request.json()
  rule_id = body.get('rule_id', '')
  active = body.get('active', True)
  office: Office = request.app.state.office
  success = office.improvement_engine.prompt_evolver.toggle_rule(agent, rule_id, active)
  if not success:
    raise HTTPException(status_code=404, detail='규칙을 찾을 수 없습니다')
  return {'success': True, 'rule_id': rule_id, 'active': active}
