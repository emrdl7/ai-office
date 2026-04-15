# FastAPI 오케스트레이션 서버 진입점
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bus.message_bus import MessageBus
from log_bus.event_bus import EventBus, LogEvent, event_bus
from orchestration.office import Office, OfficeState
from orchestration.router import MessageRouter
from orchestration.task_graph import TaskGraph
from workspace.manager import WorkspaceManager
from db.task_store import save_task, update_task_state, list_tasks, get_task

import logging
logger = logging.getLogger(__name__)

# WebSocket 인증 토큰 (환경변수 또는 서버 시작 시 자동 생성)
WS_AUTH_TOKEN = os.environ.get('WS_AUTH_TOKEN') or secrets.token_urlsafe(32)

# REST API 인증 토큰 (선택) — 설정 시 /api/* 경로가 Bearer 또는 ?token=로 보호됨
# 로컬 단독 실행 시 비워두면 현재 동작 유지(CORS로 외부 차단).
# 외부 노출(원격/프록시 뒤) 시 반드시 설정할 것.
REST_AUTH_TOKEN = os.environ.get('REST_AUTH_TOKEN', '').strip()

# 인증 면제 경로 — 헬스체크만 (ws-token은 보호하여 token 탈취 방지)
_AUTH_EXEMPT_PATHS = {'/health'}

# 파일 업로드 제한
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',  # 이미지
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',  # 문서
  '.txt', '.md', '.csv', '.json', '.yaml', '.yml',  # 텍스트/데이터
  '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css',  # 코드
  '.zip', '.tar', '.gz',  # 압축
}

# 데이터 디렉토리 생성 (MessageBus SQLite 파일용)
Path('data').mkdir(exist_ok=True)

# 싱글턴 인스턴스
message_bus = MessageBus(db_path='data/bus.db')
# WorkspaceManager: 프로젝트 루트의 workspace/ 디렉토리 사용
WORKSPACE_ROOT = Path(__file__).parent.parent / 'workspace'
workspace = WorkspaceManager(task_id='', workspace_root=str(WORKSPACE_ROOT))


@asynccontextmanager
async def lifespan(app: FastAPI):
  '''FastAPI 생명주기 관리.'''
  office = Office(
    bus=message_bus,
    event_bus=event_bus,
    workspace=workspace,
  )
  app.state.office = office
  app.state.log_history: list[dict] = []

  await office.groq_runner.start()

  # 중단된 태스크 알림 (자동 재실행 없이 사용자에게 선택권)
  asyncio.create_task(office.restore_pending_tasks())
  # 재기동 복구 — 코드 패치 중단으로 남은 orphan git 상태 정리
  asyncio.create_task(_recover_orphan_patches())

  # 에이전트 자발적 활동 백그라운드 루프 시작
  office._autonomous_task = asyncio.create_task(office.start_autonomous_loop())
  # 팀장 배치 리뷰 루프 시작 (주기적 대화 분석 + 건의 격상 + 요약 압축)
  office._teamlead_review_task = asyncio.create_task(office.start_teamlead_review_loop())
  # 메시지 버스 아카이브 루프 — 시작 시 1회 + 24h 주기 (완료 메시지 30일 이상 이관)
  archive_task = asyncio.create_task(_archive_loop())
  # draft 건의 자동 승격 루프 — 24h 경과 draft를 pending으로
  draft_promotion_task = asyncio.create_task(_draft_promotion_loop())
  yield
  archive_task.cancel()
  draft_promotion_task.cancel()
  office.stop_autonomous_loop()
  await office.groq_runner.stop()
  message_bus.close()


async def _archive_loop():
  '''서버 생존 동안 24시간 주기로 오래된 done 메시지 + 임계치 도달한 chat_logs를 archive로 이관.'''
  from db.log_store import maybe_archive_logs
  while True:
    try:
      moved = await asyncio.to_thread(message_bus.archive_old_messages)
      if moved:
        logger.info('message bus archive: moved %d rows', moved)
    except asyncio.CancelledError:
      raise
    except Exception:
      logger.exception('message bus archive failed')
    try:
      moved_logs = await asyncio.to_thread(maybe_archive_logs, 30)
      if moved_logs:
        logger.info('chat_logs archive: moved %d rows', moved_logs)
    except asyncio.CancelledError:
      raise
    except Exception:
      logger.exception('chat_logs archive failed')
    try:
      await asyncio.sleep(24 * 60 * 60)
    except asyncio.CancelledError:
      break


async def _draft_promotion_loop():
  '''1시간 주기로 24h 경과 draft 건의를 pending으로 자동 승격.

  draft → pending 승격 후 auto_triage_new_suggestion을 호출해 정상 흐름 진입.
  '''
  from db.suggestion_store import auto_promote_drafts, list_suggestions
  while True:
    try:
      await asyncio.sleep(60 * 60)
    except asyncio.CancelledError:
      break
    try:
      before = {s['id'] for s in list_suggestions(status='pending')}
      promoted = await asyncio.to_thread(auto_promote_drafts, 24)
      if promoted:
        logger.info('draft 자동 승격: %d건', promoted)
        after = list_suggestions(status='pending')
        for s in after:
          if s['id'] not in before:
            try:
              asyncio.create_task(auto_triage_new_suggestion(s['id']))
            except Exception:
              logger.debug('auto_triage 호출 실패: %s', s['id'], exc_info=True)
    except Exception:
      logger.exception('draft 자동 승격 실패')


app = FastAPI(title='AI Office', lifespan=lifespan)
app.state.ws_token = WS_AUTH_TOKEN


@app.middleware('http')
async def _rest_auth_middleware(request: Request, call_next):
  '''REST_AUTH_TOKEN이 설정된 경우 /api/* 경로를 Bearer 또는 ?token=으로 보호.

  WS 엔드포인트는 기존 WS_AUTH_TOKEN 쿼리 파라미터로 별도 보호.
  로컬 개발(토큰 미설정) 시 현재 동작 유지.
  '''
  if not REST_AUTH_TOKEN:
    return await call_next(request)
  path = request.url.path
  if not path.startswith('/api/') or path in _AUTH_EXEMPT_PATHS:
    return await call_next(request)
  # Authorization: Bearer <token> 우선
  auth = request.headers.get('authorization', '')
  token = ''
  if auth.lower().startswith('bearer '):
    token = auth[7:].strip()
  else:
    token = request.query_params.get('token', '')
  # 상수시간 비교
  if not token or not secrets.compare_digest(token, REST_AUTH_TOKEN):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
  return await call_next(request)


# CORS 설정 — Vite 개발 서버(localhost:3100) 허용
app.add_middleware(
  CORSMiddleware,
  allow_origins=['http://localhost:3100', 'http://127.0.0.1:3100'],
  allow_credentials=True,
  allow_methods=['*'],
  allow_headers=['*'],
)

from routes.admin import router as admin_router
from routes.team import router as team_router
from routes.search import router as search_router
from routes.artifacts import router as artifacts_router
from routes.logs import router as logs_router
from routes.tasks import router as tasks_router
from routes.suggestion_branch import (
  router as suggestion_branch_router,
  _run_git,
  _BRANCH_EXPLAIN_CACHE,
  explain_suggestion_branch,
)
app.include_router(admin_router)
app.include_router(team_router)
app.include_router(search_router)
app.include_router(artifacts_router)
app.include_router(logs_router)
app.include_router(tasks_router)
app.include_router(suggestion_branch_router)


def _validate_upload(f: UploadFile, content: bytes) -> str | None:
  '''업로드 파일 검증. 문제가 있으면 에러 메시지 반환, 없으면 None.'''
  ext = Path(f.filename or '').suffix.lower()
  if ext not in ALLOWED_EXTENSIONS:
    return f'허용되지 않는 파일 형식: {ext} ({f.filename})'
  if len(content) > MAX_UPLOAD_SIZE:
    return f'파일 크기 초과 ({len(content) // (1024*1024)}MB > {MAX_UPLOAD_SIZE // (1024*1024)}MB): {f.filename}'
  return None


# 요청/응답 Pydantic 모델
class TaskRequest(BaseModel):
  instruction: str  # 사용자 지시 텍스트


class TaskResponse(BaseModel):
  task_id: str
  status: str  # 'accepted'


@app.get('/health')
async def health():
  '''서버 상태 확인'''
  return {
    'status': 'ok',
    'log_bus_subscribers': event_bus.subscriber_count,
  }






# --- 건의게시판 API ---


@app.post('/api/suggestions')
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


@app.post('/api/suggestions/{suggestion_id}/promote')
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


@app.patch('/api/suggestions/{suggestion_id}')
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

  # 승인/반려 감사 이벤트
  if new_status in ('accepted', 'rejected') and suggestion:
    from db.suggestion_store import log_event as _le
    _le(suggestion_id, 'approved' if new_status == 'accepted' else 'rejected', {
      'response': (body.get('response') or '')[:200],
    })

  # 승인 — 저장된 suggestion_type 보고 자동 분기
  if new_status == 'accepted' and suggestion:
    stype = suggestion.get('suggestion_type') or 'prompt'
    auto_merge_req = bool(body.get('auto_merge', True))  # 기본 on
    if stype == 'code':
      async def _run_patch():
        from improvement.code_patcher import apply_suggestion
        from db.suggestion_store import update_suggestion as _upd
        ok = await apply_suggestion(suggestion)
        if ok:
          _upd(suggestion_id, status='review_pending')
          if auto_merge_req:
            # 자동 병합 파이프라인 진입 (risky/rollback 시 중단)
            asyncio.create_task(_auto_merge_pipeline(suggestion_id))
        else:
          _upd(suggestion_id, status='pending')
      asyncio.create_task(_run_patch())
    else:
      # prompt 타입 — 즉시 반영
      await _apply_suggestion_to_prompts(suggestion)
      # done으로 마킹
      update_suggestion(suggestion_id, status='done')

  # 반려 — 제안자 에이전트 메모리에 "유사 건의 반복 금지" 시그널
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

  # 갓 생성된 DB 트랜잭션 충돌 피하려 1초 유예
  await _a.sleep(1.0)

  s = get_suggestion(suggestion_id)
  if not s or s.get('status') != 'pending':
    return  # 이미 누가 처리함

  # 일일 triage 한도 체크 (24h 15건)
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

  # 회로 차단기
  if count_rollbacks_since(hours=24) > 0:
    log_event(suggestion_id, 'auto_triage_hold', {'reason': 'recent_rollback'})
    return

  # LLM 판정 (Haiku, 저비용)
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

  # accept — 타입별 분기
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
  else:  # code
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

  branch = f'improvement/{suggestion_id}'

  # 회로 차단기 — 최근 24h 코드 롤백(어떤 건의든) 있으면 자동 병합 전면 중단
  recent_rollbacks = count_rollbacks_since(hours=24)
  if recent_rollbacks > 0:
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message=f'⚠️ 최근 24h 롤백 {recent_rollbacks}건 — 자동 병합 중단, 수동 검토로 전환 (#{suggestion_id})',
    ))
    return

  # 일일 한도 — 24h 자동 병합 5건 초과 시 중단
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
    '''AI 리뷰 후 조건 만족 시 병합. 성공 True.'''
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
      # 자동 폐기
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

    # 스코프 재확인
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

    # 실제 병합 (PATCH_LOCK 내부)
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

      # risks를 follow-up으로 등록 (기존 merge 엔드포인트와 동일)
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

  # 1차 시도
  if await _try_merge():
    return

  # needs_fix면 자동 보완 루프 진입
  update_suggestion(suggestion_id, status='supplementing')
  import time as _time
  loop_start = _time.monotonic()
  LOOP_BUDGET = 25 * 60  # 25분 예산
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
      # 수렴 실패 감지
      if prev_risks_sig and risks_sig == prev_risks_sig:
        await event_bus.publish(LogEvent(
          agent_id='teamlead', event_type='system_notice',
          message=f'🔁 [자동] #{suggestion_id} 위험사항 변화 없음 — 수렴 실패, 중단',
        ))
        break
      prev_risks_sig = risks_sig
      # 병합 재시도
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


async def _run_one_supplement_iter(suggestion_id: str, branch: str, it: int, max_iters: int) -> tuple[bool, str]:
  '''supplement 1회 실행. (성공, risks_signature) 반환.

  성공 = Claude가 커밋 생성 + 새 explain 완료.
  '''
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
      f'프로젝트 루트: {_P(__file__).parent.parent}\n\n'
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
      result = await run_claude_isolated(prompt=prompt, timeout=600.0, max_turns=20)
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

    # 스코프 체크 — 위반 시 이 iter만 폐기 (브랜치 유지)
    file_list = [f for f in changed.strip().splitlines() if f]
    _, stat_out = _git(['diff', '--stat', 'HEAD'])
    scope_ok, scope_reason = _check_scope(suggestion, file_list, stat_out)
    if not scope_ok:
      _git(['checkout', '.'])  # 변경 폐기
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

  # 락 해제 후 explain (다른 iter 차단 불필요)
  try:
    new_explain = await explain_suggestion_branch(suggestion_id)
  except Exception:
    return (True, '')
  new_risks = (new_explain or {}).get('risks') or []
  sig = '|'.join(sorted((r or '')[:60] for r in new_risks))
  return (True, sig)


def _extract_rule_body(content: str) -> str:
  '''자동 등록 건의의 content에서 실제 발언 본문만 추출. 메타 헤더·트리거·카테고리 안내 제거.'''
  import re
  m = re.search(r'의 발언:\s*"([^"]+)"', content)
  if m:
    return m.group(1).strip()
  # 수동 건의 등 — 앞쪽 문단만 사용 (첫 메타 라인 이후 잘라냄)
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
  apply_to = target_agent or agent_id  # target 있으면 대상, 없으면 제안자 본인
  title = suggestion['title']
  content = suggestion['content']
  category = suggestion.get('category', 'general')
  user_comment = (suggestion.get('response') or '').strip()
  now_iso = datetime.now(timezone.utc).isoformat()
  rule_body = _extract_rule_body(content)  # 메타 제거한 발언 본문
  comment_suffix = f'\n[사용자 코멘트] {user_comment}' if user_comment else ''

  # 1. 팀 공유 메모리에 교훈으로 등록 → 모든 에이전트 시스템 프롬프트에 자동 주입
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

  # 2. 대상 에이전트의 PromptEvolver에 규칙 추가
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
    # 활성 규칙 10개 초과 시 hit_count 높은(=효과 낮은) 순으로 비활성화 (보존)
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

  # 3. 채팅에 공지
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


@app.get('/api/suggestions/{suggestion_id}/events')
async def get_suggestion_events(suggestion_id: str):
  '''건의의 감사 이벤트 시계열.'''
  from db.suggestion_store import list_events
  return list_events(suggestion_id=suggestion_id, limit=200)


@app.get('/api/suggestion-events')
async def get_all_events(limit: int = 200):
  '''전체 감사 이벤트 최신순 (분석용).'''
  from db.suggestion_store import list_events
  return list_events(limit=limit)


@app.delete('/api/suggestions/{suggestion_id}')
async def delete_suggestion_api(suggestion_id: str):
  '''건의를 삭제한다.'''
  from db.suggestion_store import delete_suggestion
  if not delete_suggestion(suggestion_id):
    raise HTTPException(status_code=404, detail='건의를 찾을 수 없습니다')
  return {'deleted': suggestion_id}



# --- 자가개선 API ---

@app.get('/api/improvement/report')
async def get_improvement_report(request: Request):
  '''최신 자가개선 분석 보고서를 반환한다.'''
  office: Office = request.app.state.office
  return office.improvement_engine.get_report()


async def _recover_orphan_patches():
  '''서버 기동 시 호출. 코드 패치 중단으로 남은 git/DB 불일치 정리.'''
  import subprocess as _sp
  import asyncio as _a
  from pathlib import Path as _P
  from db.suggestion_store import list_suggestions, update_suggestion

  await _a.sleep(2)  # 다른 init 끝난 뒤

  root = _P(__file__).parent.parent

  def g(args):
    r = _sp.run(['git'] + args, cwd=str(root), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

  recovered = []

  # 1. 현재 HEAD가 improvement/* 위에 있으면 main으로 강제 복귀
  _, cur = g(['rev-parse', '--abbrev-ref', 'HEAD'])
  cur = cur.strip()
  if cur.startswith('improvement/'):
    logger.warning('기동 시 HEAD가 %s 위에 있음 — main 복귀', cur)
    # 워킹트리 변경 있으면 stash (분실 방지)
    _, status = g(['status', '--porcelain'])
    if status.strip():
      g(['stash', 'push', '-u', '-m', f'auto-recover-from-{cur}'])
      recovered.append(f'워킹트리 변경 stash: {cur}')
    # 브랜치에 커밋이 있어도 무조건 main으로 복귀 (서버는 main에서만 동작)
    rc_co, out_co = g(['checkout', 'main'])
    if rc_co == 0:
      recovered.append(f'HEAD {cur} → main (브랜치 {cur}는 유지 — 사용자 검토용)')
    else:
      # main 체크아웃 실패 시 강제 (워킹트리 더러워도)
      g(['checkout', '-f', 'main'])
      recovered.append(f'HEAD {cur} → main (강제 체크아웃)')

  # 2. accepted 상태로 멈춘 code 건의 → pending 롤백 + 남은 improvement 브랜치 삭제
  try:
    stuck = [
      s for s in list_suggestions(status='accepted')
      if (s.get('suggestion_type') or 'prompt') == 'code'
    ]
    for s in stuck:
      sid = s['id']
      branch = f'improvement/{sid}'
      code, _ = g(['rev-parse', '--verify', branch])
      if code == 0:
        # 브랜치가 main과 차이 없으면 삭제, 아니면 유지 (사용자 판단)
        _, ahead = g(['rev-list', '--count', f'main..{branch}'])
        if ahead.strip() == '0':
          g(['branch', '-D', branch])
          recovered.append(f'빈 브랜치 삭제: {branch}')
      update_suggestion(sid, status='pending', response='기동 시 자동 롤백 (패치 중단)')
      recovered.append(f'건의 #{sid} 상태 accepted → pending')
  except Exception:
    logger.debug('stuck 건의 복구 실패', exc_info=True)

  if recovered:
    msg = '♻️ 기동 시 자동 복구:\n' + '\n'.join(f'- {r}' for r in recovered)
    logger.info(msg)
    try:
      await event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='system_notice', message=msg,
      ))
    except Exception:
      pass


# --- 정적 파일 서빙 (빌드된 프론트엔드) ---
DIST_DIR = Path(__file__).parent.parent / 'dashboard' / 'dist'
if DIST_DIR.exists():
  from fastapi.staticfiles import StaticFiles
  from fastapi.responses import FileResponse

  # /assets 등 정적 파일
  app.mount('/assets', StaticFiles(directory=str(DIST_DIR / 'assets')), name='static')

  # SPA fallback — API/WS가 아닌 모든 경로는 index.html 반환
  @app.get('/{path:path}')
  async def spa_fallback(path: str):
    file_path = DIST_DIR / path
    if file_path.exists() and file_path.is_file():
      return FileResponse(str(file_path))
    return FileResponse(str(DIST_DIR / 'index.html'))
