# 자가개선 코드 패처 — 건의 승인 시 Claude CLI로 코드 반영
import asyncio
import subprocess
from pathlib import Path

from log_bus.event_bus import LogEvent, event_bus
from runners.claude_runner import run_claude_isolated, ClaudeRunnerError
import logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
BRANCH_PREFIX = 'improvement'

# 코드 패치는 워킹트리를 공유하므로 직렬화 필요
# (branch checkout/commit/switch가 동시에 겹치면 엉킴)
_PATCH_LOCK = asyncio.Lock()


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
      '팀장',
      f'⏳ 건의 #{suggestion_id} — 다른 코드 패치 작업 중입니다. 대기 큐에 추가됨.',
    )

  async with _PATCH_LOCK:
    return await _apply_suggestion_locked(suggestion, suggestion_id, branch)


async def _apply_suggestion_locked(suggestion: dict, suggestion_id: str, branch: str) -> bool:
  original_branch = _current_branch()

  await _emit('팀장', f'📋 건의 #{suggestion_id} 결재 승인 — 자가개선을 시작합니다.')

  # 1. feature 브랜치 생성
  if _branch_exists(branch):
    _git(['branch', '-D', branch])
  code, out = _git(['checkout', '-b', branch])
  if code != 0:
    await _emit('팀장', f'⚠️ 브랜치 생성 실패: {out}', 'error')
    return False

  await _emit('팀장', f'🌿 브랜치 `{branch}` 생성 완료 — Claude가 코드를 수정합니다.')

  try:
    # 2. Claude CLI로 코드 수정
    prompt = _build_patch_prompt(suggestion)
    result = await run_claude_isolated(
      prompt=prompt,
      timeout=300.0,
      max_turns=20,
    )

    # 3. 변경 사항 확인
    _, diff_stat = _git(['diff', '--stat', original_branch])
    _, changed_files = _git(['diff', '--name-only', original_branch])

    if not changed_files.strip():
      await _emit('팀장', f'ℹ️ 건의 #{suggestion_id}: 변경된 파일 없음 — 구현 불가 또는 이미 적용된 상태입니다.\n\n{result}', 'message')
      _rollback(branch, original_branch)
      return False

    # 4. 성공 — 변경사항을 브랜치에 커밋하고 원 브랜치로 복귀
    #    (서버가 계속 원 브랜치에서 돌도록 — 사용자가 별도 merge 판단)
    _git(['add', '-A'])
    commit_msg = f'improvement(#{suggestion_id}): {suggestion["title"][:80]}'
    _git(['commit', '-m', commit_msg])
    _git(['checkout', original_branch])

    file_list = '\n'.join(f'  • {f}' for f in changed_files.strip().splitlines())
    await _emit('팀장', (
      f'✅ 건의 #{suggestion_id} 자가개선 완료!\n\n'
      f'**수정된 파일:**\n{file_list}\n\n'
      f'**브랜치:** `{branch}` (커밋 완료, 원 브랜치로 복귀)\n'
      f'`git merge {branch}` 로 병합 검토하세요.\n\n'
      f'**Claude 작업 요약:**\n{result[:800]}'
    ))
    return True

  except ClaudeRunnerError as e:
    await _emit('팀장', f'❌ 자가개선 실패 (Claude 오류): {e}', 'error')
    _rollback(branch, original_branch)
    return False
  except Exception as e:
    logger.warning("자가개선 중 예기치 않은 오류 발생: %s", e, exc_info=True)
    await _emit('팀장', f'❌ 자가개선 중 오류 발생: {e}', 'error')
    _rollback(branch, original_branch)
    return False


def _rollback(branch: str, original_branch: str):
  '''실패 시 원래 브랜치로 되돌리고 feature 브랜치 삭제.'''
  _git(['checkout', original_branch])
  _git(['branch', '-D', branch])
