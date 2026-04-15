# _single_agent_chat 단위 테스트 — Round 1 PASS / 멘션 강제응답 / Round 2 컨텍스트.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def office():
  agent = MagicMock()
  agent._build_system_prompt = MagicMock(return_value='[시스템 프롬프트]')
  office = MagicMock()
  office.agents = {'planner': agent}
  office._emit = AsyncMock()
  return office


@pytest.mark.asyncio
async def test_pass_returns_empty(office):
  '''응답이 [PASS]면 빈 문자열을 반환한다.'''
  from orchestration.agent_interactions import _single_agent_chat
  with patch(
    'orchestration.agent_interactions.run_claude_isolated',
    new_callable=AsyncMock,
  ) as mock_claude:
    mock_claude.return_value = '[PASS]'
    name, content = await _single_agent_chat(
      office, 'planner', '잡담', ['[사용자] 잡담'], mentioned_ids=[],
    )
  assert name == 'planner'
  assert content == ''


@pytest.mark.asyncio
async def test_mention_forces_response(office):
  '''멘션된 에이전트는 반드시 응답(강제응답 프롬프트)을 받는다.'''
  from orchestration.agent_interactions import _single_agent_chat
  with patch(
    'orchestration.agent_interactions.run_claude_isolated',
    new_callable=AsyncMock,
  ) as mock_claude:
    mock_claude.return_value = '네, 확인했습니다.'
    name, content = await _single_agent_chat(
      office, 'planner', '@기획자 확인해주세요',
      ['[사용자] @기획자 확인해주세요'], mentioned_ids=['planner'],
    )
  assert content == '네, 확인했습니다.'
  # 멘션 전용 프롬프트에 "반드시 응답" 포함
  called_prompt = mock_claude.await_args.args[0]
  assert '반드시 응답하세요' in called_prompt


@pytest.mark.asyncio
async def test_round2_includes_round1_context(office):
  '''round_context가 주어지면 [라운드 1 발언] 섹션이 프롬프트에 포함된다.'''
  from orchestration.agent_interactions import _single_agent_chat
  with patch(
    'orchestration.agent_interactions.run_claude_isolated',
    new_callable=AsyncMock,
  ) as mock_claude:
    mock_claude.return_value = '추가 의견 있습니다.'
    await _single_agent_chat(
      office, 'planner', '잡담',
      ['[사용자] 잡담'], mentioned_ids=[],
      round_context='[designer] 디자이너 의견입니다.',
    )
  called_prompt = mock_claude.await_args.args[0]
  assert '[라운드 1 발언]' in called_prompt
  assert '디자이너 의견입니다' in called_prompt
