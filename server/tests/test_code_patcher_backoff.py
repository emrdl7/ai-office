# _run_with_backoff 단위 테스트 — 지수 백오프·에러 분기·이벤트 발행 검증
import pytest
from unittest.mock import AsyncMock, patch

from improvement.code_patcher import _run_with_backoff, _RETRY_MAX, _RETRY_MAX_DELAY
from runners.claude_runner import ClaudeRunnerError, ClaudeTimeoutError


async def test_success_on_first_attempt():
    """첫 시도 성공 → 재시도 없이 결과 반환."""
    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               return_value='응답') as mock_run, \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        result = await _run_with_backoff('s1', 'prompt', 60.0, 3)

    assert result == '응답'
    mock_run.assert_awaited_once()
    mock_sleep.assert_not_awaited()


async def test_retry_on_runner_error_then_success():
    """ClaudeRunnerError 후 재시도 성공 → 호출 횟수 2회, sleep 1회."""
    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               side_effect=[ClaudeRunnerError('오류'), '재시도 성공']) as mock_run, \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
         patch('improvement.code_patcher.event_bus') as mock_bus:
        mock_bus.publish = AsyncMock()
        result = await _run_with_backoff('s2', 'prompt', 60.0, 3)

    assert result == '재시도 성공'
    assert mock_run.await_count == 2
    mock_sleep.assert_awaited_once_with(2.0)  # min(2^1, 30) = 2.0


async def test_exponential_backoff_delays():
    """재시도마다 지수적으로 증가하는 대기 시간: 2s → 4s → 8s."""
    side_effects = [ClaudeRunnerError('오류')] * _RETRY_MAX + ['최종 성공']
    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               side_effect=side_effects), \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
         patch('improvement.code_patcher.event_bus') as mock_bus:
        mock_bus.publish = AsyncMock()
        result = await _run_with_backoff('s3', 'prompt', 60.0, 3)

    assert result == '최종 성공'
    delays = [c.args[0] for c in mock_sleep.await_args_list]
    assert delays == [2.0, 4.0, 8.0]  # min(2^1,30), min(2^2,30), min(2^3,30)


async def test_timeout_not_retried():
    """ClaudeTimeoutError는 재시도 없이 즉시 전파된다."""
    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               side_effect=ClaudeTimeoutError('타임아웃')) as mock_run, \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(ClaudeTimeoutError):
            await _run_with_backoff('s4', 'prompt', 60.0, 3)

    mock_run.assert_awaited_once()
    mock_sleep.assert_not_awaited()


async def test_exceeds_max_retries_raises_error():
    """최대 재시도 초과 시 ClaudeRunnerError('재시도 … 초과') 발생."""
    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               side_effect=ClaudeRunnerError('API 과부하')) as mock_run, \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock), \
         patch('improvement.code_patcher.event_bus') as mock_bus:
        mock_bus.publish = AsyncMock()
        with pytest.raises(ClaudeRunnerError, match='재시도.*초과'):
            await _run_with_backoff('s5', 'prompt', 60.0, 3)

    assert mock_run.await_count == 1 + _RETRY_MAX


async def test_event_emitted_on_retry():
    """재시도 시 event_bus에 경고 이벤트가 1회 발행된다."""
    published = []

    async def capture(event):
        published.append(event)

    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               side_effect=[ClaudeRunnerError('오류'), '성공']), \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock), \
         patch('improvement.code_patcher.event_bus') as mock_bus:
        mock_bus.publish = capture
        await _run_with_backoff('s6', 'prompt', 60.0, 3)

    assert len(published) == 1
    assert 's6' in published[0].message
    assert '재시도' in published[0].message


async def test_delay_capped_at_max_delay():
    """대기 시간이 _RETRY_MAX_DELAY 상한을 초과하지 않는다."""
    side_effects = [ClaudeRunnerError('오류')] * _RETRY_MAX + ['성공']
    with patch('improvement.code_patcher.run_claude_isolated', new_callable=AsyncMock,
               side_effect=side_effects), \
         patch('improvement.code_patcher.asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
         patch('improvement.code_patcher.event_bus') as mock_bus, \
         patch('improvement.code_patcher._RETRY_BASE', 1000.0):
        mock_bus.publish = AsyncMock()
        await _run_with_backoff('s7', 'prompt', 60.0, 3)

    delays = [c.args[0] for c in mock_sleep.await_args_list]
    assert all(d <= _RETRY_MAX_DELAY for d in delays)
    assert all(d == _RETRY_MAX_DELAY for d in delays)  # 1000^n >> 30 → 항상 상한값
