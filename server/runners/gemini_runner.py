# Gemini CLI subprocess 러너
import asyncio
from pathlib import Path

import os
GEMINI_CLI = os.environ.get('GEMINI_CLI', 'gemini')
LOG = Path('data/debug.log')


class GeminiRunnerError(Exception):
  pass


async def run_gemini(prompt: str, system: str = '', timeout: float = 600.0) -> str:
  '''Gemini CLI를 subprocess로 실행하고 텍스트 응답을 반환한다.'''
  project_root = str(Path(__file__).parent.parent.parent)

  # system prompt가 있으면 prompt 앞에 합침
  full_prompt = prompt
  if system:
    full_prompt = f'{system}\n\n---\n\n{prompt}'

  proc = await asyncio.create_subprocess_exec(
    GEMINI_CLI,
    '-p', '',  # non-interactive 모드, stdin에서 프롬프트 읽음
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

  # stderr의 deprecation warning, 로그 등 제거하고 실제 응답만 추출
  lines = []
  for line in stdout_text.splitlines():
    # Gemini CLI의 노이즈 필터링
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

  # stdout이 비었으면 stderr도 확인
  stderr_text = stderr.decode(errors='replace').strip()
  if 'rate limit' in stderr_text.lower() or '429' in stderr_text:
    raise GeminiRunnerError(f'Gemini rate limit 초과: {stderr_text[:200]}')

  raise GeminiRunnerError(f'Gemini 응답 없음 (exit={proc.returncode})')
