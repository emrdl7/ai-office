# 비서 상태 조회 엔드포인트
from typing import Any

from fastapi import APIRouter, Request

from orchestration.office import Office, OfficeState

router = APIRouter()


@router.get('/api/agents')
async def get_agents(request: Request) -> list[dict[str, Any]]:
  '''프론트엔드에는 단일 비서 상태만 노출한다.'''
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

  status = 'working' if is_working else 'idle'
  return [{
    'agent_id': 'teamlead',
    'status': status,
    'model': 'Claude CLI',
    'work_started_at': office._work_started_at if status == 'working' else '',
    'current_phase': office._current_phase if status == 'working' else '',
    'active_project_title': office._active_project_title if active or status == 'working' else '',
  }]


@router.get('/api/agents/quotes')
async def get_daily_quotes() -> dict[str, str]:
  '''비서 오늘의 한마디 반환. 없으면 Haiku로 생성 후 캐싱.'''
  from db.daily_quote_store import get_quotes, save_quotes
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError

  cached = get_quotes()
  if cached.get('teamlead'):
    return {'teamlead': cached['teamlead']}

  prompt = (
    'AI Office 비서가 오늘 업무를 시작하며 남길 짧은 한마디를 만들어 주세요.\n'
    '20자 이내, 한국어, 직접 인용처럼.\n\n'
    '아래 JSON 형식으로만 답하세요 (설명 없이):\n'
    '{"teamlead":"..."}'
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
    if parsed and isinstance(parsed, dict) and parsed.get('teamlead'):
      quotes = {'teamlead': str(parsed['teamlead'])}
      save_quotes(quotes)
      return quotes
  except (ClaudeRunnerError, Exception):
    pass

  fallback = {'teamlead': '필요한 일을 정리하고 바로 실행하겠습니다.'}
  save_quotes(fallback)
  return fallback


@router.get('/api/team')
async def get_team() -> list[dict[str, Any]]:
  '''비서 표시 정보 조회. 내부 실행 역할은 노출하지 않는다.'''
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

  # 다른 에이전트가 인용/멘션한 횟수 — 발화에 본인 이름 등장 (다른 에이전트 발화에서)
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
