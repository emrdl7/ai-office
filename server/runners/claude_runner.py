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


async def run_claude_isolated(prompt: str, timeout: float = 180.0) -> str:
  '''Claude CLI를 subprocess로 실행하고 텍스트 응답을 반환한다.'''
  project_root = str(Path(__file__).parent.parent.parent)

  proc = await asyncio.create_subprocess_exec(
    CLAUDE_CLI,
    '--print',
    '--output-format', 'stream-json',
    '--verbose',
    '--no-session-persistence',
    '--dangerously-skip-permissions',
    '--model', CLAUDE_MODEL,
    '--max-turns', '3',
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
    raise ClaudeRunnerError(f'Claude CLI 타임아웃 ({timeout}초)')

  stdout_text = stdout.decode(errors='replace')
  LOG.open('a').write(f'[CLAUDE] exit={proc.returncode} len={len(stdout_text)}\n')

  # stdout에서 텍스트 추출 — exit code 완전 무시
  # 1순위: result 이벤트의 result 필드 (마지막 것)
  last_result = ''
  # 2순위: assistant 이벤트의 text 블록들
  assistant_parts: list[str] = []

  for line in stdout_text.splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      event = json.loads(line)
      if event.get('type') == 'result':
        r = event.get('result', '')
        if r:
          last_result = r
      elif event.get('type') == 'assistant':
        for block in event.get('message', {}).get('content', []):
          if block.get('type') == 'text':
            assistant_parts.append(block['text'])
    except json.JSONDecodeError:
      pass

  # result 이벤트 우선, 없으면 assistant 텍스트
  text = last_result or ''.join(assistant_parts)

  if text:
    LOG.open('a').write(f'[CLAUDE] result_len={len(text)}, using result\n')
    return text

  raise ClaudeRunnerError('Claude 응답 텍스트 없음')
