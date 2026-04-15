# _archive_loop 복원성 — 한쪽 실패 시 다른 아카이브 작업이 계속 동작한다.
import asyncio
import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_message_bus_failure_does_not_skip_chat_logs(monkeypatch):
  '''message bus archive가 예외를 던져도 chat_logs archive는 실행된다.'''
  import main
  from db import log_store

  monkeypatch.setattr(
    main.message_bus, 'archive_old_messages',
    MagicMock(side_effect=RuntimeError('bus boom')),
  )
  chat_calls: list[int] = []

  def _fake_archive(days):
    chat_calls.append(days)
    return 0

  monkeypatch.setattr(log_store, 'maybe_archive_logs', _fake_archive)

  async def _no_wait(_):
    raise asyncio.CancelledError

  monkeypatch.setattr(main.asyncio, 'sleep', _no_wait)

  await main._archive_loop()

  assert chat_calls == [30]


@pytest.mark.asyncio
async def test_chat_logs_failure_does_not_kill_loop(monkeypatch):
  '''chat_logs archive 실패해도 다음 iteration(다음 sleep)까지 루프가 살아 있다.'''
  import main
  from db import log_store

  bus_calls: list[int] = []

  def _fake_bus():
    bus_calls.append(1)
    return 0

  monkeypatch.setattr(main.message_bus, 'archive_old_messages', _fake_bus)
  monkeypatch.setattr(
    log_store, 'maybe_archive_logs',
    MagicMock(side_effect=RuntimeError('logs boom')),
  )

  sleep_calls = 0

  async def _limited_sleep(_):
    nonlocal sleep_calls
    sleep_calls += 1
    # 2회 iteration까지 실행 후 취소
    if sleep_calls >= 2:
      raise asyncio.CancelledError

  monkeypatch.setattr(main.asyncio, 'sleep', _limited_sleep)

  await main._archive_loop()

  # bus archive가 2회 호출되었으면 chat_logs 실패 후에도 루프가 지속된 것
  assert len(bus_calls) == 2
