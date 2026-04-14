# Claude CLI subprocess 러너
import asyncio
import json
from pathlib import Path

import os
CLAUDE_CLI = os.environ.get('CLAUDE_CLI', 'claude')
CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6')
LOG = Path('data/debug.log')


class ClaudeRunnerError(Exception):
  pass


class ClaudeTimeoutError(ClaudeRunnerError):
  """Claude CLI 프로세스가 지정 타임아웃을 초과했을 때 발생."""
  pass


async def run_claude_isolated(prompt: str, timeout: float = 600.0, model: str = '', max_turns: int = 3) -> str:
  '''Claude CLI를 subprocess로 실행하고 텍스트 응답을 반환한다.'''
  project_root = str(Path(__file__).parent.parent.parent)
  use_model = model or CLAUDE_MODEL

  proc = await asyncio.create_subprocess_exec(
    CLAUDE_CLI,
    '--print',
    '--output-format', 'stream-json',
    '--verbose',
    '--no-session-persistence',
    '--dangerously-skip-permissions',
    '--model', use_model,
    '--max-turns', str(max_turns),
    prompt,
    cwd=project_root,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
  )

  try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
  except asyncio.TimeoutError:
    proc.kill()
    await proc.wait()
    raise ClaudeTimeoutError(f'Claude CLI 타임아웃 ({timeout}초)')

  stdout_text = stdout.decode(errors='replace')
  LOG.open('a').write(f'[CLAUDE] exit={proc.returncode} len={len(stdout_text)}\n')

  # stdout에서 텍스트 추출 + 에러 플래그 감지
  last_result = ''
  assistant_parts: list[str] = []
  had_error_event = False

  for line in stdout_text.splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      event = json.loads(line)
      etype = event.get('type')
      if etype == 'result':
        r = event.get('result', '')
        if r:
          last_result = r
        if event.get('is_error') or event.get('error'):
          had_error_event = True
      elif etype == 'assistant':
        for block in event.get('message', {}).get('content', []):
          if block.get('type') == 'text':
            assistant_parts.append(block['text'])
      elif etype == 'error':
        had_error_event = True
    except json.JSONDecodeError:
      pass

  # assistant 누적 텍스트가 result보다 충분히 길면 그걸 우선 (Claude가 짧은 result로 끊는 경우 대응)
  assistant_full = ''.join(assistant_parts)
  if len(assistant_full) > len(last_result) * 2 and len(assistant_full) > 50:
    text = assistant_full
    LOG.open('a').write(f'[CLAUDE] using assistant ({len(text)}) > result ({len(last_result)})\n')
  else:
    text = last_result or assistant_full

  # 끊김 감지 — exit!=0 또는 error 이벤트 + 응답 너무 짧으면 폴백 유도
  stripped = text.strip()
  if (proc.returncode != 0 or had_error_event) and len(stripped) < 80:
    LOG.open('a').write(
      f'[CLAUDE] truncated: exit={proc.returncode} err={had_error_event} len={len(stripped)}\n'
    )
    raise ClaudeRunnerError(
      f'Claude 응답 끊김 (exit={proc.returncode}, err={had_error_event}, len={len(stripped)})'
    )

  if stripped:
    LOG.open('a').write(f'[CLAUDE] result_len={len(stripped)}, using result\n')
    return text

  raise ClaudeRunnerError('Claude 응답 텍스트 없음')
