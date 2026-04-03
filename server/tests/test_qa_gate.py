# WKFL-02: QA 게이트 검수 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_qa_receives_original_requirements():
  '''QA 에이전트가 원본 요구사항을 독립적으로 참조한다 (WKFL-02, D-08)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_qa_fail_returns_failure_reason():
  '''QA 불합격 시 failure_reason이 구체적으로 포함된다 (WKFL-02, D-09)'''
  assert False, '미구현'
