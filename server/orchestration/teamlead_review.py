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
from typing import Any

from config.team import display_name
from log_bus.event_bus import LogEvent
from memory.team_memory import SharedLesson, ProjectSummary
from runners.claude_runner import run_claude_isolated
from runners.gemini_runner import run_gemini

logger = logging.getLogger(__name__)


def _summarize_team_dynamics(office: Any, lookback: int = 100) -> str:
  '''최근 TeamDynamic 기록을 (from→to, type) 카운트로 집계.

  팀장 리뷰 프롬프트에 주입되어 "누가 누구와 잘 맞는지 / stuck 패턴"을
  배치 리뷰가 인지하도록 한다 (P2 메타 학습).
  '''
  try:
    data = office.team_memory._load()
    dynamics = (data.get('dynamics') or [])[-lookback:]
  except Exception:
    return '(집계 데이터 없음)'

  if not dynamics:
    return '(집계 데이터 없음)'

  pair_counts: dict[tuple[str, str, str], int] = {}
  for d in dynamics:
    key = (d.get('from_agent', ''), d.get('to_agent', ''), d.get('dynamic_type', ''))
    pair_counts[key] = pair_counts.get(key, 0) + 1

  ranked = sorted(pair_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
  lines = [f'- {f}→{t} [{dt}] {c}회' for (f, t, dt), c in ranked]

  concern_pairs = [
    (f, t, c) for (f, t, dt), c in pair_counts.items()
    if dt == 'peer_concern' and c >= 2
  ]
  if concern_pairs:
    concern_pairs.sort(key=lambda x: x[2], reverse=True)
    lines.append('')
    lines.append('[주의: 반복적 우려 쌍]')
    lines.extend(f'- {f}→{t}: peer_concern {c}회' for f, t, c in concern_pairs[:3])

  return '\n'.join(lines)


async def run_loop(office: Any) -> None:
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
  if office._review_lock is None:
    office._review_lock = asyncio.Lock()
  office.latest_digest_summary = office._load_digest_state().get('last_summary', '')

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

    # 다짐 follow-up — 배치 리뷰와 별개로 저비용 추적 (DB only, LLM 호출 없음).
    try:
      await run_commitment_followup(office)
    except Exception:
      logger.debug('다짐 follow-up 실패', exc_info=True)

    await asyncio.sleep(300)


async def run_single(office: Any, force: bool = False) -> None:
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
  dynamics_summary = _summarize_team_dynamics(office)
  prompt = (
    f'당신은 팀장 잡스입니다. 아래는 지난 배치 이후 팀의 자발적 대화입니다.\n'
    f'에이전트들은 AI이며 실제 실행 권한이 없습니다. 따라서 말로만 끝나는 발화를\n'
    f'실제 실행 궤적으로 전환하는 것이 팀장의 역할입니다.\n'
    f'**선언형 발언(X하겠습니다/올리겠습니다/건의하겠습니다/반영하겠습니다)은\n'
    f'반드시 `[다짐]` 카테고리로 등록**하고 target_agent를 발화자 본인으로 지정하세요.\n'
    f'"도구가 없어서/템플릿이 없어서/할 수 없어서"처럼 **능력 부족을 드러낸 발화**도\n'
    f'`도구 부족`/`정보 부족` 카테고리로 반드시 등록하세요 (발화자 자가발전의 시작점).\n'
    f'중요: 대화가 결론·실행·진행으로 수렴하지 않은 주제가 있으면, 그 자체를\n'
    f'`프로세스 개선` 건의로 올려 후속 조치가 묻히지 않게 하세요.\n\n'
    f'[팀 협업 패턴 (최근 100건 집계)]\n{dynamics_summary}\n\n'
    f'[대화]\n{convo}\n\n'
    f'JSON만 출력:\n'
    f'{{\n'
    f'  "suggestions":[{{"title":"40자","body":"구체 문제+제안 2-3문장",'
    f'"target_agent":"planner|designer|developer|qa|teamlead|",'
    f'"category":"프로세스 개선|도구 부족|정보 부족|아이디어|다짐",'
    f'"reasoning":"1문장",'
    f'"auto_safe":true|false}}],\n'
    f'  "summary":"2-4문장",\n'
    f'  "dropped":[{{"text":"앞 40자","reason":"이유"}}]\n'
    f'}}\n\n'
    f'auto_safe 판정 기준:\n'
    f'- true: 단순 규칙 추가/명세 작성 가이드/문서화 방식 같이 되돌리기 쉬운 변경\n'
    f'- false: 실제 코드 생성, 다수 에이전트에 영향, 기존 규칙과 충돌 가능, 범위 모호\n'
    f'보수적으로 판정: 조금이라도 의심되면 false. 단 `[다짐]`은 항상 false.\n\n'
    f'규칙: suggestions 최대 5건·중복 금지. 수치 환각 금지. '
    f'추상 방법론 단독 언급(Gherkin/WCAG/KPI)만 있고 구체 맥락이 없으면 건의 아님.'
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
  for s in (data.get('suggestions') or [])[:5]:
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

  # P5-2: 누적 규칙 ↔ 페르소나 충돌 감사 (주 1회 수준)
  from improvement.persona_guard import maybe_run_persona_guard
  await maybe_run_persona_guard(office)

  msg = f'📋 팀장 리뷰 완료{circuit_note}{dryrun_note} — 분석 {len(fresh)}건, 건의 {registered}건 (자동 반영 {auto_applied}건)'
  if summary:
    msg += f'\n요약: {summary[:200]}'
  await office.event_bus.publish(LogEvent(
    agent_id='teamlead', event_type='system_notice', message=msg,
  ))
  logger.info('팀장 리뷰 완료: 분석=%d, 건의=%d, 자동=%d, forced=%s', len(fresh), registered, auto_applied, force)


def stop_loop(office: Any) -> None:
  office._review_running = False


def _build_agent_metrics_context(office: Any, agent_name: str) -> str:
  '''회고 프롬프트에 주입할 에이전트별 실행 컨텍스트. QA/리비전/피드백 요약.'''
  lines = []
  metrics = list(getattr(office, '_phase_metrics', None) or [])
  own = [m for m in metrics if getattr(m, 'agent_name', '') == agent_name]
  if own:
    qa_fails = sum(1 for m in own if not getattr(m, 'qa_passed', True))
    rev = sum(int(getattr(m, 'revision_count', 0) or 0) for m in own)
    total_s = sum(float(getattr(m, 'duration_seconds', 0.0) or 0.0) for m in own)
    lines.append(
      f'- 담당 단계 {len(own)}개 · QA 불합격 {qa_fails}회 · 리비전 {rev}회 · 총 {int(total_s // 60)}분'
    )
  feedback = getattr(office, '_phase_feedback', None) or []
  received = [
    f for f in feedback
    if isinstance(f, dict) and display_name(agent_name) not in (f.get('from') or '')
  ][-3:]
  if received:
    lines.append('- 받은 피드백 (최근):')
    for f in received:
      lines.append(f'  · {f.get("from", "")}[{f.get("phase", "")}]: {(f.get("content") or "")[:80]}')
  return '\n'.join(lines)


async def _peer_lesson_commentary(
  office: Any,
  lesson_pairs: list[tuple[str, str]],
) -> None:
  '''회고 발언 직후, 다른 팀원이 "내 다음 작업에 이렇게 적용" 한 문장 연결.

  유기성 원칙 (memory/feedback_team_organic.md): 각자 교훈이 고립되지 않고
  다음 사람의 행동으로 이어지도록 라운드로빈 커뮤니터리 1회.
  '''
  if len(lesson_pairs) < 2:
    return

  names = [n for n, _ in lesson_pairs]
  lesson_map = dict(lesson_pairs)

  async def _one_comment(owner: str, lesson: str, commenter: str) -> tuple[str, str, str]:
    owner_kr = display_name(owner)
    commenter_kr = display_name(commenter)
    prompt = (
      f'팀원 {owner_kr}의 회고 한 줄: "{lesson}"\n\n'
      f'당신({commenter_kr})의 다음 작업에 이 교훈을 어떻게 적용할지 '
      f'한 문장으로 답하세요.\n'
      f'- 30자 이내, 메신저 톤, 마크다운/서두 인사 금지.\n'
      f'- 구체 행동으로 (예: "다음 초안 제출 전 AC 체크리스트 먼저")'
    )
    try:
      text = await run_claude_isolated(
        prompt, model='claude-haiku-4-5-20251001', timeout=15.0,
      )
      return owner, commenter, (text or '').strip().split('\n')[0][:80]
    except Exception:
      logger.debug('상호 회고 코멘트 실패: %s→%s', commenter, owner, exc_info=True)
      return owner, commenter, ''

  # 라운드로빈 — names[i]의 교훈에 names[(i+1) % n]가 코멘트
  n = len(names)
  tasks = [
    _one_comment(names[i], lesson_map[names[i]], names[(i + 1) % n])
    for i in range(n)
  ]
  comments = await asyncio.gather(*tasks, return_exceptions=False)

  for owner, commenter, text in comments:
    if not text:
      continue
    owner_kr = display_name(owner)
    await office._emit(commenter, f'↳ {owner_kr} 교훈 반영: {text}', 'response')
    try:
      office._record_dynamic(
        from_agent=commenter,
        to_agent=owner,
        dynamic_type='lesson_applied',
        description=text[:100],
      )
    except Exception:
      logger.debug('lesson_applied 기록 실패', exc_info=True)


async def _synthesize_and_save_retrospective(
  office: Any,
  project_title: str,
  project_type: str,
  duration: float,
  user_input: str,
  lessons: list[tuple[str, str]],
) -> None:
  '''팀원 회고 발언을 팀장이 종합해 retrospective.md 아티팩트로 저장.

  유기성 원칙: 팀장이 단순 나열이 아니라 *관통하는 실마리*를 뽑고,
  다음 프로젝트에 적용할 액션 1~2개를 제시.
  '''
  if not lessons:
    return
  lessons_block = '\n'.join(f'- {display_name(n)}: {t}' for n, t in lessons)
  synth_prompt = (
    f'팀원들의 회고 발언을 종합해 회고록을 작성하세요.\n\n'
    f'[프로젝트] {project_title} ({project_type}) · {int(duration // 60)}분 소요\n'
    f'[사용자 지시 요약]\n{user_input[:400]}\n\n'
    f'[팀원 회고]\n{lessons_block}\n\n'
    f'아래 마크다운 형식 그대로, 간결하게. 각 섹션 2~3문장.\n\n'
    f'## 이번 프로젝트 핵심\n'
    f'(프로젝트가 무엇이었고 어떻게 진행되었는지 한 단락)\n\n'
    f'## 관통하는 실마리\n'
    f'(팀원 회고들을 가로지르는 공통 교훈/패턴 1~2개)\n\n'
    f'## 다음 프로젝트에 적용할 액션\n'
    f'(구체적 실행 액션 1~2개, 책임 에이전트 명시)'
  )
  synthesis = ''
  try:
    synthesis = await run_claude_isolated(
      synth_prompt, model='claude-haiku-4-5-20251001', timeout=30.0,
    )
  except Exception:
    logger.debug('회고 종합 생성 실패', exc_info=True)

  header = (
    f'# {project_title} — 팀 회고\n\n'
    f'- 유형: {project_type}\n'
    f'- 소요: {int(duration // 60)}분 {int(duration % 60)}초\n'
    f'- 참여: {", ".join(display_name(n) for n, _ in lessons)}\n\n'
    f'## 팀원별 배운 점\n'
    f'{lessons_block}\n\n'
  )
  body = (synthesis or '').strip() or '_(팀장 종합 생략)_'
  doc = header + body + '\n'

  try:
    office.workspace.write_artifact('retrospective.md', doc)
    logger.info('retrospective.md 저장: %s', project_title)
  except Exception:
    logger.debug('retrospective.md 저장 실패', exc_info=True)

  # 팀장이 종합 요지 한마디 채팅에 공유
  if synthesis:
    first_action = ''
    for line in synthesis.splitlines():
      if '액션' in line or line.strip().startswith('-'):
        first_action = line.strip()[:120]
        break
    if first_action:
      await office._emit('teamlead', f'📘 회고 종합: {first_action}', 'response')


async def run_retrospective(
  office: Any,
  project_title: str,
  project_type: str,
  all_results: dict[str, str],
  user_input: str,
  duration: float,
) -> None:
  '''프로젝트 완료 후 각 에이전트가 배운 점을 팀 메모리에 기록한다.

  각 회고 프롬프트에는 해당 에이전트의 실제 실행 메트릭·피드백을 주입하여
  "30자 한 줄"에 그치지 않고 구체 교훈이 나오도록 유도. 팀장이 회고를
  종합해 `retrospective.md` 아티팩트로 저장한다 — 사람이 읽을 회고록.
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
      metrics_ctx = _build_agent_metrics_context(office, name)
      metrics_section = f'\n[당신의 이번 프로젝트 실행 요약]\n{metrics_ctx}\n' if metrics_ctx else ''
      retro_prompt = (
        f'프로젝트 "{project_title}"이(가) 완료되었습니다.\n'
        f'프로젝트 유형: {project_type}\n'
        f'소요 시간: {int(duration // 60)}분\n'
        f'{metrics_section}\n'
        f'위 실행 요약을 참고해서, 당신({display_name(name)})이 이번 프로젝트에서 배운 점을 한 줄로 공유하세요.\n'
        f'- 실제 겪은 일에 근거한 구체 교훈 (예: "리비전 2회 반복 → 초안에 AC 체크 먼저 해야")\n'
        f'- 30자 이내, 메신저 톤, 마크다운 금지.'
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
  lesson_pairs: list[tuple[str, str]] = []
  for name, lesson_text in results:
    if not lesson_text:
      continue

    # 채팅에 회고 발언 표시
    await office._emit(name, f'💭 {lesson_text}', 'response')
    key_decisions.append(lesson_text)
    lesson_pairs.append((name, lesson_text))

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

  # 팀원 간 상호 코멘트 — 교훈 연결 (유기성 원칙)
  try:
    await _peer_lesson_commentary(office, lesson_pairs)
  except Exception:
    logger.debug('상호 회고 코멘트 실패', exc_info=True)

  # 팀장 종합 → retrospective.md 아티팩트
  try:
    await _synthesize_and_save_retrospective(
      office, project_title, project_type, duration, user_input, lesson_pairs,
    )
  except Exception:
    logger.debug('회고 종합/저장 실패', exc_info=True)

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


# --------------------------------------------------------------------
# 다짐 follow-up — 말·행동 일치 시스템
# --------------------------------------------------------------------

_COMMITMENT_FOLLOWUP_MINUTES = 30  # 다짐 후 이 시간 내 실행 흔적 없으면 재촉
_COMMITMENT_FOLLOWUP_COOLDOWN_HOURS = 24  # 같은 committer 재촉 주기


async def run_commitment_followup(office: Any) -> None:
  '''다짐 후 실행 궤적이 없으면 팀장이 채팅에서 재촉한다.

  원칙(2026-04-15): 채팅 발화가 공허한 외침이 되지 않게,
  "~하겠습니다" 후 N분 내 후속 조치(suggestion 등록/관련 발화)가 없으면
  팀장이 직접 재촉 발화를 생성하고 `followup_nudged` 이벤트를 남긴다.

  저비용 — DB 조회만, LLM 호출 없음.
  '''
  from db.suggestion_store import list_suggestions, list_events, log_event
  from db.log_store import load_logs as _load_logs

  now = datetime.now(timezone.utc)
  cutoff_old = now - timedelta(minutes=_COMMITMENT_FOLLOWUP_MINUTES)
  cutoff_too_old = now - timedelta(hours=6)  # 6시간 넘은 건 재촉 안 함 (소음 방지)

  try:
    all_sugg = list_suggestions(status='')
  except Exception:
    logger.debug('follow-up list_suggestions 실패', exc_info=True)
    return

  # 24h 내 이미 재촉한 committer 집계 (쿨다운)
  recent_nudged: set[str] = set()
  cooldown_cut = now - timedelta(hours=_COMMITMENT_FOLLOWUP_COOLDOWN_HOURS)
  try:
    for ev in list_events(limit=500):
      if ev.get('kind') != 'followup_nudged':
        continue
      try:
        ts = datetime.fromisoformat((ev.get('ts') or '').replace('Z', '+00:00'))
      except Exception:
        continue
      if ts < cooldown_cut:
        continue
      c = (ev.get('payload') or {}).get('committer') or ''
      if c:
        recent_nudged.add(c)
  except Exception:
    logger.debug('follow-up 쿨다운 조회 실패', exc_info=True)

  # 다짐 대상 후보: [다짐]으로 시작하거나 events에 self_commitment 기록된 건
  candidates: list[dict] = []
  for s in all_sugg:
    title = s.get('title') or ''
    if not title.startswith('[다짐]'):
      continue
    try:
      created = datetime.fromisoformat((s.get('created_at') or '').replace('Z', '+00:00'))
    except Exception:
      continue
    if created > cutoff_old or created < cutoff_too_old:
      continue
    candidates.append({'sugg': s, 'created': created})

  if not candidates:
    return

  # 최근 로그로 "실행 흔적" 샘플링 — 해당 committer가 다짐 후 발화에서
  # 구체 수치/파일명/PR/커밋 같은 팔로우업 키워드를 썼는지만 가볍게 확인.
  try:
    recent_logs = _load_logs(limit=200)
  except Exception:
    recent_logs = []

  action_markers = (
    '커밋', 'commit', 'PR', 'pr ', '머지', '반영됨', '등록 완료', '올렸',
    '올림', '배포', 'merged', '처리 완료', '완료했', '완료함', '반영했',
    '추가했', '수정했',
  )

  for cand in candidates:
    s = cand['sugg']
    committer = s.get('agent_id') or ''
    if not committer or committer in recent_nudged:
      continue

    # 이미 follow-up 이벤트가 있으면 스킵
    try:
      evs = list_events(suggestion_id=s['id'], limit=20)
    except Exception:
      evs = []
    if any(e.get('kind') == 'followup_nudged' for e in evs):
      continue

    # 다짐 이후 committer가 실행 흔적을 남겼는지
    executed = False
    for lg in recent_logs:
      if lg.get('agent_id') != committer:
        continue
      try:
        lts = datetime.fromisoformat((lg.get('timestamp') or '').replace('Z', '+00:00'))
      except Exception:
        continue
      if lts <= cand['created']:
        continue
      msg = lg.get('message') or ''
      if any(m in msg for m in action_markers):
        executed = True
        break

    # suggestion 자체가 이미 merged/applied면 실행된 것으로 간주
    status = s.get('status') or ''
    if status in ('merged', 'applied', 'approved'):
      executed = True

    if executed:
      try:
        log_event(s['id'], 'followup_cleared', {'committer': committer})
      except Exception:
        logger.debug('follow-up cleared 기록 실패', exc_info=True)
      continue

    # 재촉 발화
    first_line = (s.get('title') or '').replace('[다짐]', '').strip()[:60]
    nudge = (
      f'@{display_name(committer)} — 앞서 다짐하신 "{first_line}" 건, '
      f'{_COMMITMENT_FOLLOWUP_MINUTES}분이 지났는데 후속 진행이 안 보입니다. '
      f'지금 상태 공유 부탁드립니다 — 실행 중이면 어디까지, 막혔으면 어디서 막혔는지. '
      f'할 수 없는 부분이 있으면 건의게시판에 등록해 주세요.'
    )
    try:
      await office._emit('teamlead', nudge, 'response')
      log_event(s['id'], 'followup_nudged', {
        'committer': committer,
        'nudged_at': now.isoformat(),
      })
      recent_nudged.add(committer)
      logger.info('다짐 follow-up 재촉: %s | %s', committer, first_line[:40])
    except Exception:
      logger.debug('다짐 재촉 실패', exc_info=True)
