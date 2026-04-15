# TeamDynamic 기록 훅 — peer_review, commitment 경로.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from memory.team_memory import TeamMemory


@pytest.fixture
def team_memory(tmp_path):
  tm = TeamMemory(tmp_path / 'team.json')
  return tm


@pytest.fixture
def office_stub(team_memory, tmp_path, monkeypatch):
  '''Office 클래스의 메서드를 호출하기 위한 최소 스텁.'''
  import db.suggestion_store as store
  monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'sugg.db')

  office = MagicMock()
  office.team_memory = team_memory
  office._phase_feedback = []
  office._PEER_REVIEWERS = {'developer': ['designer', 'planner']}
  office._emit = AsyncMock()

  # 실제 Office의 _record_dynamic 로직 재현
  from datetime import datetime, timezone
  from memory.team_memory import TeamDynamic
  def _record_dynamic(from_agent, to_agent, dynamic_type, description):
    if not from_agent or not to_agent or from_agent == to_agent:
      return
    team_memory.add_dynamic(TeamDynamic(
      from_agent=from_agent, to_agent=to_agent, dynamic_type=dynamic_type,
      description=description[:100],
      timestamp=datetime.now(timezone.utc).isoformat(),
    ))
  office._record_dynamic = _record_dynamic
  return office


@pytest.mark.asyncio
async def test_peer_review_records_dynamic(office_stub, team_memory):
  '''peer_review의 리뷰 결과는 TeamDynamic (peer_concern / peer_approved)로 기록된다.'''
  from orchestration import agent_interactions

  async def fake_claude(prompt, **kw):
    # 첫 리뷰어는 우려, 두 번째는 긍정
    if '디자이너' in prompt or 'designer' in prompt:
      return '레이아웃 구조에 이슈 있어 보입니다 [CONCERN]'
    return '기획 관점에서 문제없어 보입니다'

  with patch('orchestration.agent_interactions.run_claude_isolated', side_effect=fake_claude):
    await agent_interactions._peer_review(
      office_stub, worker_name='developer', phase_name='개발',
      content='코드 초안', user_input='프로젝트 요청',
    )

  dynamics = team_memory.get_dynamics_for('developer')
  types_for_dev = sorted(d.dynamic_type for d in dynamics)
  assert 'peer_concern' in types_for_dev or 'peer_approved' in types_for_dev
  # 최소 1명의 리뷰어 → 작업자 방향
  assert any(d.to_agent == 'developer' for d in dynamics)


@pytest.mark.asyncio
async def test_commitment_records_committed_to_request(office_stub, team_memory):
  '''_file_commitment_suggestion은 committer → source_speaker로 committed_to_request 기록.'''
  from orchestration import suggestion_filer

  # office_stub에 Office의 실제 forwarder 동작 재현 불필요 — _record_dynamic만 호출
  await suggestion_filer._file_commitment_suggestion(
    office_stub,
    committer_id='developer',
    message='네, 반영하겠습니다. 테스트 커버리지 챙기겠습니다.',
    source_speaker='planner',
    source_message='QA 기준 강화 부탁드립니다',
  )

  dynamics = team_memory.get_dynamics_for('developer')
  committed = [d for d in dynamics if d.dynamic_type == 'committed_to_request']
  assert len(committed) == 1
  assert committed[0].from_agent == 'developer'
  assert committed[0].to_agent == 'planner'
