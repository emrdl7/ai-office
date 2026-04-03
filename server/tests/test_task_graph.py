# WKFL-01: 태스크 그래프(DAG) 테스트 stub
import pytest


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_task_graph_creates_node():
  '''TaskGraph에 노드를 추가할 수 있다 (WKFL-01)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_task_graph_tracks_status():
  '''태스크 상태(pending/processing/done/failed)를 추적한다 (WKFL-01)'''
  assert False, '미구현'


@pytest.mark.xfail(strict=False, reason='stub — Wave 1에서 구현')
def test_task_graph_dependency_order():
  '''의존성이 있는 태스크는 선행 태스크 완료 후 실행 가능 상태가 된다 (WKFL-01, D-05)'''
  assert False, '미구현'
