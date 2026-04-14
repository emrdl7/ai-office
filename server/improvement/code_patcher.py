# 자가개선 코드 패처 — 건의 승인 시 Claude CLI로 코드 반영
import asyncio
import subprocess
from pathlib import Path

from log_bus.event_bus import LogEvent, event_bus
from runners.claude_runner import run_claude_isolated, ClaudeRunnerError, ClaudeTimeoutError
import logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent

# 지수 백오프 재시도 설정
_RETRY_MAX = 3        # 최대 재시도 횟수 (초기 시도 제외)
_RETRY_BASE = 2.0     # 기본 대기 초 (2^n 배수로 증가)
_RETRY_MAX_DELAY = 30.0  # 대기 상한 (초) — 600초 타임아웃의 5% 이내로 제한
BRANCH_PREFIX = 'improvement'

# 코드 패치는 워킹트리를 공유하므로 직렬화 필요
# (branch checkout/commit/switch가 동시에 겹치면 엉킴)
_PATCH_LOCK = asyncio.Lock()

# 스코프 제한 — 건의 내용에 해당 파일이 명시적으로 언급되지 않으면 수정 불가
FORBIDDEN_PATHS = (
  'server/main.py',
  'server/orchestration/office.py',
  'dashboard/src/components/SuggestionModal.tsx',
  'dashboard/src/components/ChatRoom.tsx',
  'dashboard/src/components/Sidebar.tsx',
  'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'uv.lock',
  'dashboard/vite.config.ts', 'tsconfig.json',
  '.gitignore', '.gitattributes',
)
MAX_CHANGED_FILES = 15
MAX_CHANGED_LINES = 500


def _check_scope(suggestion: dict, changed_files: list[str], diff_stat: str) -> tuple[bool, str]:
  '''변경이 스코프 제약을 위반하는지 검사. (ok, 위반 사유).'''
  content_lower = (suggestion.get('content', '') + ' ' + suggestion.get('title', '')).lower()
  # 파일 수 체크
  if len(changed_files) > MAX_CHANGED_FILES:
    return (False, f'변경 파일 {len(changed_files)}개 > 한도 {MAX_CHANGED_FILES}개')
  # 줄 수 체크 (diff --stat의 마지막 줄에 합계)
  import re as _re
  m = _re.search(r'(\d+)\s+insertion.*?(\d+)\s+deletion', diff_stat)
  if m:
    total = int(m.group(1)) + int(m.group(2))
    if total > MAX_CHANGED_LINES:
      return (False, f'변경 {total}줄 > 한도 {MAX_CHANGED_LINES}줄')
  # 금지 파일 체크 — 건의 본문에 언급되지 않았는데 수정된 경우
  violations = []
  for f in changed_files:
    for fp in FORBIDDEN_PATHS:
      if fp in f:
        # 건의에 해당 경로가 언급됐는지 간단 검사 (파일명 또는 핵심 토큰)
        fname = fp.split('/')[-1].lower()
        if fp.lower() not in content_lower and fname not in content_lower:
          violations.append(f'{f} (금지 경로 - 건의에 언급 없음)')
        break
  if violations:
    return (False, '금지 파일 무단 수정: ' + ', '.join(violations[:5]))
  return (True, '')


def _git(args: list[str]) -> tuple[int, str]:
  '''git 명령을 동기로 실행하고 (returncode, stdout+stderr) 반환.'''
  result = subprocess.run(
    ['git'] + args,
    cwd=str(PROJECT_ROOT),
    capture_output=True,
    text=True,
  )
  return result.returncode, (result.stdout + result.stderr).strip()


def _current_branch() -> str:
  _, out = _git(['rev-parse', '--abbrev-ref', 'HEAD'])
  return out.strip()


def _branch_exists(branch: str) -> bool:
  code, _ = _git(['rev-parse', '--verify', branch])
  return code == 0


async def _emit(agent_id: str, message: str, event_type: str = 'message'):
  await event_bus.publish(LogEvent(
    agent_id=agent_id,
    event_type=event_type,
    message=message,
  ))


async def _run_with_backoff(
  suggestion_id: str,
  prompt: str,
  timeout: float,
  max_turns: int,
) -> str:
  '''지수 백오프로 run_claude_isolated를 재시도한다.

  타임아웃 오류(ClaudeTimeoutError)는 재시도하지 않고 즉시 re-raise한다.
  그 외 ClaudeRunnerError는 최대 _RETRY_MAX회 재시도하고,
  초과 시 원본 오류를 체인으로 보존해 re-raise한다.
  '''
  last_error: ClaudeRunnerError | None = None
  for attempt in range(1 + _RETRY_MAX):
    try:
      return await run_claude_isolated(
        prompt=prompt,
        timeout=timeout,
        max_turns=max_turns,
      )
    except ClaudeTimeoutError:
      raise  # 타임아웃은 재시도 없이 즉시 전파
    except ClaudeRunnerError as e:
      last_error = e
      if attempt >= _RETRY_MAX:
        raise ClaudeRunnerError(
          f'재시도 {_RETRY_MAX}회 초과 — 마지막 오류: {e}'
        ) from e
      delay = min(_RETRY_BASE ** (attempt + 1), _RETRY_MAX_DELAY)
      logger.warning(
        '건의 #%s Claude 오류 (시도 %d/%d), %.0f초 후 재시도: %s',
        suggestion_id, attempt + 1, _RETRY_MAX, delay, e,
      )
      await _emit(
        'teamlead',
        f'⚠️ 건의 #{suggestion_id} Claude 오류 — {delay:.0f}초 후 재시도 ({attempt + 1}/{_RETRY_MAX}): {e}',
      )
      await asyncio.sleep(delay)
  # 여기에 도달하지 않음 (루프 안에서 raise 처리)
  raise ClaudeRunnerError(f'재시도 초과: {last_error}') from last_error


def _build_patch_prompt(suggestion: dict) -> str:
  category_map = {
    '도구 부족': 'MCP 서버 또는 새로운 runner/tool을 추가해 주세요.',
    '정보 부족': '필요한 정보를 가져올 수 있도록 코드를 수정해 주세요.',
    '데이터 부족': '필요한 데이터를 처리하거나 수집할 수 있도록 코드를 수정해 주세요.',
    'general': '아래 건의사항을 코드에 반영해 주세요.',
  }
  category_hint = category_map.get(suggestion.get('category', 'general'), category_map['general'])

  return f"""# AI Office 자가개선 작업

당신은 AI Office 프로젝트의 자가개선 엔지니어입니다.
프로젝트 루트: {PROJECT_ROOT}

팀원 {suggestion['agent_id']}이(가) 다음 개선사항을 건의했고, 사용자가 승인했습니다.

## 건의 ID: {suggestion['id']}
## 제목: {suggestion['title']}
## 카테고리: {suggestion['category']}
## 건의 내용:
{suggestion['content']}

## ⚠️ 범위 제약 (반드시 준수) — 어기면 패치 전체 폐기
- **변경 범위는 건의 내용에 명시된 파일·모듈에만 한정**하라. 건의가 "디자인 토큰"이면 토큰 관련 파일(tokens/, tokens.css, 빌드 스크립트)만 허용. 서버 코드·설정·라이브러리는 건드리지 마라.
- **최대 15개 파일, 총 500줄 이하** 변경을 목표로. 초과가 불가피하면 중단하고 "범위 초과: [이유]"로 응답.
- **다음 파일은 특별한 언급이 없는 한 절대 수정 금지**:
  - `server/main.py`, `server/orchestration/office.py` (핵심 오케스트레이션)
  - `dashboard/src/components/SuggestionModal.tsx`, `ChatRoom.tsx`, `Sidebar.tsx` (UI 핵심)
  - `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `uv.lock` (의존성)
  - `vite.config.ts`, `tsconfig.json`, `.gitignore`, `.gitattributes` (프로젝트 설정)
- 위 금지 파일을 손대야만 한다면 **먼저 중단하고 "범위 확인 필요: 건의가 {{파일명}} 수정을 포함하는지 불분명"** 으로 응답하라.
- 건의에서 요구하지 않은 **라이브러리 추가·버전 업·설정 변경 금지**.

## 작업 지침
{category_hint}

- 프로젝트 구조를 먼저 파악한 뒤 최소한의 변경으로 구현하세요.
- 기존 코드 스타일과 패턴을 유지하세요.
- 변경 파일 목록과 변경 이유를 마지막에 간략히 정리해 주세요.
- 실행 불가능하거나 범위를 벗어난 건의는 "구현 불가: [이유]"로 응답하세요.
- 절대로 테스트를 실패시키거나 서버 기동을 깨뜨리지 마세요.
"""


async def apply_suggestion(suggestion: dict) -> bool:
  '''건의사항을 feature 브랜치에서 Claude CLI로 코드에 반영한다. 성공 시 True.

  동일 워킹트리를 사용하므로 전역 락으로 직렬화한다.
  '''
  suggestion_id = suggestion['id']
  branch = f'{BRANCH_PREFIX}/{suggestion_id}'

  # 락 대기 중이면 대기 안내
  if _PATCH_LOCK.locked():
    await _emit(
      'teamlead',
      f'⏳ 건의 #{suggestion_id} — 다른 코드 패치 작업 중입니다. 대기 큐에 추가됨.',
    )

  async with _PATCH_LOCK:
    return await _apply_suggestion_locked(suggestion, suggestion_id, branch)


async def _apply_suggestion_locked(suggestion: dict, suggestion_id: str, branch: str) -> bool:
  original_branch = _current_branch()

  await _emit('teamlead', f'📋 건의 #{suggestion_id} 결재 승인 — 자가개선을 시작합니다.')

  # 1. feature 브랜치 생성
  if _branch_exists(branch):
    _git(['branch', '-D', branch])
  code, out = _git(['checkout', '-b', branch])
  if code != 0:
    await _emit('teamlead', f'⚠️ 브랜치 생성 실패: {out}', 'error')
    return False

  await _emit('teamlead', f'🌿 브랜치 `{branch}` 생성 완료 — Claude가 코드를 수정합니다.')

  try:
    # 2. Claude CLI로 코드 수정
    prompt = _build_patch_prompt(suggestion)
    timed_out = False
    try:
      result = await _run_with_backoff(
        suggestion_id=suggestion_id,
        prompt=prompt,
        timeout=600.0,  # 5분 → 10분으로 연장 (CI 워크플로 등 복잡 작업 여유)
        max_turns=20,
      )
    except ClaudeTimeoutError:
      timed_out = True
      result = f'⏱️ Claude CLI 타임아웃 (600초) — 중간 결과물 확인 필요'

    # 3. 변경 사항 확인
    _, diff_stat = _git(['diff', '--stat', original_branch])
    _, changed_files = _git(['diff', '--name-only', original_branch])

    if not changed_files.strip():
      note = '타임아웃 + ' if timed_out else ''
      await _emit('teamlead', f'ℹ️ 건의 #{suggestion_id}: {note}변경된 파일 없음 — 구현 불가 또는 이미 적용된 상태입니다.\n\n{result}', 'message')
      _rollback(branch, original_branch)
      return False

    # 타임아웃이어도 변경 파일이 있으면 partial 결과를 커밋해 사용자 검토에 넘김
    if timed_out:
      await _emit('teamlead', (
        f'⏱️ 건의 #{suggestion_id}: 타임아웃이지만 부분 결과물 존재 — '
        f'{len(changed_files.strip().splitlines())}파일 변경됨. 검토 대기로 전환합니다.'
      ), 'message')

    # 스코프 체크 — 금지 파일·사이즈 초과 시 폐기
    file_list = [f for f in changed_files.strip().splitlines() if f]
    scope_ok, scope_reason = _check_scope(suggestion, file_list, diff_stat)
    if not scope_ok:
      await _emit('teamlead', (
        f'🚫 건의 #{suggestion_id} 스코프 위반으로 패치 폐기: {scope_reason}\n'
        f'변경 파일: {", ".join(file_list[:8])}\n'
        f'건의 범위를 좁혀 다시 올리거나 범위를 명시해 재승인하세요.'
      ), 'error')
      _rollback(branch, original_branch)
      return False

    # 4. 성공 — 변경사항을 브랜치에 커밋하고 원 브랜치로 복귀
    #    (서버가 계속 원 브랜치에서 돌도록 — 사용자가 별도 merge 판단)
    _git(['add', '-A'])
    commit_msg = f'improvement(#{suggestion_id}): {suggestion["title"][:80]}'
    _git(['commit', '-m', commit_msg])
    _git(['checkout', original_branch])

    file_list = '\n'.join(f'  • {f}' for f in changed_files.strip().splitlines())
    await _emit('teamlead', (
      f'✅ 건의 #{suggestion_id} 자가개선 완료!\n\n'
      f'**수정된 파일:**\n{file_list}\n\n'
      f'**브랜치:** `{branch}` (커밋 완료, 원 브랜치로 복귀)\n'
      f'`git merge {branch}` 로 병합 검토하세요.\n\n'
      f'**Claude 작업 요약:**\n{result[:800]}'
    ))
    return True

  except ClaudeRunnerError as e:
    await _emit('teamlead', f'❌ 자가개선 실패 (Claude 오류): {e}', 'error')
    _rollback(branch, original_branch)
    return False
  except Exception as e:
    logger.warning("자가개선 중 예기치 않은 오류 발생: %s", e, exc_info=True)
    await _emit('teamlead', f'❌ 자가개선 중 오류 발생: {e}', 'error')
    _rollback(branch, original_branch)
    return False


def _rollback(branch: str, original_branch: str):
  '''실패 시 원래 브랜치로 되돌리고 feature 브랜치 삭제.'''
  _git(['checkout', original_branch])
  _git(['branch', '-D', branch])
