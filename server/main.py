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
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
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
from core import paths
workspace = WorkspaceManager(task_id='', workspace_root=str(paths.WORKSPACE_ROOT))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  '''FastAPI 생명주기 관리.'''
  office = Office(
    bus=message_bus,
    event_bus=event_bus,
    workspace=workspace,
  )
  app.state.office = office
  app.state.log_history = []

  # 중단된 태스크 알림 (자동 재실행 없이 사용자에게 선택권)
  asyncio.create_task(office.restore_pending_tasks())
  # 재기동 복구 — 코드 패치 중단으로 남은 orphan git 상태 정리
  asyncio.create_task(_recover_orphan_patches())
  # 재시작 완료 알림 — 직전이 "재시작 중" 시스템 알림이면 후속 알림 발행
  asyncio.create_task(_announce_restart_complete())

  # [동결] 자율 대화 루프 — UX Studio 전환으로 비활성화
  # office._autonomous_task = asyncio.create_task(office.start_autonomous_loop())
  # [동결] 팀장 배치 리뷰 루프
  # office._teamlead_review_task = asyncio.create_task(office.start_teamlead_review_loop())
  # [동결] 대화 품질 자동 평가 루프
  # from orchestration.conversation_quality import quality_eval_loop
  # quality_task = asyncio.create_task(quality_eval_loop(office))

  # 메시지 버스 아카이브 루프 — 시작 시 1회 + 24h 주기 (완료 메시지 30일 이상 이관)
  archive_task = asyncio.create_task(_archive_loop())
  # draft 건의 자동 승격 루프 — 24h 경과 draft를 pending으로
  draft_promotion_task = asyncio.create_task(_draft_promotion_loop())
  yield
  archive_task.cancel()
  draft_promotion_task.cancel()
  office.stop_autonomous_loop()
  message_bus.close()


async def _archive_loop() -> None:
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
    # 1년+ archive 데이터 → 분기별 JSONL 파일 dump
    try:
      from db.log_store import dump_archive_to_quarterly_file
      dumped, fpath = await asyncio.to_thread(dump_archive_to_quarterly_file, 365)
      if dumped:
        logger.info('chat_logs quarterly dump: %d rows → %s', dumped, fpath)
    except asyncio.CancelledError:
      raise
    except Exception:
      logger.exception('chat_logs quarterly dump failed')
    try:
      await asyncio.sleep(24 * 60 * 60)
    except asyncio.CancelledError:
      break


async def _draft_promotion_loop() -> None:
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
async def _rest_auth_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
from routes.suggestion_branch import router as suggestion_branch_router
from routes.suggestions import router as suggestions_router, auto_triage_new_suggestion
from routes.autonomous import router as autonomous_router
from routes.topics import router as topics_router
from routes.jobs import router as jobs_router
app.include_router(admin_router)
app.include_router(team_router)
app.include_router(search_router)
app.include_router(artifacts_router)
app.include_router(logs_router)
app.include_router(tasks_router)
app.include_router(suggestion_branch_router)
app.include_router(suggestions_router)
app.include_router(autonomous_router)
app.include_router(topics_router)
app.include_router(jobs_router)


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
async def health() -> dict[str, Any]:
  '''서버 상태 확인'''
  return {
    'status': 'ok',
    'log_bus_subscribers': event_bus.subscriber_count,
  }






# --- 자가개선 API ---

@app.get('/api/improvement/report')
async def get_improvement_report(request: Request) -> dict[str, Any]:
  '''최신 자가개선 분석 보고서를 반환한다.'''
  office: Office = request.app.state.office
  return office.improvement_engine.get_report()


async def _announce_restart_complete() -> None:
  '''직전 로그가 "재시작 중" 시스템 알림이면 "재시작 완료" 후속 알림.

  콜드 스타트(첫 부팅 / 무관한 종료 후 재기동)에서는 발행 안 함.
  웹소켓 구독자가 붙을 시간을 짧게 주기 위해 1.5초 대기.
  '''
  await asyncio.sleep(1.5)
  try:
    from db.log_store import load_logs
    recent = load_logs(limit=3)
  except Exception:
    return
  was_restart = any(
    l.get('agent_id') == 'teamlead'
    and l.get('event_type') == 'system_notice'
    and '재시작 중' in (l.get('message') or '')
    for l in recent
  )
  if not was_restart:
    return
  try:
    await event_bus.publish(LogEvent(
      agent_id='teamlead', event_type='system_notice',
      message='✅ 서버 재시작 완료 — 새 코드로 동작 중.',
    ))
  except Exception:
    logger.debug('재시작 완료 알림 실패', exc_info=True)


async def _recover_orphan_patches() -> None:
  '''서버 기동 시 호출. 코드 패치 중단으로 남은 git/DB 불일치 정리.'''
  import subprocess as _sp
  import asyncio as _a
  from pathlib import Path as _P
  from db.suggestion_store import list_suggestions, update_suggestion

  await _a.sleep(2)  # 다른 init 끝난 뒤

  root = _P(__file__).parent.parent

  def g(args: list[str]) -> tuple[int, str]:
    r = _sp.run(['git'] + args, cwd=str(root), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

  recovered: list[str] = []

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
  async def spa_fallback(path: str) -> FileResponse:
    file_path = DIST_DIR / path
    if file_path.exists() and file_path.is_file():
      return FileResponse(str(file_path))
    return FileResponse(str(DIST_DIR / 'index.html'))
