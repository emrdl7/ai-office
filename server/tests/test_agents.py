# ORCH-02: 에이전트 시스템 프롬프트 파일 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_planner_has_system_prompt():
  '''기획자 시스템 프롬프트 파일이 존재하고 필수 섹션을 포함한다 (ORCH-02)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_all_agents_have_system_prompts():
  '''4개 에이전트 모두 시스템 프롬프트 파일이 존재한다 (ORCH-02)'''
  assert False, '미구현'
