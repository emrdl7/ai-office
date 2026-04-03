# WKFL-01: 태스크 그래프(DAG) 테스트
import pytest
from bus.payloads import TaskRequestPayload
from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus


def make_payload(**kwargs) -> TaskRequestPayload:
  '''TaskRequestPayload 생성 헬퍼'''
  defaults = {
    'description': '테스트 태스크',
    'requirements': '테스트 요구사항',
    'assigned_to': 'developer',
  }
  defaults.update(kwargs)
  return TaskRequestPayload(**defaults)


def test_task_graph_creates_node():
  '''TaskGraph에 노드를 추가할 수 있다 (WKFL-01)'''
  graph = TaskGraph()
  payload = make_payload(description='디자인 작업')
  node = graph.add_task(payload)

  # add_task가 TaskNode를 반환해야 함
  assert isinstance(node, TaskNode)
  assert node.task_id == payload.task_id

  # get_task로 동일 노드를 찾을 수 있어야 함
  found = graph.get_task(payload.task_id)
  assert found is not None
  assert found.task_id == payload.task_id
  assert found.description == '디자인 작업'


def test_task_graph_tracks_status():
  '''태스크 상태(pending/processing/done/failed)를 추적한다 (WKFL-01)'''
  graph = TaskGraph()
  payload = make_payload()
  node = graph.add_task(payload)

  # 초기 상태는 PENDING
  assert node.status == TaskStatus.PENDING

  # 상태를 DONE으로 변경
  graph.update_status(payload.task_id, TaskStatus.DONE)
  updated = graph.get_task(payload.task_id)
  assert updated.status == TaskStatus.DONE


def test_task_graph_dependency_order():
  '''의존성이 있는 태스크는 선행 태스크 완료 후 실행 가능 상태가 된다 (WKFL-01, D-05)'''
  graph = TaskGraph()

  # t1 생성 (의존성 없음)
  p1 = make_payload(description='t1 작업', assigned_to='developer')
  graph.add_task(p1)
  t1_id = p1.task_id

  # t2 생성 (t1에 의존)
  p2 = make_payload(description='t2 작업', assigned_to='developer')
  # depends_on은 TaskGraph.add_task에서 처리
  p2_with_dep = TaskRequestPayload(
    task_id=p2.task_id,
    description=p2.description,
    requirements=p2.requirements,
    assigned_to=p2.assigned_to,
    depends_on=[t1_id],
  )
  graph.add_task(p2_with_dep)

  # t1이 DONE이 아니면 t2는 ready_tasks에 없어야 함
  ready = graph.ready_tasks()
  ready_ids = [n.task_id for n in ready]
  assert t1_id in ready_ids         # t1은 의존성 없으므로 ready
  assert p2.task_id not in ready_ids  # t2는 t1 완료 전이라 not ready

  # t1을 DONE으로 변경 후 t2가 ready_tasks에 포함돼야 함
  graph.update_status(t1_id, TaskStatus.DONE)
  ready_after = graph.ready_tasks()
  ready_after_ids = [n.task_id for n in ready_after]
  assert p2.task_id in ready_after_ids


def test_task_graph_ready_tasks_empty_deps():
  '''depends_on=[] 이면 즉시 ready_tasks()에 포함됨 (WKFL-01)'''
  graph = TaskGraph()
  payload = make_payload(depends_on=[])
  node = graph.add_task(payload)

  ready = graph.ready_tasks()
  assert node.task_id in [n.task_id for n in ready]
