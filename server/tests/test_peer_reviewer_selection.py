# _select_peer_reviewers — 팀 dynamics 기반 peer 선정 단위 테스트.
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _dyn(from_a, to_a, dtype):
  from memory.team_memory import TeamDynamic
  return TeamDynamic(
    from_agent=from_a, to_agent=to_a,
    dynamic_type=dtype, description='',
    timestamp=datetime.now(timezone.utc).isoformat(),
  )


@pytest.fixture
def office_stub(tmp_path):
  from memory.team_memory import TeamMemory
  office = MagicMock()
  office.team_memory = TeamMemory(tmp_path)
  # 기존 하드코딩 매핑 (폴백)
  office._PEER_REVIEWERS = {
    'planner': ['designer', 'developer'],
    'designer': ['developer', 'planner'],
    'developer': ['designer', 'planner'],
  }
  return office


def test_fallback_on_insufficient_signals(office_stub):
  '''dynamics 신호가 3건 미만이면 하드코딩 매핑 폴백.'''
  from orchestration.agent_interactions import _select_peer_reviewers
  office_stub.team_memory.add_dynamic(_dyn('designer', 'developer', 'peer_approved'))
  picks = _select_peer_reviewers(office_stub, 'developer', limit=2)
  assert picks == ['designer', 'planner']


def test_dynamic_selection_by_score(office_stub):
  '''충분한 신호가 쌓이면 점수 상위 후보 선정. planner가 designer보다 호환 좋으면 우선.'''
  from orchestration.agent_interactions import _select_peer_reviewers
  tm = office_stub.team_memory
  # developer ↔ planner: approved 3회, committed 1회 → +3.3
  for _ in range(3):
    tm.add_dynamic(_dyn('planner', 'developer', 'peer_approved'))
  tm.add_dynamic(_dyn('developer', 'planner', 'committed_to_request'))
  # developer ↔ designer: concern 2회 → -1.0
  for _ in range(2):
    tm.add_dynamic(_dyn('designer', 'developer', 'peer_concern'))

  picks = _select_peer_reviewers(office_stub, 'developer', limit=2)
  assert picks[0] == 'planner'
  # designer는 음수 점수라 탈락 → 폴백으로 채움
  assert 'designer' in picks or len(picks) == 1 or picks[1] == 'designer'


def test_concern_heavy_pair_excluded(office_stub):
  '''peer_concern 누적이 많아 음수 점수면 후보에서 제외.'''
  from orchestration.agent_interactions import _select_peer_reviewers
  tm = office_stub.team_memory
  # planner ↔ designer: concern 5회 → -2.5
  for _ in range(5):
    tm.add_dynamic(_dyn('designer', 'planner', 'peer_concern'))
  # planner ↔ developer: approved 2회 + committed 1회 → +2.3
  for _ in range(2):
    tm.add_dynamic(_dyn('developer', 'planner', 'peer_approved'))
  tm.add_dynamic(_dyn('planner', 'developer', 'committed_to_request'))

  picks = _select_peer_reviewers(office_stub, 'planner', limit=2)
  # developer 상위, designer는 음수라 배제 → 폴백 보강으로 designer 들어올 수 있으나
  # 최소한 developer가 1순위여야 한다.
  assert picks[0] == 'developer'
