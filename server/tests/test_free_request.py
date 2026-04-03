# WKFL-03: 에이전트 간 자유 작업 요청 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 2에서 구현')
def test_developer_can_request_designer():
  '''개발자가 디자이너에게 작업 요청을 보낼 수 있다 (WKFL-03, D-06)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 2에서 구현')
def test_free_request_goes_through_message_bus():
  '''자유 요청은 메시지 버스를 경유한다 (WKFL-03, D-06)'''
  assert False, '미구현'
