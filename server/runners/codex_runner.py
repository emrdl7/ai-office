"""Codex CLI subprocess runner."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

LOG = Path('data/debug.log')
CODEX_CLI = os.environ.get('CODEX_CLI', 'codex')
CODEX_MODEL = os.environ.get('CODEX_MODEL', '')


class CodexRunnerError(Exception):
    pass


class PermanentCodexRunnerError(CodexRunnerError):
    pass


class CodexTimeoutError(CodexRunnerError):
    pass


async def run_codex_isolated(
    prompt: str,
    timeout: float = 600.0,
    model: str = '',
    reasoning_effort: str = '',
) -> str:
    """Run Codex CLI non-interactively and return the final assistant text."""
    project_root = str(Path(__file__).parent.parent.parent)
    use_model = model or CODEX_MODEL
    use_effort = reasoning_effort or os.environ.get('CODEX_REASONING_EFFORT', '')

    with NamedTemporaryFile('w+', encoding='utf-8', suffix='.txt', delete=False) as out:
        output_path = out.name

    cmd = [
        CODEX_CLI,
        'exec',
        '--cd', project_root,
        '--sandbox', 'read-only',
        '--ask-for-approval', 'never',
        '--output-last-message', output_path,
    ]
    if use_model:
        cmd.extend(['--model', use_model])
    if use_effort:
        cmd.extend(['-c', f'model_reasoning_effort="{use_effort}"'])
    cmd.append(prompt)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=project_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise CodexTimeoutError(f'Codex CLI 타임아웃 ({timeout}초)')

    stdout_text = stdout.decode(errors='replace')
    stderr_text = stderr.decode(errors='replace').strip() if stderr else ''
    try:
        LOG.open('a').write(f'[CODEX] exit={proc.returncode} stdout_len={len(stdout_text)}\n')
        if stderr_text and proc.returncode != 0:
            LOG.open('a').write(f'[CODEX] stderr: {stderr_text[:500]}\n')
    except Exception:
        pass

    text = ''
    try:
        output_file = Path(output_path)
        if output_file.exists():
            text = output_file.read_text('utf-8').strip()
            output_file.unlink(missing_ok=True)
    except Exception:
        text = ''

    if proc.returncode == 2:
        raise PermanentCodexRunnerError('Codex CLI 인수 오류 (exit=2) — 설정 확인 필요')
    if proc.returncode != 0 and not text:
        raise CodexRunnerError(
            f'Codex 실행 실패 (exit={proc.returncode}): {stderr_text[:300] or stdout_text[:300]}'
        )
    if not text:
        text = stdout_text.strip()
    if not text:
        raise CodexRunnerError('Codex 응답 텍스트 없음')

    try:
        from runners.cost_tracker import record_call
        model_label = use_model or 'codex'
        if use_effort:
            model_label = f'{model_label}:{use_effort}'
        record_call(runner='codex', model=model_label, prompt=prompt, response=text)
    except Exception:
        pass
    return text
