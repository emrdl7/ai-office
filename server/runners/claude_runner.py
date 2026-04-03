# Claude CLI subprocess 러너 (INFR-02, D-05, D-06)
# --bare: CLAUDE.md 자동 로드, MCP, 훅, 플러그인 모두 비활성화 → 토큰 격리
# --print: 비대화형 모드 (stdin → stdout → 종료)
# --output-format stream-json: JSON-lines 응답
# --no-session-persistence: 세션을 디스크에 저장하지 않음
import asyncio
import json
from pathlib import Path

# 격리 디렉토리: CLAUDE.md 자동 탐색 차단 (D-06)
ISOLATION_DIR = Path('/tmp/ai-office-claude-isolated')


class ClaudeRunnerError(Exception):
    '''Claude CLI subprocess 실행 실패'''
    pass


async def run_claude_isolated(prompt: str) -> str:
    '''Claude CLI를 격리 subprocess로 실행하고 텍스트 응답을 반환한다.

    Args:
        prompt: Claude에게 전달할 프롬프트 텍스트

    Returns:
        Claude의 텍스트 응답 (JSON-lines 스트림에서 추출)

    Raises:
        ClaudeRunnerError: subprocess가 비정상 종료된 경우
    '''
    ISOLATION_DIR.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        'claude',
        '--bare',
        '--print',
        '--output-format', 'stream-json',
        '--no-session-persistence',
        prompt,
        cwd=str(ISOLATION_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors='replace').strip()
        raise ClaudeRunnerError(
            f'Claude CLI 실패 (exit {proc.returncode}): {error_msg}'
        )

    result_parts: list[str] = []
    for line in stdout.decode(errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            # stream-json 이벤트: type='assistant', content 블록 추출
            if event.get('type') == 'assistant':
                for block in event.get('message', {}).get('content', []):
                    if block.get('type') == 'text':
                        result_parts.append(block['text'])
        except json.JSONDecodeError:
            pass  # 파싱 불가 라인 무시 (스트림 메타데이터 등)

    return ''.join(result_parts)
