# INFR-02: Claude CLI subprocess 러너 테스트
# 실제 Claude CLI 호출은 로컬 환경 의존 → unittest.mock.AsyncMock 사용
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from runners.claude_runner import run_claude_isolated, ClaudeRunnerError


def _make_stream_json_output(text: str) -> bytes:
    '''테스트용 stream-json 응답 생성'''
    event = {
        'type': 'assistant',
        'message': {
            'content': [{'type': 'text', 'text': text}]
        }
    }
    return json.dumps(event).encode() + b'\n'


@pytest.fixture
def mock_proc_success(monkeypatch):
    '''성공적인 Claude subprocess mock'''
    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(
            return_value=(
                _make_stream_json_output('테스트 응답'),
                b'',
            )
        )
        return proc

    monkeypatch.setattr(
        'runners.claude_runner.asyncio.create_subprocess_exec',
        fake_subprocess,
    )


@pytest.fixture
def mock_proc_failure(monkeypatch):
    '''실패하는 Claude subprocess mock'''
    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(
            return_value=(b'', b'Claude CLI error: not found')
        )
        return proc

    monkeypatch.setattr(
        'runners.claude_runner.asyncio.create_subprocess_exec',
        fake_subprocess,
    )


async def test_run_claude_returns_text(mock_proc_success):
    '''Claude subprocess가 텍스트 응답을 반환 (INFR-02)'''
    result = await run_claude_isolated('테스트 프롬프트')
    assert result == '테스트 응답'


async def test_bare_flag_in_subprocess_command(monkeypatch):
    '''subprocess 명령에 --bare 플래그가 포함됨 (D-05, D-06 토큰 격리)'''
    captured_args = []

    async def capture_subprocess(*args, **kwargs):
        captured_args.extend(args)
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b'', b''))
        return proc

    monkeypatch.setattr(
        'runners.claude_runner.asyncio.create_subprocess_exec',
        capture_subprocess,
    )

    await run_claude_isolated('test')

    assert '--bare' in captured_args
    assert '--print' in captured_args
    assert '--output-format' in captured_args
    assert 'stream-json' in captured_args
    assert '--no-session-persistence' in captured_args


async def test_isolation_dir_used_as_cwd(monkeypatch):
    '''격리 디렉토리가 subprocess cwd로 사용됨 (D-06)'''
    captured_kwargs = {}

    async def capture_subprocess(*args, **kwargs):
        captured_kwargs.update(kwargs)
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b'', b''))
        return proc

    monkeypatch.setattr(
        'runners.claude_runner.asyncio.create_subprocess_exec',
        capture_subprocess,
    )

    await run_claude_isolated('test')

    assert 'cwd' in captured_kwargs
    assert 'ai-office-claude-isolated' in captured_kwargs['cwd']


async def test_failure_raises_claude_runner_error(mock_proc_failure):
    '''subprocess 실패 시 ClaudeRunnerError 발생'''
    with pytest.raises(ClaudeRunnerError, match='Claude CLI 실패'):
        await run_claude_isolated('test')


async def test_invalid_json_lines_ignored(monkeypatch):
    '''파싱 불가 JSON-lines는 무시되고 유효한 부분만 반환'''
    async def fake_subprocess(*args, **kwargs):
        # 유효한 stream-json + 파싱 불가 라인 혼합
        output = b'not-json\n' + _make_stream_json_output('유효한 응답')
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(output, b''))
        return proc

    monkeypatch.setattr(
        'runners.claude_runner.asyncio.create_subprocess_exec',
        fake_subprocess,
    )

    result = await run_claude_isolated('test')
    assert result == '유효한 응답'
