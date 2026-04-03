# ORCH-03: 메시지 payload 스키마 테스트
import pytest
from bus.payloads import TaskRequestPayload, TaskResultPayload, StatusUpdatePayload


def test_task_request_payload_schema():
  '''TaskRequestPayload가 Pydantic 모델로 유효성 검사된다 (ORCH-03)'''
  payload = TaskRequestPayload(
    description='x',
    requirements='y',
    assigned_to='developer',
  )
  assert payload.description == 'x'
  assert payload.requirements == 'y'
  assert payload.assigned_to == 'developer'
  assert isinstance(payload.task_id, str)
  assert payload.depends_on == []


def test_task_result_payload_schema():
  '''TaskResultPayload가 Pydantic 모델로 유효성 검사된다 (ORCH-03)'''
  payload = TaskResultPayload(
    task_id='t1',
    status='success',
    summary='done',
  )
  assert payload.task_id == 't1'
  assert payload.status == 'success'
  assert payload.summary == 'done'
  assert payload.artifact_paths == []
  assert payload.failure_reason is None


def test_status_update_payload_schema():
  '''StatusUpdatePayload가 Pydantic 모델로 유효성 검사된다 (ORCH-03)'''
  payload = StatusUpdatePayload(
    task_id='t1',
    state='done',
    agent_id='planner',
  )
  assert payload.task_id == 't1'
  assert payload.state == 'done'
  assert payload.agent_id == 'planner'
  assert payload.note == ''
