# 팀장 배치 리뷰 집계 — _summarize_team_dynamics + run_single fallback.
# NOTE: orchestration.teamlead_review 는 4월 리팩터링에서 제거됨 — 전체 skip.
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

pytestmark = pytest.mark.skip(reason='orchestration.teamlead_review 제거됨 (2026-04 리팩터링)')

from memory.team_memory import TeamMemory, TeamDynamic


def _add(tm, frm, to, dt, desc='x'):
  tm.add_dynamic(TeamDynamic(
    from_agent=frm, to_agent=to, dynamic_type=dt,
    description=desc, timestamp=datetime.now(timezone.utc).isoformat(),
  ))


def test_summarize_top_pairs(tmp_path):
  '''상위 8쌍을 카운트 내림차순으로 노출.'''
  from orchestration.teamlead_review import _summarize_team_dynamics
  tm = TeamMemory(tmp_path / 't.json')
  for _ in range(3):
    _add(tm, 'designer', 'developer', 'peer_approved')
  _add(tm, 'planner', 'developer', 'consulted')

  office = MagicMock()
  office.team_memory = tm
  text = _summarize_team_dynamics(office)
  assert 'designer→developer' in text
  assert '[peer_approved]' in text
  # peer_approved 3회가 consulted 1회보다 위에 출현
  assert text.index('designer→developer') < text.index('planner→developer')


def test_summarize_concern_warning(tmp_path):
  '''같은 쌍 peer_concern 2회+ 는 별도 경고 섹션.'''
  from orchestration.teamlead_review import _summarize_team_dynamics
  tm = TeamMemory(tmp_path / 't.json')
  for _ in range(3):
    _add(tm, 'designer', 'developer', 'peer_concern')

  office = MagicMock()
  office.team_memory = tm
  text = _summarize_team_dynamics(office)
  assert '반복적 우려 쌍' in text
  assert 'peer_concern 3회' in text


def test_summarize_empty(tmp_path):
  from orchestration.teamlead_review import _summarize_team_dynamics
  tm = TeamMemory(tmp_path / 't.json')
  office = MagicMock()
  office.team_memory = tm
  assert '집계 데이터 없음' in _summarize_team_dynamics(office)


@pytest.mark.asyncio
async def test_run_single_skips_below_threshold(tmp_path):
  '''force=False, fresh<30이면 조기 반환 (gemini 호출 없음).'''
  from orchestration import teamlead_review

  office = MagicMock()
  office._load_digest_state = MagicMock(return_value={'last_reviewed_ts': '', 'last_run_ts': '', 'history': []})

  with patch('orchestration.teamlead_review.run_gemini', new_callable=AsyncMock) as mock_gem, \
       patch('db.log_store.load_logs', return_value=[
         {'agent_id': 'a', 'event_type': 'autonomous', 'message': 'x', 'timestamp': '2026-01-01T00:00:00Z'},
       ]):
    await teamlead_review.run_single(office, force=False)

  mock_gem.assert_not_called()
