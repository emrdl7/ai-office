# 팀/에이전트 조회 엔드포인트
from typing import Any

from fastapi import APIRouter, Request

from orchestration.office import Office, OfficeState

router = APIRouter()


@router.get('/api/agents')
async def get_agents(request: Request) -> list[dict[str, Any]]:
  '''에이전트별 현재 상태를 Office 상태에서 추론한다.'''
  office: Office = request.app.state.office
  state = office._state

  state_to_active: dict[OfficeState, str] = {
    OfficeState.TEAMLEAD_THINKING: 'teamlead',
    OfficeState.MEETING: 'all',
    OfficeState.WORKING: office._active_agent or 'working',
    OfficeState.QA_REVIEW: 'qa',
    OfficeState.TEAMLEAD_REVIEW: 'teamlead',
    OfficeState.REVISION: 'planner',
  }

  active = state_to_active.get(state, '')

  is_working = state in {
    OfficeState.TEAMLEAD_THINKING, OfficeState.MEETING,
    OfficeState.WORKING, OfficeState.QA_REVIEW,
    OfficeState.TEAMLEAD_REVIEW, OfficeState.REVISION,
  }

  agents: list[dict[str, Any]] = []
  for agent_id in ['teamlead', 'planner', 'designer', 'developer', 'qa']:
    if active == 'all':
      status = 'meeting'
    elif active == agent_id:
      status = 'working'
    elif state in {OfficeState.IDLE, OfficeState.COMPLETED, OfficeState.ESCALATED}:
      status = 'idle'
    else:
      status = 'waiting'

    if not is_working:
      model = 'Gemini'
    elif agent_id == 'teamlead':
      model = 'Claude Haiku'
    elif agent_id == 'qa':
      model = 'Claude Haiku'
    elif agent_id == 'planner':
      model = 'Gemini'
    elif agent_id == 'developer':
      model = 'Gemini'
    elif agent_id == 'designer':
      model = 'Claude Sonnet'
    else:
      model = 'Claude Sonnet'

    agents.append({
      'agent_id': agent_id,
      'status': status,
      'model': model,
      'work_started_at': office._work_started_at if status in ('working', 'meeting') else '',
      'current_phase': office._current_phase if status == 'working' and active == agent_id else '',
      'active_project_title': office._active_project_title if status in ('working', 'meeting', 'waiting') else '',
    })
  return agents


@router.get('/api/agents/quotes')
async def get_daily_quotes() -> dict[str, str]:
  '''오늘의 한마디 반환. 없으면 Haiku로 생성 후 캐싱.'''
  from db.daily_quote_store import get_quotes, save_quotes, AGENT_PERSONAS
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError

  cached = get_quotes()
  if len(cached) >= 5:
    return cached

  persona_block = '\n'.join(
    f'- {agent_id}: {persona}'
    for agent_id, persona in AGENT_PERSONAS.items()
  )
  prompt = (
    '아래 5명의 직장인 캐릭터가 오늘 아침 출근하며 한마디씩 합니다.\n'
    '각 캐릭터의 성격을 살려, 짧고 인상적인 한마디를 만들어 주세요.\n'
    '일상적인 감상, 일에 대한 생각, 오늘 날씨, 인생 통찰 등 자유롭게.\n'
    '20자 이내, 구어체, 말줄임표 사용 가능, 직접 인용처럼.\n\n'
    f'{persona_block}\n\n'
    '아래 JSON 형식으로만 답하세요 (설명 없이):\n'
    '{"teamlead":"...", "planner":"...", "designer":"...", "developer":"...", "qa":"..."}'
  )

  try:
    result = await run_claude_isolated(
      prompt,
      model='claude-haiku-4-5-20251001',
      timeout=30.0,
      max_turns=1,
    )
    from runners.json_parser import parse_json
    parsed = parse_json(result)
    if parsed and isinstance(parsed, dict) and len(parsed) >= 5:
      quotes = {k: str(v) for k, v in parsed.items() if k in AGENT_PERSONAS}
      save_quotes(quotes)
      return quotes
  except (ClaudeRunnerError, Exception):
    pass

  from config.team import TEAM
  fallback = {m.agent_id: m.fallback_quote for m in TEAM}
  save_quotes(fallback)
  return fallback


@router.get('/api/team')
async def get_team() -> list[dict[str, Any]]:
  '''팀 구성 조회 — 프론트엔드에서 이름/역할/페르소나 등을 동기화한다.'''
  from config.team import to_api_dict
  return to_api_dict()


@router.get('/api/team-memory')
async def get_team_memory() -> dict[str, Any]:
  '''팀 공유 메모리 조회 — 교훈, 협업 패턴, 프로젝트 이력'''
  from memory.team_memory import TeamMemory
  tm = TeamMemory()
  return {
    'lessons': [
      {'id': l.id, 'project': l.project_title, 'agent': l.agent_name,
       'lesson': l.lesson, 'category': l.category, 'timestamp': l.timestamp}
      for l in tm.get_all_lessons(limit=15)
    ],
    'projects': [
      {'id': p.project_id, 'title': p.title, 'type': p.project_type,
       'outcome': p.outcome, 'decisions': p.key_decisions, 'timestamp': p.timestamp}
      for p in tm.get_recent_projects(limit=10)
    ],
  }


@router.get('/api/reactions/stats')
async def get_reaction_stats_api(days: int = 30) -> dict[str, Any]:
  '''에이전트별 리액션 통계 (최근 N일).'''
  from db.log_store import get_reaction_stats
  return get_reaction_stats(limit_days=days)


@router.get('/api/team/persona-drift')
async def get_persona_drift(request: Request, hours: int = 48) -> dict[str, Any]:
  '''에이전트별 페르소나 드리프트 점수 (0-10) 반환.

  최근 N시간 발화 샘플 → Haiku 채점 → drift_detected 이벤트 기록.
  캐시: 마지막 실행 결과를 office state에 저장해 30분 내 재요청은 LLM 없이 반환.
  '''
  import json
  import re
  from datetime import datetime, timezone, timedelta
  from db.log_store import load_logs
  from runners.claude_runner import run_claude_isolated
  from config.team import display_name
  from log_bus.event_bus import LogEvent

  office: Office = request.app.state.office

  # 30분 캐시
  cache: dict[str, Any] | None = getattr(office, '_persona_drift_cache', None)
  if cache:
    cached_at = cache.get('computed_at', '')
    try:
      if cached_at and (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds() < 1800:
        return cache
    except Exception:
      pass

  cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
  all_logs = load_logs(limit=500)
  recent = [l for l in all_logs if l.get('timestamp', '') >= cutoff]

  AGENTS = ['designer', 'developer', 'planner', 'qa', 'teamlead']

  # agents/*.md 로드 (성격/판단력/대화 스타일 섹션만)
  def _load_persona(name: str) -> str:
    # project root 추론
    import pathlib
    root = pathlib.Path(__file__).parent.parent.parent
    path = root / 'agents' / f'{name}.md'
    if not path.exists():
      return ''
    text = path.read_text(encoding='utf-8')
    SECTIONS = {'성격', '판단력', '대화 스타일'}
    out: list[str] = []
    cur: str | None = None
    for line in text.splitlines():
      if line.startswith('## '):
        cur = line[3:].strip()
      elif cur in SECTIONS:
        out.append(line)
    return '\n'.join(out).strip()

  results: list[dict[str, Any]] = []

  for agent in AGENTS:
    msgs = [
      l['message'] for l in recent
      if l.get('agent_id') == agent
      and l.get('event_type') in ('response', 'autonomous')
      and l.get('message', '').strip()
    ]
    if not msgs:
      results.append({'agent': agent, 'score': None, 'reason': '발화 없음', 'sample_count': 0})
      continue

    sample = msgs[-10:]  # 최근 10개
    persona = _load_persona(agent)
    if not persona:
      results.append({'agent': agent, 'score': None, 'reason': '페르소나 없음', 'sample_count': len(sample)})
      continue

    sample_text = '\n'.join(f'- {m[:200]}' for m in sample)
    prompt = (
      f'아래는 AI 에이전트 "{display_name(agent)}"의 페르소나 선언입니다:\n\n'
      f'{persona}\n\n'
      f'아래는 이 에이전트의 최근 발화 샘플 {len(sample)}개입니다:\n\n'
      f'{sample_text}\n\n'
      f'페르소나 선언과 실제 발화의 일치도를 0-10점으로 채점하세요.\n'
      f'10점 = 완벽히 일치, 0점 = 전혀 다른 캐릭터처럼 발화.\n'
      f'JSON만 출력:\n'
      f'{{"score":7,"reason":"1문장 근거"}}'
    )

    try:
      raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=25.0)
      m = re.search(r'\{[\s\S]*?\}', raw)
      if m:
        parsed = json.loads(m.group())
        score = int(parsed.get('score') or 0)
        reason = str(parsed.get('reason') or '').strip()
      else:
        score = -1
        reason = 'LLM 파싱 실패'
    except Exception as e:
      score = -1
      reason = f'LLM 오류: {e}'

    results.append({
      'agent': agent,
      'score': score if score >= 0 else None,
      'reason': reason,
      'sample_count': len(sample),
    })

    # drift_detected 이벤트 (6점 미만)
    if score >= 0 and score < 6:
      try:
        await office.event_bus.publish(LogEvent(
          agent_id='system',
          event_type='drift_detected',
          message=f'⚠️ 페르소나 드리프트 감지 — {display_name(agent)} {score}/10점: {reason}',
          data={'agent': agent, 'score': score, 'reason': reason},
        ))
      except Exception:
        pass

  now_iso = datetime.now(timezone.utc).isoformat()
  payload: dict[str, Any] = {
    'computed_at': now_iso,
    'period_hours': hours,
    'agents': results,
    'drift_count': sum(1 for r in results if r['score'] is not None and r['score'] < 6),
  }
  office._persona_drift_cache = payload  # type: ignore[attr-defined]
  return payload
