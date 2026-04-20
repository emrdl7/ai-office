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


@router.get('/api/agents/{agent_id}/growth')
async def get_agent_growth(agent_id: str, days: int = 30) -> dict[str, Any]:
  '''에이전트별 성장 트래킹 — 발화 수, PASS율, 채택 건의, 키워드 다양성, 인용 수.'''
  import sqlite3
  import json
  from datetime import datetime, timedelta, timezone
  from collections import Counter
  from db.log_store import DB_PATH as LOG_DB
  from db.suggestion_store import DB_PATH as SUGG_DB
  from config.team import display_name

  cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

  # 발화 수, PASS 수
  log_conn = sqlite3.connect(str(LOG_DB))
  log_conn.row_factory = sqlite3.Row
  speak_count = log_conn.execute(
    "SELECT count(*) AS n FROM chat_logs "
    "WHERE agent_id=? AND event_type IN ('autonomous','response') AND timestamp >= ?",
    (agent_id, cutoff),
  ).fetchone()['n']
  pass_count = log_conn.execute(
    "SELECT count(*) AS n FROM chat_logs "
    "WHERE agent_id=? AND event_type='autonomous_pass' AND timestamp >= ?",
    (agent_id, cutoff),
  ).fetchone()['n']

  # 키워드 다양성 (TF-IDF는 과중 — 유니크 토큰 수 사용)
  msg_rows = log_conn.execute(
    "SELECT message FROM chat_logs WHERE agent_id=? AND event_type='autonomous' AND timestamp >= ? LIMIT 200",
    (agent_id, cutoff),
  ).fetchall()
  unique_kw: set[str] = set()
  total_kw_count = 0
  try:
    from orchestration.office import _extract_keywords
    for r in msg_rows:
      kws = [k for k in _extract_keywords(r['message'] or '') if len(k) >= 3]
      total_kw_count += len(kws)
      unique_kw.update(kws)
  except Exception:
    pass

  # 동료가 인용/멘션한 횟수 — 발화에 본인 이름 등장 (다른 에이전트 발화에서)
  display = display_name(agent_id)
  cite_rows = log_conn.execute(
    "SELECT count(*) AS n FROM chat_logs "
    "WHERE agent_id != ? AND event_type IN ('autonomous','response') "
    "AND message LIKE ? AND timestamp >= ?",
    (agent_id, f'%{display}%', cutoff),
  ).fetchone()
  cite_count = cite_rows['n'] if cite_rows else 0
  log_conn.close()

  # 건의 채택 수 (status=done) + 등록 수
  filed = 0
  accepted = 0
  try:
    sugg_conn = sqlite3.connect(str(SUGG_DB))
    sugg_conn.row_factory = sqlite3.Row
    filed_row = sugg_conn.execute(
      "SELECT count(*) AS n FROM suggestions WHERE agent_id=? AND created_at >= ?",
      (agent_id, cutoff),
    ).fetchone()
    filed = filed_row['n'] if filed_row else 0
    accepted_row = sugg_conn.execute(
      "SELECT count(*) AS n FROM suggestions WHERE agent_id=? AND status='done' AND created_at >= ?",
      (agent_id, cutoff),
    ).fetchone()
    accepted = accepted_row['n'] if accepted_row else 0
    sugg_conn.close()
  except Exception:
    pass

  total_attempts = speak_count + pass_count
  pass_rate = round(pass_count / total_attempts, 3) if total_attempts > 0 else 0.0
  diversity_ratio = round(len(unique_kw) / max(total_kw_count, 1), 3)
  acceptance_rate = round(accepted / filed, 3) if filed > 0 else 0.0

  return {
    'agent_id': agent_id,
    'display_name': display,
    'period_days': days,
    'speak_count': speak_count,
    'pass_count': pass_count,
    'pass_rate': pass_rate,
    'unique_keywords': len(unique_kw),
    'total_keyword_tokens': total_kw_count,
    'keyword_diversity': diversity_ratio,
    'cite_count': cite_count,
    'suggestions_filed': filed,
    'suggestions_accepted': accepted,
    'acceptance_rate': acceptance_rate,
  }


@router.get('/api/team/persona-drift')
async def get_persona_drift(hours: int = 48) -> dict[str, Any]:
  '''페르소나 드리프트 감사 — 최근 N시간 발화의 일치도 채점.'''
  from improvement.persona_drift import run_persona_drift_audit
  hours = max(1, min(hours, 168))  # 최대 7일
  return await run_persona_drift_audit(hours=hours)


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
