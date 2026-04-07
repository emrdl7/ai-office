# Gemini CLI subprocess 러너
import asyncio
from pathlib import Path

import os
GEMINI_CLI = os.environ.get('GEMINI_CLI', 'gemini')
LOG = Path('data/debug.log')

# 응답이 잘렸는지 판단하는 패턴
_CUT_INDICATORS = ['###', '## ', '**', '- **', '---', '|']


class GeminiRunnerError(Exception):
  pass


def _looks_truncated(text: str) -> bool:
  '''응답이 중간에 잘린 것처럼 보이는지 판단한다.'''
  if not text:
    return False
  last_line = text.rstrip().split('\n')[-1].strip()
  # 마지막 줄이 헤더/리스트 시작이면 잘린 것
  if any(last_line.endswith(ind) for ind in _CUT_INDICATORS):
    return True
  # 마지막 줄이 문장 중간에 끊겼으면 (마침표/느낌표/물음표로 안 끝남)
  if last_line and not last_line[-1] in '.!?。\n```':
    # 단, 짧은 응답(회의 발언 등)은 제외
    if len(text) > 1500:
      return True
  return False


async def _call_gemini(full_prompt: str, timeout: float) -> str:
  '''Gemini CLI 단일 호출'''
  project_root = str(Path(__file__).parent.parent.parent)

  proc = await asyncio.create_subprocess_exec(
    GEMINI_CLI,
    '-p', '',
    '-o', 'text',
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=project_root,
  )

  try:
    stdout, stderr = await asyncio.wait_for(
      proc.communicate(input=full_prompt.encode('utf-8')),
      timeout=timeout,
    )
  except asyncio.TimeoutError:
    proc.kill()
    await proc.wait()
    raise GeminiRunnerError(f'Gemini CLI 타임아웃 ({timeout}초)')

  stdout_text = stdout.decode(errors='replace')
  LOG.open('a').write(f'[GEMINI] exit={proc.returncode} len={len(stdout_text)}\n')

  lines = []
  for line in stdout_text.splitlines():
    if 'DeprecationWarning' in line:
      continue
    if 'Loaded cached credentials' in line:
      continue
    if 'Hook registry initialized' in line:
      continue
    if line.strip().startswith('(node:'):
      continue
    lines.append(line)

  text = '\n'.join(lines).strip()

  if text:
    return text

  stderr_text = stderr.decode(errors='replace').strip()
  if 'rate limit' in stderr_text.lower() or '429' in stderr_text:
    raise GeminiRunnerError(f'Gemini rate limit 초과: {stderr_text[:200]}')

  raise GeminiRunnerError(f'Gemini 응답 없음 (exit={proc.returncode})')


async def run_gemini(prompt: str, system: str = '', timeout: float = 600.0) -> str:
  '''Gemini CLI를 실행하고, 응답이 잘리면 이어서 작성하도록 재호출한다.'''
  full_prompt = prompt
  if system:
    full_prompt = f'{system}\n\n---\n\n{prompt}'

  result = await _call_gemini(full_prompt, timeout)

  # 응답이 잘린 것 같으면 최대 2회 이어쓰기
  for _ in range(2):
    if not _looks_truncated(result):
      break
    continue_prompt = (
      f'{full_prompt}\n\n'
      f'[이전 응답]\n{result}\n\n'
      f'위 응답이 중간에 끊겼습니다. 끊긴 부분부터 이어서 작성하세요. '
      f'이전 내용을 반복하지 말고, 끊긴 지점부터 바로 이어서 작성하세요.'
    )
    continuation = await _call_gemini(continue_prompt, timeout)
    result += '\n' + continuation

  return result
