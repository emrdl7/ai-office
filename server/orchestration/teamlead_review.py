# 팀장 배치 리뷰 + 프로젝트 회고 — office.py에서 분리 (P1 로드맵 1단계)
#
# 원칙: 행동 변경 금지. self.* → office.* 기계적 치환만.
# Office 클래스의 public 메서드는 forwarder로 유지되어 외부 API(main.py 의존) 보존.
from __future__ import annotations

import asyncio
import logging
import os as _os
import json as _j
import re as _re
from datetime import datetime, timezone, timedelta

from config.team import display_name
from log_bus.event_bus import LogEvent
from memory.team_memory import SharedLesson, ProjectSummary
from runners.claude_runner import run_claude_isolated
from runners.gemini_runner import run_gemini

logger = logging.getLogger(__name__)


async def run_loop(office) -> None:
  '''팀장 역할로 최근 대화를 배치 분석한다.

  트리거: 30분 경과 OR 직전 리뷰 이후 30건 이상 새 메시지.
  동작:
    1) 지난 리뷰 이후 autonomous/response 메시지 수집
    2) Gemini로 구조화 JSON 분석 (suggestions / summary / dropped)
    3) suggestions는 create_suggestion (agent_id='teamlead')
    4) summary는 team_digests.json + office.latest_digest_summary에 저장
    → 이후 start_autonomous_loop 시드가 raw 대신 요약을 참조 (반복 차단)
  '''
  office._review_running = True
  if not hasattr(office, '_review_lock'):
    office._review_lock = asyncio.Lock()
  office.latest_digest_summary: str = office._load_digest_state().get('last_summary', '')

  await asyncio.sleep(60)  # 서버 기동 직후 부담 줄이려 60초 대기

  while office._review_running:
    try:
      # 수동 트리거와 배타 — 한 번에 한 리뷰만
      if office._review_lock.locked():
        await asyncio.sleep(120)
        continue
      async with office._review_lock:
        await run_single(office)
    except Exception:
      logger.debug('팀장 리뷰 루프 에러', exc_info=True)

    await asyncio.sleep(300)


async def run_single(office, force: bool = False) -> None:
  '''배치 리뷰 1회 실행. 락은 호출자가 소유.

  force=True면 트리거 조건 무시. 단 최소 간격(5분)은 유지해 연타 방지.
  '''
  state = office._load_digest_state()
  last_ts = state.get('last_reviewed_ts', '')
  # 실제 리뷰가 돌아간 시각 — last_run_ts가 없으면 history 최근 ts, 그마저 없으면 last_reviewed_ts
  last_run = state.get('last_run_ts')
  if not last_run:
    hist = state.get('history') or []
    last_run = hist[0].get('ts') if hist else last_ts

  # 최소 간격 보호 — force여도 10분 안쪽이면 거절
  min_interval = 600 if force else 7200  # 수동 10분 / 자동 2시간
  if last_run:
    try:
      last_dt = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
      elapsed_run = (datetime.now(timezone.utc) - last_dt).total_seconds()
      if elapsed_run < min_interval:
        logger.info('리뷰 간격 미충족 — %.0fs < %ds (force=%s)', elapsed_run, min_interval, force)
        return
    except Exception:
      pass

  from db.log_store import load_logs as _load
  recent = _load(limit=200)
  fresh = [
    l for l in recent
    if l.get('event_type') in ('autonomous', 'response')
    and l.get('agent_id') != 'system'
    and (not last_ts or l.get('timestamp', '') > last_ts)
  ]
  # 트리거: 30건 이상(force 제외). 아니면 건너뜀 (시간은 위에서 2시간으로 이미 보장됨)
  if not force:
    if len(fresh) < 30:
      return
  if not fresh:
    return

  convo = '\n'.join(
    f'[{l["agent_id"]}] {l["message"][:300]}' for l in reversed(fresh[:120])
  )
  prompt = (
    f'당신은 팀장 잡스입니다. 아래는 지난 배치 이후 팀의 자발적 대화입니다.\n'
    f'에이전트들은 AI이며 실제 실행 권한이 없습니다. 선언형 발언은 신뢰하지 마세요.\n\n'
    f'[대화]\n{convo}\n\n'
    f'JSON만 출력:\n'
    f'{{\n'
    f'  "suggestions":[{{"title":"40자","body":"구체 문제+제안 2-3문장",'
    f'"target_agent":"planner|designer|developer|qa|teamlead|",'
    f'"category":"프로세스 개선|도구 부족|정보 부족|아이디어",'
    f'"reasoning":"1문장",'
    f'"auto_safe":true|false}}],\n'
    f'  "summary":"2-4문장",\n'
    f'  "dropped":[{{"text":"앞 40자","reason":"이유"}}]\n'
    f'}}\n\n'
    f'auto_safe 판정 기준:\n'
    f'- true: 단순 규칙 추가/명세 작성 가이드/문서화 방식 같이 되돌리기 쉬운 변경\n'
    f'- false: 실제 코드 생성, 다수 에이전트에 영향, 기존 규칙과 충돌 가능, 범위 모호\n'
    f'보수적으로 판정: 조금이라도 의심되면 false.\n\n'
    f'규칙: suggestions 최대 3건·중복 금지. 수치 환각 금지. '
    f'추상 방법론 단독 언급(Gherkin/WCAG/KPI)만 있으면 건의 아님.'
  )
  raw = await run_gemini(prompt=prompt)
  m = _re.search(r'\{[\s\S]*\}', raw)
  data = _j.loads(m.group()) if m else None
  if not isinstance(data, dict):
    return

  from db.suggestion_store import (
    create_suggestion, list_suggestions, is_duplicate, log_event,
    count_rollbacks_since, classify_suggestion_type_2stage,
  )
  all_prev = list_suggestions(status='')

  # 24h 자동 반영 한도 계산 (target별 3건 제한)
  cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
  auto_count_by_target: dict[str, int] = {}
  for p in all_prev:
    if int(p.get('auto_applied') or 0) == 1 and (p.get('auto_applied_at') or '') >= cutoff:
      t = (p.get('target_agent') or '').strip() or '(team)'
      auto_count_by_target[t] = auto_count_by_target.get(t, 0) + 1

  # 회로 차단기: 최근 7일 rollback 2건 이상이면 auto_apply 전면 중단
  global_rollback_7d = count_rollbacks_since(hours=168)
  circuit_tripped = global_rollback_7d >= 2
  # dry-run 환경변수
  dry_run = _os.environ.get('SUGGESTION_AUTO_APPLY_DRYRUN', '').lower() in ('1', 'true', 'yes')

  registered = 0
  auto_applied = 0
  for s in (data.get('suggestions') or [])[:3]:
    title = (s.get('title') or '').strip()[:80]
    body = (s.get('body') or '').strip()
    if not title or not body:
      continue
    # 통합 dedup 함수
    dup, reason = is_duplicate(title, body)
    if dup:
      logger.info('리뷰 건의 중복 skip: %s', reason)
      continue
    target = (s.get('target_agent') or '').strip()
    category = (s.get('category') or '아이디어').strip()
    content = (
      f'{body}\n\n[팀장 리뷰 근거]\n{(s.get("reasoning") or "").strip()}\n\n'
      f'(팀장 배치 리뷰 {datetime.now(timezone.utc).isoformat()})'
    )
    try:
      created = create_suggestion(
        agent_id='teamlead', title=title, content=content,
        category=category, target_agent=target,
      )
      # 경계 케이스 2-stage 재분류
      refined_type = await classify_suggestion_type_2stage(title, content, category)
      if refined_type != created.get('suggestion_type'):
        from db.suggestion_store import _conn as _sconn
        _c = _sconn()
        _c.execute('UPDATE suggestions SET suggestion_type=? WHERE id=?', (refined_type, created['id']))
        _c.commit(); _c.close()
        created['suggestion_type'] = refined_type
      log_event(created['id'], 'review_promoted', {
        'target_agent': target, 'category': category,
        'suggestion_type': refined_type, 'auto_safe': bool(s.get('auto_safe')),
      })
      existing_titles.add(title)
      registered += 1

      # 자동 반영 판정
      auto_safe = bool(s.get('auto_safe'))
      stype = refined_type
      bucket = target or '(team)'
      target_rollbacks = count_rollbacks_since(hours=168, target_agent=target) if target else 0
      eligible = (
        auto_safe
        and stype in ('prompt', 'rule')
        and auto_count_by_target.get(bucket, 0) < 3
        and not circuit_tripped
        and target_rollbacks == 0  # 해당 target에 롤백 이력 있으면 차단
      )
      if eligible and dry_run:
        log_event(created['id'], 'auto_apply_dryrun', {'bucket': bucket})
        await office.event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'🧪 [DRYRUN] 자동 반영 후보: "{title[:40]}" → {display_name(target) if target else "팀"} (#{created["id"]})',
        ))
      elif eligible:
        from improvement.auto_apply import apply_prompt_or_rule
        from db.suggestion_store import _conn as _sconn
        ok = await apply_prompt_or_rule(created, user_comment='')
        if ok:
          now_iso = datetime.now(timezone.utc).isoformat()
          c = _sconn()
          c.execute(
            'UPDATE suggestions SET status=?, auto_applied=1, auto_applied_at=? WHERE id=?',
            ('done', now_iso, created['id']),
          )
          c.commit(); c.close()
          auto_count_by_target[bucket] = auto_count_by_target.get(bucket, 0) + 1
          auto_applied += 1
          log_event(created['id'], 'auto_applied', {'target_agent': target, 'bucket': bucket})
          await office.event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=(
              f'🤖 자동 반영: {display_name(target) if target else "팀"} 규칙에 "{title[:40]}" 추가 '
              f'(#{created["id"]}) — 24시간 내 건의게시판에서 되돌리기 가능'
            ),
          ))
      elif circuit_tripped and auto_safe and stype in ('prompt', 'rule'):
        log_event(created['id'], 'circuit_breaker_block', {'rollbacks_7d': global_rollback_7d})
      else:
        # auto_safe가 False이거나 code 타입 → triage에게 맡김
        try:
          from main import auto_triage_new_suggestion
          import asyncio as _a_triage
          _a_triage.create_task(auto_triage_new_suggestion(created['id']))
        except Exception:
          logger.debug('auto_triage 호출 실패', exc_info=True)
    except Exception:
      logger.debug('팀장 리뷰 건의 등록 실패', exc_info=True)

  summary = (data.get('summary') or '').strip()
  now_ts = datetime.now(timezone.utc).isoformat()
  if summary:
    office.latest_digest_summary = summary
    state['last_summary'] = summary
    state.setdefault('history', []).insert(0, {
      'ts': now_ts, 'summary': summary,
      'new_suggestions': registered,
      'dropped': data.get('dropped', [])[:10],
      'forced': force,
    })
    state['history'] = state['history'][:30]
  # load_logs는 오름차순(old→new) 반환이므로 fresh[-1]이 최신
  state['last_reviewed_ts'] = fresh[-1]['timestamp']
  state['last_run_ts'] = now_ts  # 최소 간격 계산용
  office._save_digest_state(state)

  circuit_note = ' ⚠️ 자동반영 일시중단(최근7일 롤백 2건+)' if circuit_tripped else ''
  dryrun_note = ' 🧪 DRYRUN' if dry_run else ''
  # 주기 압축 + 로그 용량 감시 — 하루 1회
  last_compact = state.get('last_compaction_ts', '')
  try:
    if not last_compact or (datetime.now(timezone.utc) - datetime.fromisoformat(last_compact.replace('Z', '+00:00'))) > timedelta(hours=23):
      from improvement.prompt_evolver import PromptEvolver as _PE
      _pe = _PE()
      compact_results = []
      for agent in ['planner', 'designer', 'developer', 'qa', 'teamlead']:
        try:
          r = await _pe.age_and_compress(agent)
          if r.get('dormant_new') or r.get('meta_added'):
            compact_results.append(f'{agent}: dormant+{r["dormant_new"]} meta+{r["meta_added"]} (압축 {r["compressed_from"]}건)')
        except Exception:
          logger.debug('age_and_compress 실패: %s', agent, exc_info=True)
      state['last_compaction_ts'] = datetime.now(timezone.utc).isoformat()
      if compact_results:
        await office.event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message='🧹 에이전트 규칙 주기 정리:\n' + '\n'.join(f'- {r}' for r in compact_results),
        ))

      # 로그 DB 용량 감시 — 임계치 초과 시 알람 (30일+ 1만 건 OR 50MB)
      try:
        from db.log_store import log_storage_stats
        ls = log_storage_stats()
        if ls['old_30d'] > 10000 or ls['db_size_bytes'] > 50 * 1024 * 1024:
          mb = ls['db_size_bytes'] / (1024 * 1024)
          await office.event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=(
              f'💾 채팅 로그 용량 주의 — 총 {ls["total"]}건 / 30일+ {ls["old_30d"]}건 / {mb:.1f}MB.\n'
              f'아카이브·삭제 정책을 검토하세요 (현재 자동 정리 없음).'
            ),
          ))
      except Exception:
        logger.debug('로그 용량 감시 실패', exc_info=True)
  except Exception:
    logger.debug('주기 압축 실패', exc_info=True)

  msg = f'📋 팀장 리뷰 완료{circuit_note}{dryrun_note} — 분석 {len(fresh)}건, 건의 {registered}건 (자동 반영 {auto_applied}건)'
  if summary:
    msg += f'\n요약: {summary[:200]}'
  await office.event_bus.publish(LogEvent(
    agent_id='teamlead', event_type='system_notice', message=msg,
  ))
  logger.info('팀장 리뷰 완료: 분석=%d, 건의=%d, 자동=%d, forced=%s', len(fresh), registered, auto_applied, force)


def stop_loop(office) -> None:
  office._review_running = False


async def run_retrospective(
  office,
  project_title: str,
  project_type: str,
  all_results: dict[str, str],
  user_input: str,
  duration: float,
) -> None:
  '''프로젝트 완료 후 각 에이전트가 배운 점을 팀 메모리에 기록한다.

  채팅에도 회고 발언이 표시되어 "실제 회고 미팅" 느낌을 준다.
  '''
  await office._emit('teamlead', '프로젝트 회고를 진행하겠습니다. 각자 배운 점 한마디씩 해주세요.', 'response')

  # 참여한 에이전트만 회고 (산출물이 있는 에이전트)
  participants = set()
  for phase_name in all_results:
    for agent_name in ('planner', 'designer', 'developer'):
      if agent_name in str(all_results.get(phase_name, '')):
        participants.add(agent_name)
  if not participants:
    participants = {'planner', 'designer', 'developer'}

  async def _one_retro(name: str) -> tuple[str, str]:
    agent = office.agents.get(name)
    if not agent:
      return name, ''
    try:
      system = agent._build_system_prompt()
      retro_prompt = (
        f'프로젝트 "{project_title}"이(가) 완료되었습니다.\n'
        f'프로젝트 유형: {project_type}\n'
        f'소요 시간: {int(duration // 60)}분\n\n'
        f'이번 프로젝트에서 당신({display_name(name)})이 배운 점을 한 줄로 공유하세요.\n'
        f'구체적 교훈이어야 합니다 (예: "IA 설계 시 모바일 우선으로 접근해야 속도가 빠르다").\n'
        f'30자 이내, 메신저 톤, 마크다운 금지.'
      )
      result = await run_claude_isolated(
        f'{system}\n\n---\n\n{retro_prompt}',
        model='claude-haiku-4-5-20251001', timeout=20.0,
      )
      return name, result.strip().split('\n')[0][:80]
    except Exception:
      logger.debug("회고 발언 생성 실패: %s", name, exc_info=True)
      return name, ''

  results = await asyncio.gather(
    *[_one_retro(n) for n in participants],
    return_exceptions=False,
  )

  key_decisions = []
  for name, lesson_text in results:
    if not lesson_text:
      continue

    # 채팅에 회고 발언 표시
    await office._emit(name, f'💭 {lesson_text}', 'response')
    key_decisions.append(lesson_text)

    # 팀 메모리에 교훈 저장
    try:
      office.team_memory.add_lesson(SharedLesson(
        id=f'{project_title}-{name}-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M")}',
        project_title=project_title,
        agent_name=name,
        lesson=lesson_text,
        category='process_improvement',
        timestamp=datetime.now(timezone.utc).isoformat(),
      ))
    except Exception:
      logger.debug("팀 교훈 저장 실패: %s", name, exc_info=True)

  # 팀장 마무리 한마디
  await office._emit('teamlead', '좋은 회고였습니다. 다음 프로젝트에 반영하겠습니다. 수고하셨습니다 👏', 'response')

  # 프로젝트 요약 저장
  try:
    office.team_memory.add_project_summary(ProjectSummary(
      project_id=office._active_project_id or '',
      title=project_title,
      project_type=project_type,
      outcome='success',
      key_decisions=key_decisions[:5],
      duration_seconds=duration,
      timestamp=datetime.now(timezone.utc).isoformat(),
    ))
  except Exception:
    logger.debug("프로젝트 요약 저장 실패", exc_info=True)
