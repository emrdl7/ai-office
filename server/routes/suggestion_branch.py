# 자가개선 브랜치 검토/병합/보완/폐기 엔드포인트
import logging

from fastapi import APIRouter, HTTPException, Request

from log_bus.event_bus import LogEvent, event_bus

router = APIRouter()
logger = logging.getLogger(__name__)

_BRANCH_EXPLAIN_CACHE: dict[str, dict] = {}


def _run_git(args: list[str]) -> tuple[int, str]:
  import subprocess
  from pathlib import Path
  root = Path(__file__).resolve().parent.parent.parent
  r = subprocess.run(['git'] + args, cwd=str(root), capture_output=True, text=True)
  return r.returncode, (r.stdout + r.stderr).strip()


@router.get('/api/suggestions/{suggestion_id}/branch')
async def get_suggestion_branch_diff(suggestion_id: str):
  '''improvement/{id} 브랜치의 diff + 파일 목록을 반환.'''
  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')
  _, files = _run_git(['diff', '--name-only', f'main...{branch}'])
  _, stat = _run_git(['diff', '--stat', f'main...{branch}'])
  _, patch = _run_git(['diff', f'main...{branch}'])
  return {
    'branch': branch,
    'files': files.splitlines() if files else [],
    'stat': stat,
    'diff': patch[:80000],
  }


@router.get('/api/suggestions/{suggestion_id}/branch/explain')
async def explain_suggestion_branch(suggestion_id: str):
  '''변경사항의 의도·효과·위험을 AI로 분석해 반환 (커밋 해시 기준 캐시).'''
  from db.suggestion_store import get_suggestion
  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')
  _, tip = _run_git(['rev-parse', branch])
  tip = tip.strip()
  cached = _BRANCH_EXPLAIN_CACHE.get(tip)
  if cached:
    return cached

  _, stat = _run_git(['diff', '--stat', f'main...{branch}'])
  _, patch = _run_git(['diff', f'main...{branch}'])
  _, log = _run_git(['log', f'main..{branch}', '--pretty=%s%n%b', '-n', '3'])
  suggestion = get_suggestion(suggestion_id) or {}

  from runners.gemini_runner import run_gemini
  from runners.claude_runner import run_claude_isolated
  import json as _j, re as _re

  prompt = (
    f'당신은 시니어 엔지니어 리뷰어입니다. 아래 변경사항을 분석해 JSON만 출력하세요.\n\n'
    f'[원 건의]\n'
    f'제목: {suggestion.get("title", "(미상)")}\n'
    f'내용: {suggestion.get("content", "")[:800]}\n\n'
    f'[커밋 메시지]\n{log[:600]}\n\n'
    f'[변경 통계]\n{stat}\n\n'
    f'[패치]\n{patch[:30000]}\n\n'
    f'출력 스키마:\n'
    f'{{\n'
    f'  "intent": "이 변경의 의도 (건의를 어떻게 해석해서 무엇을 고쳤는지) 2-3문장",\n'
    f'  "effects": ["기대 효과 1", "기대 효과 2"],\n'
    f'  "risks": ["위험/주의점 1", "위험/주의점 2"],\n'
    f'  "verdict": "merge_safe|review_needed|risky",\n'
    f'  "verdict_reason": "판단 근거 한 문장",\n'
    f'  "recommendation": "merge|discard|needs_fix",\n'
    f'  "recommendation_reason": "왜 그 행동을 권장하는지 2-3문장 (구체 이유)"\n'
    f'}}\n'
    f'규칙:\n'
    f'- 의도/효과/위험은 구체적으로. 일반론 금지.\n'
    f'- 실제 수정된 함수·파일·동작 변화를 근거로 작성.\n'
    f'- 위험이 없어 보여도 최소 1개는 찾아서 기술 (테스트 누락/엣지 케이스/되돌리기 어려움 등).\n'
    f'- verdict는 엄격하게: 어지간하면 review_needed.\n'
    f'- recommendation:\n'
    f'  · merge: 의도대로 잘 구현됐고 위험이 경미해 바로 병합해도 OK\n'
    f'  · needs_fix: 방향은 맞지만 수정·보완 필요 (폐기하고 재시도 또는 수동 보강)\n'
    f'  · discard: 건의 의도와 다르거나 잘못 구현돼 버리는 게 맞음\n'
    f'- recommendation_reason은 사용자가 결정할 때 참고할 수 있도록 실질적으로 작성.'
  )
  data = None
  last_err = ''
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=90.0)
    m = _re.search(r'\{[\s\S]*\}', raw)
    if m:
      data = _j.loads(m.group())
  except Exception as e:
    last_err = f'claude: {type(e).__name__}: {str(e)[:120]}'
    logger.warning('Claude explain 실패 → Gemini 폴백: %s', last_err)

  if not isinstance(data, dict):
    try:
      raw = await run_gemini(prompt=prompt, timeout=120.0)
      m = _re.search(r'\{[\s\S]*\}', raw)
      if m:
        data = _j.loads(m.group())
    except Exception as e:
      last_err = last_err + f' | gemini: {type(e).__name__}: {str(e)[:120]}'
      logger.warning('Gemini explain 실패: %s', last_err)

  if not isinstance(data, dict):
    return {'error': f'AI 분석 실패 — {last_err or "응답 없음"}'}

  from db.suggestion_store import list_events as _list_ev
  supplement_count = sum(1 for ev in _list_ev(suggestion_id=suggestion_id, limit=50) if ev.get('kind') == 'branch_supplemented')

  result = {
    'intent': (data.get('intent') or '').strip(),
    'effects': [str(x).strip() for x in (data.get('effects') or []) if x],
    'risks': [str(x).strip() for x in (data.get('risks') or []) if x],
    'verdict': data.get('verdict', 'review_needed'),
    'verdict_reason': (data.get('verdict_reason') or '').strip(),
    'recommendation': data.get('recommendation', 'needs_fix'),
    'recommendation_reason': (data.get('recommendation_reason') or '').strip(),
    'supplement_count': supplement_count,
    'commit': tip,
  }
  _BRANCH_EXPLAIN_CACHE[tip] = result
  return result


@router.post('/api/suggestions/{suggestion_id}/branch/merge')
async def merge_suggestion_branch(suggestion_id: str, request: Request):
  '''improvement/{id}를 현재 브랜치(main)로 병합 + 상태 done + 위험 follow-up 자동 등록.

  게이트:
  - AI 리뷰 verdict='risky'면 409 (쿼리 ?confirm_risky=true로 우회)
  - pytest/ruff 체크 (쿼리 ?skip_tests=true로 생략 가능)
  '''
  import asyncio
  from db.suggestion_store import update_suggestion, get_suggestion, create_suggestion, log_event
  confirm_risky = request.query_params.get('confirm_risky') == 'true'
  run_tests = request.query_params.get('run_tests') == 'true'
  skip_tests = not run_tests

  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')
  _, cur = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
  if cur.strip() != 'main':
    raise HTTPException(status_code=409, detail=f'현재 브랜치가 main이 아닙니다: {cur}')

  _, tip = _run_git(['rev-parse', branch])
  tip = tip.strip()

  explain_cache = _BRANCH_EXPLAIN_CACHE.get(tip)
  if explain_cache and explain_cache.get('verdict') == 'risky' and not confirm_risky:
    raise HTTPException(
      status_code=409,
      detail='RISKY_UNCONFIRMED: AI 리뷰가 위험으로 판정했습니다. ?confirm_risky=true로 강제하세요.',
    )

  from improvement.code_patcher import _check_scope
  suggestion_full = get_suggestion(suggestion_id) or {}
  _, files_out = _run_git(['diff', '--name-only', f'main...{branch}'])
  _, stat_out = _run_git(['diff', '--stat', f'main...{branch}'])
  scope_ok, scope_reason = _check_scope(suggestion_full, [f for f in files_out.splitlines() if f], stat_out)
  if not scope_ok and not confirm_risky:
    raise HTTPException(
      status_code=409,
      detail=f'SCOPE_VIOLATION: {scope_reason}. 확인 후 ?confirm_risky=true로 강제하거나 폐기하세요.',
    )

  if not skip_tests:
    import asyncio as _a
    import subprocess as _sp

    async def _check(cmd: list[str], cwd: str) -> tuple[int, str]:
      proc = await _a.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=_sp.PIPE, stderr=_sp.STDOUT,
      )
      try:
        out, _ = await _a.wait_for(proc.communicate(), timeout=300)
      except _a.TimeoutError:
        proc.kill()
        return (124, 'timeout')
      return (proc.returncode, (out or b'').decode(errors='ignore')[-3000:])

    from pathlib import Path as _P
    import tempfile as _tf
    tmpdir = _tf.mkdtemp(prefix='improvement-wt-')
    _, wt_out = _run_git(['worktree', 'add', '--detach', tmpdir, branch])
    try:
      wt_server = str(_P(tmpdir) / 'server')
      rc_lint, out_lint = await _check(['uv', 'run', 'ruff', 'check', '.'], wt_server)
      rc_test, out_test = (0, 'skipped')
      if (_P(wt_server) / 'tests').exists():
        rc_test, out_test = await _check(['uv', 'run', 'pytest', '-x', '-q'], wt_server)
      if rc_lint != 0 or rc_test != 0:
        log_event(suggestion_id, 'test_failed', {
          'lint_rc': rc_lint, 'test_rc': rc_test,
          'lint_tail': out_lint[-500:], 'test_tail': out_test[-500:],
        })
        update_suggestion(
          suggestion_id,
          response=f'테스트/린트 실패 — lint_rc={rc_lint}, test_rc={rc_test}',
        )
        raise HTTPException(
          status_code=409,
          detail=f'TEST_FAILED: lint_rc={rc_lint}, test_rc={rc_test}. 확인 후 수정하거나 ?skip_tests=true로 우회.',
        )
    finally:
      _run_git(['worktree', 'remove', '--force', tmpdir])

  code, out = _run_git(['merge', '--no-ff', '-m', f'merge: improvement/{suggestion_id}', branch])
  if code != 0:
    _run_git(['merge', '--abort'])
    raise HTTPException(status_code=500, detail=f'병합 실패 — 수동 확인 필요: {out[:300]}')
  _run_git(['branch', '-d', branch])
  update_suggestion(suggestion_id, status='done')
  suggestion = get_suggestion(suggestion_id)
  log_event(suggestion_id, 'branch_merged', {'tip': tip})

  follow_ups = 0
  explain = _BRANCH_EXPLAIN_CACHE.get(tip)
  if explain and isinstance(explain.get('risks'), list):
    from routes.suggestions import auto_triage_new_suggestion
    for risk in explain['risks'][:5]:
      risk = (risk or '').strip()
      if not risk or len(risk) < 15:
        continue
      try:
        title = f'[follow-up #{suggestion_id}] {risk[:60]}'
        content = (
          f'{risk}\n\n'
          f'[후속 조치 필요 — 자동 등록]\n'
          f'원 건의: #{suggestion_id} "{(suggestion or {}).get("title", "")[:60]}"\n'
          f'AI 리뷰 판정: {explain.get("verdict", "review_needed")}\n'
          f'근거: {explain.get("verdict_reason", "")}\n'
        )
        fu_created = create_suggestion(
          agent_id='teamlead', title=title[:80], content=content,
          category='프로세스 개선', target_agent='',
        )
        follow_ups += 1
        asyncio.create_task(auto_triage_new_suggestion(fu_created['id']))
      except Exception:
        logger.debug('follow-up 등록 실패', exc_info=True)

  followup_line = f'\n🔗 후속 조치 {follow_ups}건 자동 등록됨 (건의게시판 확인)' if follow_ups else ''
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=(
      f'🔀 건의 #{suggestion_id} 브랜치 병합 완료 → main에 반영됐습니다.{followup_line}\n'
      f'⚠️ 서버 재시작이 필요합니다 (Python 모듈 재로딩).'
    ),
  ))
  return {'merged': True, 'suggestion_id': suggestion_id, 'follow_ups': follow_ups}


@router.post('/api/suggestions/{suggestion_id}/rollback')
async def rollback_auto_applied(suggestion_id: str):
  '''자동 반영된 건의를 되돌린다 — 24시간 유예 내에서만 가능.'''
  from db.suggestion_store import get_suggestion, update_suggestion, _conn as _sconn
  from improvement.auto_apply import rollback_prompt_or_rule
  from datetime import datetime, timezone, timedelta
  suggestion = get_suggestion(suggestion_id)
  if not suggestion:
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')
  if int(suggestion.get('auto_applied') or 0) != 1:
    raise HTTPException(status_code=400, detail='자동 반영된 건의만 롤백 가능합니다')
  applied_at = suggestion.get('auto_applied_at') or ''
  try:
    applied_dt = datetime.fromisoformat(applied_at.replace('Z', '+00:00'))
    if datetime.now(timezone.utc) - applied_dt > timedelta(hours=24):
      raise HTTPException(status_code=410, detail='24시간 롤백 유예 기간이 지났습니다')
  except HTTPException:
    raise
  except Exception:
    raise HTTPException(status_code=400, detail='반영 시각 파싱 실패')

  removed = rollback_prompt_or_rule(suggestion_id)
  c = _sconn()
  c.execute(
    "UPDATE suggestions SET status='rejected', auto_applied=0, response=? WHERE id=?",
    ('자동 반영 롤백 (사용자 되돌리기)', suggestion_id),
  )
  c.commit(); c.close()
  from db.suggestion_store import log_event as _logev
  _logev(suggestion_id, 'rollback', {
    'target_agent': suggestion.get('target_agent') or '',
    'removed_rules': removed.get('rules', 0),
    'removed_lessons': removed.get('lessons', 0),
  })
  await event_bus.publish(LogEvent(
    agent_id='teamlead', event_type='system_notice',
    message=(
      f'↩️ 자동 반영 롤백: #{suggestion_id} "{suggestion["title"][:40]}" '
      f'— 규칙 {removed["rules"]}건 · 교훈 {removed["lessons"]}건 제거'
    ),
  ))
  return {'rolled_back': True, 'removed': removed}


@router.post('/api/suggestions/{suggestion_id}/branch/supplement')
async def supplement_suggestion_branch(suggestion_id: str, request: Request):
  '''improvement/{id} 브랜치에 Claude를 최대 max_iterations 반복 실행해 보완.'''
  import asyncio
  from db.suggestion_store import get_suggestion, log_event, update_suggestion
  from improvement.code_patcher import _PATCH_LOCK, _git, _current_branch
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError
  body = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
  extra_instruction = (body.get('instruction') or '').strip()
  try:
    max_iters = int(body.get('max_iterations') or 3)
  except Exception:
    max_iters = 3
  max_iters = max(1, min(max_iters, 5))

  branch = f'improvement/{suggestion_id}'
  code, _ = _run_git(['rev-parse', '--verify', branch])
  if code != 0:
    raise HTTPException(status_code=404, detail='브랜치가 존재하지 않습니다')

  if _PATCH_LOCK.locked():
    raise HTTPException(status_code=409, detail='다른 코드 패치 진행 중 — 완료 후 재시도')

  async def _run():
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent.parent
    async with _PATCH_LOCK:
      update_suggestion(suggestion_id, status='supplementing')
      suggestion = get_suggestion(suggestion_id) or {}
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🛠️ 건의 #{suggestion_id} 보완 시작 — 최대 {max_iters}회 반복',
      ))
      original_branch = _current_branch()

      success_iters = 0
      final_verdict = 'needs_fix'
      prev_risks_sig = ''
      import time as _time
      loop_start = _time.monotonic()
      LOOP_BUDGET_SEC = 25 * 60

      for it in range(1, max_iters + 1):
        if _time.monotonic() - loop_start > LOOP_BUDGET_SEC:
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'⏱️ [{it}/{max_iters}] 전체 보완 예산(25분) 초과 — 루프 중단',
          ))
          break
        _, cur_tip = _run_git(['rev-parse', branch])
        cur_tip = cur_tip.strip()
        explain = _BRANCH_EXPLAIN_CACHE.get(cur_tip) or {}
        risks = explain.get('risks') or []
        prev_intent = explain.get('intent', '')

        rc, out = _git(['checkout', branch])
        if rc != 0:
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'❌ [{it}/{max_iters}] 보완 중단 — 체크아웃 오류: {out[:200]}',
          ))
          break

        prompt = (
          f'# AI Office 자가개선 — 보완 반복 {it}/{max_iters}\n\n'
          f'프로젝트 루트: {root}\n\n'
          f'## 원 건의 #{suggestion_id}\n'
          f'제목: {suggestion.get("title", "")}\n'
          f'내용: {suggestion.get("content", "")[:1500]}\n\n'
          f'## 이전 구현 요약\n{prev_intent or "(없음)"}\n\n'
          f'## 보완해야 할 위험·부족분 (AI 리뷰)\n'
          + ('\n'.join(f'- {r}' for r in risks) if risks else '(없음)')
          + (f'\n\n## 사용자 추가 지시 (초기)\n{extra_instruction}' if extra_instruction and it == 1 else '')
          + (
            f'\n\n## 작업 지침\n'
            f'- 이미 브랜치에 구현이 있다. 덮어쓰지 말고 **추가·보완**.\n'
            f'- 위 위험·부족분을 우선 해결. 범위 벗어난 건 건드리지 마라.\n'
            f'- 기존 스타일 유지. 변경 파일·이유 마지막에 요약.'
          )
        )

        try:
          result = await run_claude_isolated(prompt=prompt, timeout=600.0, max_turns=20)
        except ClaudeRunnerError as e:
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'❌ [{it}/{max_iters}] Claude 오류: {e}',
          ))
          break

        _, changed = _git(['diff', '--name-only', 'HEAD'])
        _, untracked = _git(['ls-files', '--others', '--exclude-standard'])
        if not (changed.strip() or untracked.strip()):
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'ℹ️ [{it}/{max_iters}] 추가 변경 없음 — 루프 종료',
          ))
          break

        _git(['add', '-A'])
        _git(['commit', '-m', f'supplement(#{suggestion_id}): iter {it}/{max_iters} — AI 리뷰 위험 보완'])
        _, new_tip = _run_git(['rev-parse', branch])
        new_tip = new_tip.strip()
        _BRANCH_EXPLAIN_CACHE.pop(cur_tip, None)
        log_event(suggestion_id, 'branch_supplemented', {
          'iter': it, 'old_tip': cur_tip, 'new_tip': new_tip,
        })
        success_iters += 1

        _git(['checkout', original_branch])
        try:
          new_explain = await _compute_branch_explain(suggestion_id, branch)
          final_verdict = new_explain.get('recommendation', 'needs_fix')
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=(
              f'🛠️ [{it}/{max_iters}] 보완 커밋 완료 — AI 판단: {final_verdict}\n'
              f'Claude 요약: {result[:200]}'
            ),
          ))
          if final_verdict in ('merge', 'discard'):
            break
          new_risks = new_explain.get('risks') or []
          sig = '|'.join(sorted(r[:60] for r in new_risks))
          if prev_risks_sig and sig == prev_risks_sig:
            await event_bus.publish(LogEvent(
              agent_id='teamlead', event_type='system_notice',
              message=f'🔁 [{it}/{max_iters}] 위험사항이 변하지 않음 — 수렴 실패로 중단. 수동 확인 권장.',
            ))
            break
          prev_risks_sig = sig
        except Exception as e:
          logger.warning('보완 루프 explain 실패: %s', e)
          await event_bus.publish(LogEvent(
            agent_id='teamlead', event_type='system_notice',
            message=f'⚠️ [{it}/{max_iters}] AI 리뷰 생성 실패 — 루프 중단. 수동 확인 필요.',
          ))
          break

      update_suggestion(suggestion_id, status='review_pending')
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=(
          f'✅ 건의 #{suggestion_id} 보완 종료 — 총 {success_iters}회 커밋, 최종 판단={final_verdict}. '
          f'"변경사항 보기"에서 확인하세요.'
        ),
      ))

  asyncio.create_task(_run())
  return {'queued': True, 'max_iterations': max_iters, 'message': f'최대 {max_iters}회 반복 보완 대기열 투입'}


async def _compute_branch_explain(suggestion_id: str, branch: str) -> dict:
  '''보완 루프 내부에서 explain 로직 재사용 — 캐시에 저장하고 반환.'''
  from db.suggestion_store import get_suggestion
  from runners.gemini_runner import run_gemini
  from runners.claude_runner import run_claude_isolated
  import json as _j, re as _re
  _, stat = _run_git(['diff', '--stat', f'main...{branch}'])
  _, patch = _run_git(['diff', f'main...{branch}'])
  _, log = _run_git(['log', f'main..{branch}', '--pretty=%s%n%b', '-n', '5'])
  suggestion = get_suggestion(suggestion_id) or {}
  prompt = (
    f'당신은 시니어 엔지니어 리뷰어입니다. 변경사항을 분석해 JSON만 출력하세요.\n\n'
    f'[원 건의]\n제목: {suggestion.get("title", "")}\n내용: {suggestion.get("content", "")[:800]}\n\n'
    f'[커밋 메시지]\n{log[:600]}\n\n[변경 통계]\n{stat}\n\n[패치]\n{patch[:30000]}\n\n'
    f'스키마: {{"intent":"2-3문장","effects":["..."],"risks":["..."],"verdict":"merge_safe|review_needed|risky",'
    f'"verdict_reason":"...","recommendation":"merge|discard|needs_fix","recommendation_reason":"..."}}\n'
    f'규칙: 구체적으로, 위험 최소 1개, verdict는 엄격하게.'
  )
  data = None
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=90.0)
    m = _re.search(r'\{[\s\S]*\}', raw)
    if m: data = _j.loads(m.group())
  except Exception:
    try:
      raw = await run_gemini(prompt=prompt, timeout=120.0)
      m = _re.search(r'\{[\s\S]*\}', raw)
      if m: data = _j.loads(m.group())
    except Exception:
      pass
  if not isinstance(data, dict):
    return {}
  _, tip = _run_git(['rev-parse', branch])
  tip = tip.strip()
  from db.suggestion_store import list_events as _list_ev
  supplement_count = sum(1 for ev in _list_ev(suggestion_id=suggestion_id, limit=50) if ev.get('kind') == 'branch_supplemented')

  result = {
    'intent': (data.get('intent') or '').strip(),
    'effects': [str(x).strip() for x in (data.get('effects') or []) if x],
    'risks': [str(x).strip() for x in (data.get('risks') or []) if x],
    'verdict': data.get('verdict', 'review_needed'),
    'verdict_reason': (data.get('verdict_reason') or '').strip(),
    'recommendation': data.get('recommendation', 'needs_fix'),
    'recommendation_reason': (data.get('recommendation_reason') or '').strip(),
    'supplement_count': supplement_count,
    'commit': tip,
  }
  _BRANCH_EXPLAIN_CACHE[tip] = result
  return result


async def _run_one_supplement_iter(suggestion_id: str, branch: str, it: int, max_iters: int) -> tuple[bool, str]:
  '''supplement 1회 실행. (성공, risks_signature) 반환.'''
  from db.suggestion_store import get_suggestion, log_event
  from improvement.code_patcher import _PATCH_LOCK, _git, _current_branch, _check_scope
  from runners.claude_runner import run_claude_isolated, ClaudeRunnerError
  from pathlib import Path as _P

  async with _PATCH_LOCK:
    suggestion = get_suggestion(suggestion_id) or {}
    _, cur_tip = _run_git(['rev-parse', branch])
    cur_tip = cur_tip.strip()
    explain = _BRANCH_EXPLAIN_CACHE.get(cur_tip) or {}
    risks = explain.get('risks') or []
    prev_intent = explain.get('intent', '')

    original_branch = _current_branch()
    rc, out = _git(['checkout', branch])
    if rc != 0:
      return (False, '')

    prompt = (
      f'# AI Office 자가개선 — 자동 보완 반복 {it}/{max_iters}\n\n'
      f'프로젝트 루트: {_P(__file__).resolve().parent.parent.parent}\n\n'
      f'## 원 건의 #{suggestion_id}\n'
      f'제목: {suggestion.get("title", "")}\n내용: {suggestion.get("content", "")[:1500]}\n\n'
      f'## 이전 구현 요약\n{prev_intent or "(없음)"}\n\n'
      f'## 보완해야 할 위험·부족분\n'
      + ('\n'.join(f'- {r}' for r in risks) if risks else '(없음)')
      + f'\n\n## 작업 지침\n'
      f'- 기존 구현에 **추가·보완**만. 덮어쓰지 마라.\n'
      f'- 위 위험·부족분만 해결. 범위 벗어난 건 건드리지 마라.\n'
      f'- 스코프 제약(금지 파일·15파일 500줄 한도) 엄격 준수.\n'
      f'- 변경 파일·이유 요약.'
    )
    try:
      await run_claude_isolated(prompt=prompt, timeout=600.0, max_turns=20)
    except ClaudeRunnerError as e:
      _git(['checkout', original_branch])
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'❌ [자동 {it}/{max_iters}] Claude 오류: {e}',
      ))
      return (False, '')

    _, changed = _git(['diff', '--name-only', 'HEAD'])
    _, untracked = _git(['ls-files', '--others', '--exclude-standard'])
    if not (changed.strip() or untracked.strip()):
      _git(['checkout', original_branch])
      return (False, '')

    file_list = [f for f in changed.strip().splitlines() if f]
    _, stat_out = _git(['diff', '--stat', 'HEAD'])
    scope_ok, scope_reason = _check_scope(suggestion, file_list, stat_out)
    if not scope_ok:
      _git(['checkout', '.'])
      _git(['checkout', original_branch])
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice',
        message=f'🚫 [자동 {it}/{max_iters}] 스코프 위반으로 iter 폐기: {scope_reason}',
      ))
      return (False, '')

    _git(['add', '-A'])
    _git(['commit', '-m', f'supplement(#{suggestion_id}): auto iter {it}/{max_iters}'])
    _, new_tip = _run_git(['rev-parse', branch])
    new_tip = new_tip.strip()
    _BRANCH_EXPLAIN_CACHE.pop(cur_tip, None)
    log_event(suggestion_id, 'branch_supplemented', {
      'iter': it, 'old_tip': cur_tip, 'new_tip': new_tip, 'auto': True,
    })
    _git(['checkout', original_branch])

  try:
    new_explain = await explain_suggestion_branch(suggestion_id)
  except Exception:
    return (True, '')
  new_risks = (new_explain or {}).get('risks') or []
  sig = '|'.join(sorted((r or '')[:60] for r in new_risks))
  return (True, sig)


@router.post('/api/suggestions/{suggestion_id}/branch/discard')
async def discard_suggestion_branch(suggestion_id: str):
  '''improvement/{id} 브랜치를 폐기하고 건의를 rejected로.'''
  from db.suggestion_store import update_suggestion, log_event
  branch = f'improvement/{suggestion_id}'
  _run_git(['branch', '-D', branch])
  update_suggestion(suggestion_id, status='rejected', response='브랜치 폐기')
  log_event(suggestion_id, 'branch_discarded', {})
  await event_bus.publish(LogEvent(
    agent_id='teamlead',
    event_type='response',
    message=f'🗑️ 건의 #{suggestion_id} 브랜치 폐기 — 변경사항 반영되지 않았습니다.',
  ))
  return {'discarded': True}
