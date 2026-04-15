# handle_mid_work_input이 팀장/에이전트 응답의 다짐을 _file_commitment_suggestion에 흘리는지 검증.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.user_input import handle_mid_work_input


def _mk_office():
  office = MagicMock()
  office._emit = AsyncMock()
  office._file_commitment_suggestion = AsyncMock()
  office._user_mid_feedback = []
  office.agents = {}
  return office


@pytest.mark.asyncio
async def test_default_ack_fires_commitment():
  office = _mk_office()
  await handle_mid_work_input(office, '이 부분 좀 확인해줘')
  office._file_commitment_suggestion.assert_awaited_once()
  kwargs = office._file_commitment_suggestion.await_args.kwargs
  assert kwargs['committer_id'] == 'teamlead'
  assert kwargs['source_speaker'] == 'user'
  assert '반영하겠' in kwargs['message']


@pytest.mark.asyncio
async def test_teamlead_mention_response_fires_commitment():
  office = _mk_office()
  with patch(
    'orchestration.user_input.run_claude_isolated',
    new=AsyncMock(return_value='네, 바로 반영하겠습니다.'),
  ):
    await handle_mid_work_input(office, '@잡스 이거 확인해줘')
  office._file_commitment_suggestion.assert_awaited_once()
  kwargs = office._file_commitment_suggestion.await_args.kwargs
  assert kwargs['committer_id'] == 'teamlead'


@pytest.mark.asyncio
async def test_stop_command_skips_commitment():
  office = _mk_office()
  await handle_mid_work_input(office, '중단해줘')
  office._file_commitment_suggestion.assert_not_awaited()
