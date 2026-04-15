# 건의 CRUD + 감사 이벤트 + auto_triage + auto_merge 파이프라인
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from log_bus.event_bus import LogEvent, event_bus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('/api/suggestions')
async def create_suggestion_api(request: Request):
  '''건의를 등록한다.'''
  from db.suggestion_store import create_suggestion
  body = await request.json()
  result = create_suggestion(
    agent_id=body.get('agent_id', 'user'),
    title=body.get('title', ''),
    content=body.get('content', ''),
    category=body.get('category', 'general'),
  )
  return result


@router.post('/api/suggestions/{suggestion_id}/promote')
async def promote_suggestion_api(suggestion_id: str):
  '''draft 건의를 pending으로 수동 승격하고 auto_triage를 돌린다.'''
  from db.suggestion_store import promote_draft, get_suggestion
  if not promote_draft(suggestion_id):
    current = get_suggestion(suggestion_id)
    if current is None:
      raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다.')
    raise HTTPException(status_code=400, detail=f'draft 상태가 아닙니다 (현재: {current["status"]}).')
  try:
    asyncio.create_task(auto_triage_new_suggestion(suggestion_id))
  except Exception:
    logger.debug('promote 후 auto_triage 호출 실패', exc_info=True)
  return get_suggestion(suggestion_id)


@router.patch('/api/suggestions/{suggestion_id}')
async def update_suggestion_api(suggestion_id: str, request: Request):
  '''건의 상태/답변을 업데이트한다.

  status 값:
    - 'accepted':  승인 — 건의의 suggestion_type에 따라 자동 분기
                   (prompt → TeamMemory/PromptEvolver / code → code_patcher)
    - 'rejected':  반려 — 제안자 AgentMemory에 억제 시그널
    - 기타 문자열: 단순 상태 변경
  '''
  from db.suggestion_store import update_suggestion, get_suggestion
  body = await request.json()
  new_status = body.get('status', '')
  success = update_suggestion(
    suggestion_id,
    status=new_status,
    response=body.get('response', ''),
  )
  if not success:
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')

  suggestion = get_suggestion(suggestion_id)

  if new_status in ('accepted', 'rejected') and suggestion:
    from db.suggestion_store import log_event as _le
    _le(suggestion_id, 'approved' if new_status == 'accepted' else 'rejected', {
      'response': (body.get('response') or '')[:200],
    })

  if new_status == 'accepted' and suggestion:
    stype = suggestion.get('suggestion_type') or 'prompt'
    auto_merge_req = bool(body.get('auto_merge', True))
    if stype == 'code':
      async def _run_patch():
        from improvement.code_patcher import apply_suggestion
        from db.suggestion_store import update_suggestion as _upd
        ok = await apply_suggestion(suggestion)
        if ok:
          _upd(suggestion_id, status='review_pending')
          if auto_merge_req:
            asyncio.create_task(_auto_merge_pipeline(suggestion_id))
        else:
          _upd(suggestion_id, status='pending')
      asyncio.create_task(_run_patch())
    else:
      await _apply_suggestion_to_prompts(suggestion)
      update_suggestion(suggestion_id, status='done')

  elif new_status == 'rejected' and suggestion:
    try:
      from memory.agent_memory import AgentMemory, MemoryRecord
      from datetime import datetime as _dt, timezone as _tz
      reject_reason = (suggestion.get('response') or '').strip()
      reason_suffix = f' — 반려 이유: {reject_reason}' if reject_reason else ''
      AgentMemory(suggestion['agent_id']).record(MemoryRecord(
        task_id=f'suggestion-{suggestion_id}',
        task_type='suggestion_rejected',
        success=False,
        feedback=f'건의 반려됨 — 유사 건의 반복 금지: "{suggestion["title"]}"{reason_suffix}',
        tags=['suggestion_rejected', suggestion.get('category', 'general')],
        timestamp=_dt.now(_tz.utc).isoformat(),
      ))
      if reject_reason:
        from config.team import display_name as _dn
        await event_bus.publish(LogEvent(
          agent_id='teamlead',
          event_type='response',
          message=f'❌ {_dn(suggestion["agent_id"])}의 건의 "{suggestion["title"][:40]}" 반려\n💬 이유: {reject_reason[:200]}',
        ))
    except Exception:
      logger.debug('반려 메모리 기록 실패', exc_info=True)

  return {'success': True}


async def auto_triage_new_suggestion(suggestion_id: str):
  '''새 건의가 등록되면 LLM이 실행 가치를 판정해 자동 accept/reject/hold.

  - accept: code → 자동 패치 + 자동 병합 파이프라인 / prompt|rule → 즉시 auto_apply
  - reject: 명확히 부적절·중복 → 즉시 rejected + 사유
  - hold: 애매하면 pending 유지 (사람 판단)

  Safety:
  - 이미 pending이 아니면 no-op (중복 트리거 방지)
  - 24h 트리거 한도 15건 (폭주 방지)
  - 회로 차단기: 24h 롤백 1+ → hold
  - SUGGESTION_AUTO_TRIAGE_OFF=1 이면 비활성화 (수동 모드)
  '''
  import os as _os
  import asyncio as _a
  import json as _j
  import re as _re
  from datetime import datetime, timezone, timedelta
  from db.suggestion_store import (
    get_suggestion, update_suggestion, log_event, count_rollbacks_since, _conn as _sconn,
  )
  from runners.claude_runner import run_claude_isolated

  if _os.environ.get('SUGGESTION_AUTO_TRIAGE_OFF', '').lower() in ('1', 'true', 'yes'):
    return

  await _a.sleep(1.0)

  s = get_suggestion(suggestion_id)
  if not s or s.get('status') != 'pending':
    return
  # [다짐] / [능력] 접두 건의는 자동 반영 대상 아님 — 실행 추적 전용
  _title = s.get('title') or ''
  if _title.startswith('[다짐]') or _title.startswith('[능력]'):
    log_event(suggestion_id, 'auto_triage_skip', {'reason': 'tracking_only_prefix'})
    return

  cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
  c = _sconn()
  row = c.execute(
    'SELECT COUNT(*) FROM suggestion_events WHERE kind IN (?,?) AND ts>=? AND payload LIKE ?',
    ('auto_triage_accept', 'auto_triage_reject', cutoff, '%'),
  ).fetchone()
  c.close()
  if row and row[0] >= 15:
    log_event(suggestion_id, 'auto_triage_hold', {'reason': 'daily_budget_exhausted'})
    return

  if count_rollbacks_since(hours=24) > 0:
    log_event(suggestion_id, 'auto_triage_hold', {'reason': 'recent_rollback'})
    return

  title = s.get('title', '')
  content = s.get('content', '')[:1200]
  stype = s.get('suggestion_type', 'prompt')
  target = s.get('target_agent', '') or '팀 전체'

  prompt = (
    f'건의가 접수됐습니다. 실행 가치를 보수적으로 판정하세요.\n\n'
    f'[타입] {stype}\n[대상] {target}\n[제목] {title}\n[내용]\n{content}\n\n'
    f'판정 기준:\n'
    f'- accept: 구체·실행 가능하고 범위 명확하며 이미 해결된 주제가 아닐 때\n'
    f'- reject: 추상 방법론만 언급, 이미 반영된 주제의 재탕, 범위 너무 큼, 아키텍처 의사결정 필요, 토론·질문 성격\n'
    f'- hold: 판단이 애매하거나 사람의 추가 맥락이 필요할 때 (보수적 기본값)\n\n'
    f'JSON만 출력: {{"decision":"accept|reject|hold","reason":"1문장"}}'
  )
  decision = 'hold'
  reason = 'LLM 응답 없음'
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=30.0)
    m = _re.search(r'\{[\s\S]*?\}', raw)
    if m:
      d = _j.loads(m.group())
      decision = (d.get('decision') or 'hold').strip()
      reason = (d.get('reason') or '').strip()
  except Exception as e:
    logger.warning('auto_triage LLM 실패: %s', e)
    return

  if decision == 'reject':
    update_suggestion(suggestion_id, status='rejected', response=f'자동 판정 반려: {reason}')
    log_event(suggestion_id, 'auto_triage_reject', {'reason': reason})
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'🚫 자동 반려 #{suggestion_id}: {reason[:150]}',
    ))
    return

  if decision != 'accept':
    log_event(suggestion_id, 'auto_triage_hold', {'reason': reason})
    return

  log_event(suggestion_id, 'auto_triage_accept', {'reason': reason, 'suggestion_type': stype})
  await event_bus.publish(LogEvent(
    agent_id='teamlead', event_type='system_notice',
    message=f'✅ 자동 승인 #{suggestion_id}: {reason[:150]}',
  ))

  if stype in ('prompt', 'rule'):
    from improvement.auto_apply import apply_prompt_or_rule
    ok = await apply_prompt_or_rule(s, user_comment='')
    if ok:
      now_iso = datetime.now(timezone.utc).isoformat()
      cc = _sconn()
      cc.execute(
        'UPDATE suggestions SET status=?, auto_applied=1, auto_applied_at=? WHERE id=?',
        ('done', now_iso, suggestion_id),
      )
      cc.commit(); cc.close()
      log_event(suggestion_id, 'auto_applied', {'via': 'triage', 'target_agent': s.get('target_agent')})
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🤖 자동 반영 #{suggestion_id} — 24h 내 되돌리기 가능',
      ))
  else:
    update_suggestion(suggestion_id, status='accepted')
    log_event(suggestion_id, 'approved', {'via': 'triage'})
    async def _run():
      from improvement.code_patcher import apply_suggestion
      from db.suggestion_store import update_suggestion as _upd
      ok = await apply_suggestion(s)
      if ok:
        _upd(suggestion_id, status='review_pending')
        _a.create_task(_auto_merge_pipeline(suggestion_id))
      else:
        _upd(suggestion_id, status='pending')
    _a.create_task(_run())


async def _auto_merge_pipeline(suggestion_id: str, max_iters: int = 3):
  '''승인 후 Claude 패치가 끝난 상태에서 호출.

  AI 리뷰 → merge/needs_fix/discard 판정에 따라 자동 분기:
  - merge: 자동 병합 (risky/스코프/회로차단기/일일한도 통과 시만)
  - needs_fix: 최대 N회 자동 보완, 중간에 merge 되면 병합
  - discard: 자동 폐기
  - risky/한도 초과/회로차단: review_pending 유지 (수동)
  '''
  import asyncio as _a
  from datetime import datetime, timezone, timedelta
  from db.suggestion_store import (
    get_suggestion, update_suggestion, log_event, count_rollbacks_since, _conn as _sconn,
  )
  from improvement.code_patcher import _PATCH_LOCK, _git, _current_branch, _check_scope
  from routes.suggestion_branch import (
    _run_git, explain_suggestion_branch, _run_one_supplement_iter,
  )

  branch = f'improvement/{suggestion_id}'

  recent_rollbacks = count_rollbacks_since(hours=24)
  if recent_rollbacks > 0:
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'⚠️ 최근 24h 롤백 {recent_rollbacks}건 — 자동 병합 중단, 수동 검토로 전환 (#{suggestion_id})',
    ))
    return

  cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
  c = _sconn()
  row = c.execute(
    'SELECT COUNT(*) FROM suggestion_events WHERE kind=? AND ts>=? AND payload LIKE ?',
    ('branch_merged', cutoff, '%"auto":true%'),
  ).fetchone()
  c.close()
  today_auto = row[0] if row else 0
  if today_auto >= 5:
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'🛑 일일 자동 병합 한도(5/24h) 도달 — 이후는 수동 검토 (#{suggestion_id})',
    ))
    return

  async def _try_merge() -> bool:
    try:
      explain = await explain_suggestion_branch(suggestion_id)
    except Exception as e:
      logger.warning('auto-merge explain 실패: %s', e)
      return False
    if not isinstance(explain, dict) or explain.get('error'):
      return False

    verdict = explain.get('verdict', 'review_needed')
    rec = explain.get('recommendation', 'needs_fix')
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'🤖 자동 파이프라인 판정 #{suggestion_id}: verdict={verdict}, recommend={rec}',
    ))

    if rec == 'discard':
      _git(['branch', '-D', branch])
      update_suggestion(suggestion_id, status='rejected', response='자동 파이프라인 폐기 권장')
      log_event(suggestion_id, 'branch_discarded', {'auto': True, 'verdict': verdict})
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🗑️ 자동 폐기 #{suggestion_id} — {explain.get("recommendation_reason", "")[:150]}',
      ))
      return True

    if rec != 'merge':
      return False
    if verdict == 'risky':
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'⚠️ 자동 병합 중단 #{suggestion_id} — AI가 risky 판정. 수동 검토 필요.',
      ))
      return False

    _, files_out = _run_git(['diff', '--name-only', f'main...{branch}'])
    _, stat_out = _run_git(['diff', '--stat', f'main...{branch}'])
    scope_ok, scope_reason = _check_scope(
      get_suggestion(suggestion_id) or {},
      [f for f in files_out.splitlines() if f], stat_out,
    )
    if not scope_ok:
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🚫 자동 병합 중단 #{suggestion_id} — 스코프 위반: {scope_reason}',
      ))
      return False

    async with _PATCH_LOCK:
      _, cur = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
      if cur.strip() != 'main':
        _run_git(['checkout', 'main'])
      _, tip = _run_git(['rev-parse', branch])
      tip = tip.strip()
      code, out = _run_git(['merge', '--no-ff', '-m', f'merge: improvement/{suggestion_id} (auto)', branch])
      if code != 0:
        _run_git(['merge', '--abort'])
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'❌ 자동 병합 실패 #{suggestion_id}: {out[:200]}',
        ))
        return False
      _run_git(['branch', '-d', branch])
      update_suggestion(suggestion_id, status='done')
      log_event(suggestion_id, 'branch_merged', {'tip': tip, 'auto': True, 'verdict': verdict})

      risks = explain.get('risks') or []
      from db.suggestion_store import create_suggestion
      fu = 0
      for risk in risks[:5]:
        r = (risk or '').strip()
        if len(r) < 15:
          continue
        try:
          create_suggestion(
            agent_id='teamlead',
            title=f'[follow-up #{suggestion_id}] {r[:60]}'[:80],
            content=f'{r}\n\n[자동 파이프라인 — 원 건의 #{suggestion_id} 병합 후 잔존 위험]',
            category='프로세스 개선', target_agent='',
          )
          fu += 1
        except Exception:
          pass
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='response',
        message=(
          f'🔀 자동 병합 완료 #{suggestion_id} → main에 반영됨.'
          + (f'\n🔗 follow-up {fu}건 등록' if fu else '')
          + '\n⚠️ 서버 재시작이 필요합니다 (사이드바 재시작 버튼).'
        ),
      ))
      return True

  if await _try_merge():
    return

  update_suggestion(suggestion_id, status='supplementing')
  import time as _time
  loop_start = _time.monotonic()
  LOOP_BUDGET = 25 * 60
  prev_risks_sig = ''

  try:
    for it in range(1, max_iters + 1):
      if _time.monotonic() - loop_start > LOOP_BUDGET:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'⏱️ [자동] #{suggestion_id} 전체 보완 예산(25분) 초과 — 중단',
        ))
        break

      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🛠️ [자동] 보완 {it}/{max_iters} 시작 #{suggestion_id}',
      ))
      ok, risks_sig = await _run_one_supplement_iter(suggestion_id, branch, it, max_iters)
      if not ok:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'⏹️ [자동] 보완 {it}회 실패 또는 변화 없음 — 루프 종료',
        ))
        break
      if prev_risks_sig and risks_sig == prev_risks_sig:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'🔁 [자동] #{suggestion_id} 위험사항 변화 없음 — 수렴 실패, 중단',
        ))
        break
      prev_risks_sig = risks_sig
      if await _try_merge():
        return
  finally:
    s = get_suggestion(suggestion_id)
    if s and s.get('status') == 'supplementing':
      update_suggestion(suggestion_id, status='review_pending')
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=(
          f'ℹ️ 자동 파이프라인 #{suggestion_id} 종료 — review_pending으로 전환. '
          f'"변경사항 보기"에서 수동 결정 바랍니다.'
        ),
      ))


def _extract_rule_body(content: str) -> str:
  '''자동 등록 건의의 content에서 실제 발언 본문만 추출. 메타 헤더·트리거·카테고리 안내 제거.'''
  import re
  m = re.search(r'의 발언:\s*"([^"]+)"', content)
  if m:
    return m.group(1).strip()
  lines = []
  for line in content.splitlines():
    s = line.strip()
    if not s:
      if lines:
        break
      continue
    if s.startswith('[') or s.startswith('단계:') or s.startswith('카테고리:') or s.startswith('트리거'):
      continue
    lines.append(s)
  return ' '.join(lines)[:400] if lines else content[:300]


async def _apply_suggestion_to_prompts(suggestion: dict) -> None:
  '''프롬프트 수준 반영 — team_memory(전체 공유) + prompt_evolver(제안자 개인 규칙).'''
  from memory.team_memory import TeamMemory, SharedLesson
  from improvement.prompt_evolver import PromptEvolver, PromptRule
  from datetime import datetime, timezone

  sid = suggestion['id']
  agent_id = suggestion['agent_id']
  target_agent = (suggestion.get('target_agent') or '').strip()
  apply_to = target_agent or agent_id
  title = suggestion['title']
  content = suggestion['content']
  category = suggestion.get('category', 'general')
  user_comment = (suggestion.get('response') or '').strip()
  now_iso = datetime.now(timezone.utc).isoformat()
  rule_body = _extract_rule_body(content)
  comment_suffix = f'\n[사용자 코멘트] {user_comment}' if user_comment else ''

  try:
    TeamMemory().add_lesson(SharedLesson(
      id=f'suggestion-{sid}',
      project_title='건의 수용',
      agent_name=apply_to,
      lesson=f'{rule_body}{comment_suffix}',
      category='process_improvement',
      timestamp=now_iso,
    ))
  except Exception:
    logger.debug('TeamMemory add_lesson 실패', exc_info=True)

  try:
    evolver = PromptEvolver()
    existing = evolver.load_rules(apply_to)
    existing.append(PromptRule(
      id=f'suggestion-{sid}',
      created_at=now_iso,
      source='manual',
      category=category,
      rule=f'{rule_body}{comment_suffix}',
      evidence=f'사용자 승인된 건의 #{sid} (제안자: {agent_id})' + (f' — {user_comment[:120]}' if user_comment else ''),
      priority='high',
      active=True,
    ))
    from improvement.prompt_evolver import MAX_RULES_PER_AGENT as _MAX
    active = [r for r in existing if r.active]
    inactive = [r for r in existing if not r.active]
    if len(active) > _MAX:
      sorted_rules = sorted(active, key=lambda r: (r.hit_count, r.created_at))
      for r in sorted_rules[_MAX:]:
        r.active = False
      existing = sorted_rules + inactive
    else:
      existing = active + inactive
    evolver.save_rules(apply_to, existing)
  except Exception:
    logger.debug('PromptEvolver save_rules 실패', exc_info=True)

  from config.team import display_name
  comment_line = f'\n💬 코멘트: {user_comment[:200]}' if user_comment else ''
  target_line = f' ({display_name(apply_to)} 규칙에 적용)' if target_agent else ''
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=(
      f'✅ {display_name(agent_id)}의 건의 "{title[:40]}" 수용{target_line} → '
      f'팀 메모리 + 에이전트 프롬프트에 즉시 반영했습니다.{comment_line}'
    ),
  ))


@router.get('/api/suggestions/{suggestion_id}/events')
async def get_suggestion_events(suggestion_id: str):
  '''건의의 감사 이벤트 시계열.'''
  from db.suggestion_store import list_events
  return list_events(suggestion_id=suggestion_id, limit=200)


@router.get('/api/suggestion-events')
async def get_all_events(limit: int = 200):
  '''전체 감사 이벤트 최신순 (분석용).'''
  from db.suggestion_store import list_events
  return list_events(limit=limit)


@router.delete('/api/suggestions/{suggestion_id}')
async def delete_suggestion_api(suggestion_id: str):
  '''건의를 삭제한다.'''
  from db.suggestion_store import delete_suggestion
  if not delete_suggestion(suggestion_id):
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')
  return {'deleted': suggestion_id}
