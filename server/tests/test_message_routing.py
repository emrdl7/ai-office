# ORCH-03: 메시지 payload 스키마 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_task_request_payload_schema():
  '''TaskRequestPayload가 Pydantic 모델로 유효성 검사된다 (ORCH-03)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_task_result_payload_schema():
  '''TaskResultPayload가 Pydantic 모델로 유효성 검사된다 (ORCH-03)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_status_update_payload_schema():
  '''StatusUpdatePayload가 Pydantic 모델로 유효성 검사된다 (ORCH-03)'''
  assert False, '미구현'
