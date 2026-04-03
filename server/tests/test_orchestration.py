# ORCH-01: Claude 팀장 오케스트레이션 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_claude_analyzes_user_instruction():
  '''Claude가 사용자 지시를 파싱하여 기획자에게 task_request를 전달한다 (ORCH-01)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_claude_routes_only_to_planner():
  '''Claude는 작업자에게 직접 지시하지 않고 반드시 기획자를 경유한다 (ORCH-01, D-04)'''
  assert False, '미구현'
