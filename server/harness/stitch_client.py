# Stitch 클라이언트 — Node 브릿지를 통해 Google Stitch API 호출
import asyncio
import json
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

BRIDGE_PATH = Path(__file__).parent / 'stitch_bridge.mjs'
NODE_MODULES = Path(__file__).parent.parent.parent / 'node_modules'
TIMEOUT = 300.0


async def generate_design(prompt: str, output_dir: str) -> dict:
  '''Stitch로 UI 디자인을 생성한다.

  Args:
    prompt: 디자인 프롬프트 (디자이너의 전체 활동 내역 포함)
    output_dir: 산출물 저장 경로

  Returns:
    {'success': bool, 'html_path': str|None, 'image_path': str|None, 'error': str|None}
  '''
  env = {
    'NODE_PATH': str(NODE_MODULES),
    'PATH': '/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin',
  }

  # STITCH_API_KEY 환경변수 확인
  import os
  api_key = os.environ.get('STITCH_API_KEY', '')
  if api_key:
    env['STITCH_API_KEY'] = api_key

  # 프롬프트를 stdin으로 전달 — subprocess 인자의 특수문자 잘림 방지
  proc = await asyncio.create_subprocess_exec(
    'node', str(BRIDGE_PATH), 'generate', '--stdin', output_dir,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env={**os.environ, **env},
  )
  proc.stdin.write(prompt.encode('utf-8'))
  proc.stdin.close()

  try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
  except asyncio.TimeoutError:
    proc.kill()
    return {'success': False, 'error': f'Stitch 타임아웃 ({TIMEOUT}초)'}

  try:
    return json.loads(stdout.decode())
  except Exception:
    logger.debug("Stitch 응답 JSON 파싱 실패", exc_info=True)
    return {
      'success': False,
      'error': stderr.decode(errors='replace')[:500] or stdout.decode(errors='replace')[:500],
    }


async def designer_generate_with_context(
  design_context: str,
  task_id: str,
  workspace_root: str,
) -> dict:
  '''디자이너 활동 내역을 반영하여 Stitch 디자인을 생성한다.

  디자이너가 분석한 내용, 컬러/타이포/레이아웃 결정사항을
  모두 프롬프트에 포함해서 Stitch에 전달한다.

  Args:
    design_context: 디자이너의 전체 활동 내역 (마크다운)
    task_id: 태스크 ID
    workspace_root: workspace 루트 경로

  Returns:
    생성된 파일 정보
  '''
  output_dir = str(Path(workspace_root) / task_id / 'stitch')

  # 디자이너 활동 내역을 Stitch 프롬프트로 변환
  prompt = (
    f'아래 디자인 명세를 반영하여 UI를 생성해주세요.\n\n'
    f'{design_context}'
  )

  result = await generate_design(prompt, output_dir)

  if result.get('success'):
    Path(f'{output_dir}/design_context.md').write_text(design_context, encoding='utf-8')

  return result
