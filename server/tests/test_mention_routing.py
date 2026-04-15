# _route_agent_mentions — 멘션 감지/라우팅 규칙 단위 테스트.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def office_stub(tmp_path, monkeypatch):
  from memory.team_memory import TeamMemory
  import db.suggestion_store as store

  monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'sugg.db')

  from log_bus.event_bus import LogEvent

  office = MagicMock()
  office.team_memory = TeamMemory(tmp_path / 'team.json')

  # _emit은 실제 구현처럼 LogEvent를 반환해야 source_log_id 전파가 가능
  async def _fake_emit(agent_id, message, event_type='message'):
    return LogEvent(agent_id=agent_id, event_type=event_type, message=message)

  office._emit = AsyncMock(side_effect=_fake_emit)
  office._file_commitment_suggestion = AsyncMock()

  # 대상 에이전트들
  def _mk_agent():
    a = MagicMock()
    a.respond_to = AsyncMock(return_value='확인했습니다. 반영하겠습니다.')
    return a

  office.agents = {
    'planner': _mk_agent(),
    'designer': _mk_agent(),
    'developer': _mk_agent(),
    'qa': _mk_agent(),
  }
  return office


@pytest.mark.asyncio
async def test_teamlead_mention_uses_claude(office_stub):
  '''@팀장 멘션은 run_claude_isolated로 라우팅된다 (agent.respond_to 경로 아님).'''
  from orchestration import agent_interactions

  with patch(
    'runners.claude_runner.run_claude_isolated',
    new_callable=AsyncMock,
  ) as mock_claude:
    mock_claude.return_value = '네, 확인했습니다.'
    await agent_interactions._route_agent_mentions(
      office_stub, speaker='developer',
      content='@팀장 이 부분 검토 부탁드립니다.',
    )

  mock_claude.assert_called_once()
  # teamlead 응답 emit 되었는지
  emit_targets = [c.args[0] for c in office_stub._emit.await_args_list]
  assert 'teamlead' in emit_targets


@pytest.mark.asyncio
async def test_self_mention_ignored(office_stub):
  '''본인 멘션은 무시된다 (speaker == target).'''
  from orchestration import agent_interactions

  await agent_interactions._route_agent_mentions(
    office_stub, speaker='developer',
    content='@튜링 자문자답 코멘트입니다.',
  )

  office_stub.agents['developer'].respond_to.assert_not_called()


@pytest.mark.asyncio
async def test_max_three_mentions(office_stub):
  '''멘션이 많아도 최대 3명까지만 라우팅된다.'''
  from orchestration import agent_interactions

  content = (
    '@기획자 A 부탁드립니다. '
    '@디자이너 B 검토해주세요. '
    '@QA C 테스트 부탁합니다. '
    '@튜링 D 개발 부탁드립니다.'
  )
  with patch(
    'runners.claude_runner.run_claude_isolated',
    new_callable=AsyncMock,
  ):
    await agent_interactions._route_agent_mentions(
      office_stub, speaker='planner', content=content,
    )

  called = [
    aid for aid, agent in office_stub.agents.items()
    if agent.respond_to.await_count > 0
  ]
  # speaker(planner) 제외 + 최대 3 슬롯 → 3명 이하
  assert len(called) <= 3
  assert 'planner' not in called


@pytest.mark.asyncio
async def test_mention_triggers_commitment_filing(office_stub):
  '''멘션 응답이 성공하면 _file_commitment_suggestion이 호출된다.'''
  from orchestration import agent_interactions

  await agent_interactions._route_agent_mentions(
    office_stub, speaker='planner',
    content='@튜링 이 기능 테스트 커버리지 챙겨주세요.',
  )

  office_stub._file_commitment_suggestion.assert_awaited_once()
  kwargs = office_stub._file_commitment_suggestion.await_args.kwargs
  assert kwargs['committer_id'] == 'developer'
  assert kwargs['source_speaker'] == 'planner'
  # source_log_id는 응답 emit 이벤트의 UUID가 전파되어야 함
  assert kwargs.get('source_log_id')
  assert len(kwargs['source_log_id']) >= 16
