# _run_with_backoff 통합 테스트 — 실제 subprocess(가짜 claude CLI)로 재시도 동작 E2E 검증
#
# 단위 테스트(test_code_patcher_backoff.py)는 run_claude_isolated를 mock하므로
# subprocess 생성·JSON 파싱·오류 감지 경로는 실제로 실행되지 않는다.
# 이 파일은 가짜 claude 스크립트를 직접 실행해 실제 호출 체인을 검증한다.
import asyncio
import os
import stat
import textwrap

import pytest
import runners.claude_runner as runner_mod
from improvement.code_patcher import _run_with_backoff
from runners.claude_runner import ClaudeRunnerError, PermanentClaudeRunnerError


@pytest.fixture
def fail_once_claude(tmp_path):
    """첫 호출 exit=1(응답 없음), 두 번째 정상 JSON을 반환하는 가짜 claude CLI."""
    counter = tmp_path / 'n.txt'
    counter.write_text('0')
    script = tmp_path / 'claude'
    script.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        n=$(cat {counter}); echo $((n+1)) > {counter}
        if [ "$n" -lt 1 ]; then exit 1; fi
        printf '{{"type":"result","result":"통합 재시도 성공"}}\\n'
    """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.fixture
def permanent_fail_claude(tmp_path):
    """항상 exit=2(CLI 인수 오류)로 종료하는 가짜 claude CLI."""
    script = tmp_path / 'claude'
    script.write_text('#!/bin/bash\nexit 2\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.asyncio
async def test_integration_retry_through_real_subprocess(fail_once_claude, monkeypatch):
    """실제 subprocess 호출 체인: 첫 번째 실패 → 재시도 → 성공."""
    monkeypatch.setattr(runner_mod, 'CLAUDE_CLI', fail_once_claude)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    # asyncio.sleep만 mock — run_claude_isolated는 실제 실행
    import improvement.code_patcher as patcher_mod
    monkeypatch.setattr(patcher_mod.asyncio, 'sleep', fake_sleep)

    result = await _run_with_backoff('integ-01', 'dummy prompt', timeout=10.0, max_turns=1)

    assert '통합 재시도 성공' in result
    assert len(sleep_calls) == 1, f'재시도 1회 → sleep 1회여야 함, 실제: {sleep_calls}'
    assert sleep_calls[0] == 2.0, f'첫 대기는 2s여야 함, 실제: {sleep_calls[0]}'


@pytest.mark.asyncio
async def test_integration_permanent_error_not_retried(permanent_fail_claude, monkeypatch):
    """exit=2(CLI 인수 오류)는 PermanentClaudeRunnerError로 즉시 실패 — 재시도 없음."""
    monkeypatch.setattr(runner_mod, 'CLAUDE_CLI', permanent_fail_claude)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    import improvement.code_patcher as patcher_mod
    monkeypatch.setattr(patcher_mod.asyncio, 'sleep', fake_sleep)

    with pytest.raises(PermanentClaudeRunnerError):
        await _run_with_backoff('integ-02', 'dummy prompt', timeout=10.0, max_turns=1)

    assert len(sleep_calls) == 0, f'영구 오류는 재시도 없어야 함, 실제 sleep: {sleep_calls}'
