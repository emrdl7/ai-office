# WKFL-04: 기획자 PM 추적 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 2에서 구현')
def test_planner_receives_broadcast_copy():
  '''모든 에이전트 간 메시지의 broadcast 복사가 기획자에게 전달된다 (WKFL-04)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 2에서 구현')
def test_planner_tracks_all_task_states():
  '''기획자가 전체 에이전트의 태스크 상태를 추적한다 (WKFL-04, D-06)'''
  assert False, '미구현'
