# Opencode CLI 러너 — 클라우드 모델로 코드 생성
from __future__ import annotations
# developer 에이전트의 코드/구현 작업을 opencode run으로 대체
import asyncio
import json
import re
from pathlib import Path

import os
OPENCODE_CLI = os.environ.get('OPENCODE_CLI', 'opencode')
TIMEOUT = 300.0
PROJECT_ROOT = str(Path(__file__).parent.parent.parent)


class OpencodeRunnerError(Exception):
    pass


async def run_opencode(
    prompt: str,
    system: str = "",
    workspace_dir: str = "",
    timeout: float = TIMEOUT,
) -> str:
    """opencode run을 subprocess로 실행하고 텍스트 응답을 반환한다.

    developer 작업(코드 생성, 구현)에 사용.
    --format json으로 JSON 이벤트 스트림을 파싱하여 최종 응답을 추출한다.

    Args:
      prompt: 사용자 프롬프트 (작업 지시)
      system: 시스템 프롬프트 (에이전트 역할 정의)
      workspace_dir: 작업 디렉토리 (--dir 옵션)
      timeout: 타임아웃 (초)

    Returns:
      opencode의 최종 응답 텍스트
    """
    workdir = workspace_dir or PROJECT_ROOT

    # 시스템 프롬프트를 파일로 저장하여 --command로 전달
    # opencode run은 메시지 기반이므로 system prompt를 프롬프트 앞에 삽입
    full_prompt = ""
    if system:
        full_prompt = f"[시스템]\n{system}\n\n[작업 지시]\n{prompt}"
    else:
        full_prompt = prompt

    proc = await asyncio.create_subprocess_exec(
        OPENCODE_CLI,
        "run",
        "--format",
        "json",
        "--pure",
        full_prompt,
        cwd=workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise OpencodeRunnerError(f"opencode 타임아웃 ({timeout}초)")

    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")

    Path("data/debug.log").open("a").write(
        f"[OPENCODE] exit={proc.returncode} stdout_len={len(stdout_text)} stderr_len={len(stderr_text)}\n"
    )

    # JSON 이벤트 스트림에서 assistant 응답 추출
    response = _extract_response(stdout_text)

    if response:
        return response

    # 응답이 없으면 stderr 포함
    if stderr_text.strip():
        Path("data/debug.log").open("a").write(
            f"[OPENCODE] stderr: {stderr_text[:500]}\n"
        )

    raise OpencodeRunnerError(f"opencode 응답 없음 (exit={proc.returncode})")


def _extract_response(stdout: str) -> str | None:
    """opencode JSON 이벤트 스트림에서 최종 assistant 응답을 추출한다.

    이벤트 형식:
    {"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}
    {"type":"result","result":"..."}
    """
    last_result = ""
    assistant_parts: list[str] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            event_type = event.get("type", "")

            if event_type == "result":
                r = event.get("result", "")
                if r:
                    last_result = r
            elif event_type == "assistant":
                msg = event.get("message", {})
                content = msg.get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_parts.append(block["text"])
        except json.JSONDecodeError:
            pass

    # result 이벤트 우선, 없으면 assistant 텍스트 결합
    return last_result or "".join(assistant_parts) or None


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """마크다운 응답에서 코드 블록을 추출한다.

    Returns:
      [(언어, 코드내용), ...] 목록
    """
    pattern = r"```(\w+)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return [(lang or "text", code.strip()) for lang, code in matches]
