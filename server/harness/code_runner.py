# 코드 실행 하네스 — 산출물 코드를 실행하고 결과를 반환
import asyncio
from pathlib import Path


TIMEOUT = 10.0  # 코드 실행 최대 10초


async def run_code(file_path: str) -> dict:
  '''코드 파일을 실행하고 결과를 반환한다.

  Returns:
    {'success': bool, 'stdout': str, 'stderr': str, 'exit_code': int}
  '''
  p = Path(file_path)
  if not p.exists():
    return {'success': False, 'stdout': '', 'stderr': f'파일 없음: {file_path}', 'exit_code': -1}

  suffix = p.suffix.lower()

  # 언어별 실행 명령
  if suffix == '.py':
    cmd = ['python3', str(p)]
  elif suffix == '.js':
    cmd = ['node', str(p)]
  elif suffix == '.ts':
    cmd = ['npx', 'tsx', str(p)]
  elif suffix == '.sh':
    cmd = ['bash', str(p)]
  else:
    return {'success': False, 'stdout': '', 'stderr': f'실행 불가 확장자: {suffix}', 'exit_code': -1}

  proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=str(p.parent),
  )

  try:
    stdout, stderr = await asyncio.wait_for(
      proc.communicate(),
      timeout=TIMEOUT,
    )
  except asyncio.TimeoutError:
    proc.kill()
    return {'success': False, 'stdout': '', 'stderr': f'실행 타임아웃 ({TIMEOUT}초)', 'exit_code': -1}

  return {
    'success': proc.returncode == 0,
    'stdout': stdout.decode(errors='replace')[:2000],
    'stderr': stderr.decode(errors='replace')[:2000],
    'exit_code': proc.returncode,
  }
