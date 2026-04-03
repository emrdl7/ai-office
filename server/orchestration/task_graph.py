# 인메모리 DAG 태스크 상태 관리자 (WKFL-01)
# TaskGraph: 태스크 노드의 추가, 상태 추적, 의존성 기반 실행 순서 결정
from enum import Enum
from dataclasses import dataclass, field

from bus.payloads import TaskRequestPayload


class TaskStatus(str, Enum):
  '''태스크 실행 상태 열거형'''
  PENDING = 'pending'       # 실행 대기 중
  PROCESSING = 'processing' # 실행 중
  DONE = 'done'             # 완료
  FAILED = 'failed'         # 실패
  BLOCKED = 'blocked'       # 의존 태스크 미완료로 블록됨


@dataclass
class TaskNode:
  '''DAG 내 단일 태스크 노드'''
  task_id: str
  description: str
  requirements: str          # QA 독립 참조용 원본 요구사항 보존 (D-08)
  assigned_to: str
  depends_on: list[str] = field(default_factory=list)
  status: TaskStatus = TaskStatus.PENDING
  artifact_paths: list[str] = field(default_factory=list)
  failure_reason: str | None = None


class TaskGraph:
  '''인메모리 DAG 태스크 상태 관리자.

  태스크 노드를 추가하고 의존성 기반으로 실행 가능 태스크를 계산한다.
  WorkspaceManager와 연동하여 상태를 직렬화할 수 있다 (to_state_dict).
  '''

  def __init__(self):
    self._nodes: dict[str, TaskNode] = {}

  def add_task(self, payload: TaskRequestPayload) -> TaskNode:
    '''payload로 TaskNode를 생성하고 그래프에 추가한다.

    Args:
        payload: TaskRequestPayload — 태스크 요청 페이로드

    Returns:
        생성된 TaskNode
    '''
    node = TaskNode(
      task_id=payload.task_id,
      description=payload.description,
      requirements=payload.requirements,
      assigned_to=payload.assigned_to,
      depends_on=list(payload.depends_on),
    )
    self._nodes[payload.task_id] = node
    return node

  def get_task(self, task_id: str) -> TaskNode | None:
    '''task_id로 TaskNode를 조회한다.

    Returns:
        TaskNode 또는 None (존재하지 않는 경우)
    '''
    return self._nodes.get(task_id)

  def update_status(
    self,
    task_id: str,
    status: TaskStatus,
    **kwargs,
  ) -> None:
    '''태스크 상태를 변경하고 선택적으로 artifact_paths/failure_reason을 업데이트한다.

    Args:
        task_id: 상태를 변경할 태스크 ID
        status: 새 TaskStatus 값
        **kwargs: artifact_paths (list[str]), failure_reason (str | None) 선택 업데이트
    '''
    node = self._nodes.get(task_id)
    if node is None:
      raise KeyError(f'태스크를 찾을 수 없음: {task_id}')
    node.status = status
    if 'artifact_paths' in kwargs:
      node.artifact_paths = kwargs['artifact_paths']
    if 'failure_reason' in kwargs:
      node.failure_reason = kwargs['failure_reason']

  def ready_tasks(self) -> list[TaskNode]:
    '''실행 가능한 태스크 목록을 반환한다.

    조건: PENDING 상태이며 depends_on의 모든 task_id가 DONE 상태여야 한다.

    Returns:
        실행 가능한 TaskNode 목록
    '''
    result = []
    for node in self._nodes.values():
      if node.status != TaskStatus.PENDING:
        continue
      deps_done = all(
        self._nodes.get(dep_id, TaskNode(
          task_id=dep_id, description='', requirements='', assigned_to='',
          status=TaskStatus.PENDING,
        )).status == TaskStatus.DONE
        for dep_id in node.depends_on
      )
      if deps_done:
        result.append(node)
    return result

  def all_done(self) -> bool:
    '''모든 노드가 DONE 또는 FAILED 상태인지 확인한다.

    Returns:
        전체 노드가 완료(DONE/FAILED)이면 True
    '''
    if not self._nodes:
      return False
    return all(
      node.status in (TaskStatus.DONE, TaskStatus.FAILED)
      for node in self._nodes.values()
    )

  def to_state_dict(self) -> dict:
    '''직렬화 가능한 상태 딕셔너리를 반환한다.

    WorkspaceManager atomic write 연동용.

    Returns:
        태스크 상태 딕셔너리
    '''
    return {
      task_id: {
        'task_id': node.task_id,
        'description': node.description,
        'requirements': node.requirements,
        'assigned_to': node.assigned_to,
        'depends_on': node.depends_on,
        'status': node.status.value,
        'artifact_paths': node.artifact_paths,
        'failure_reason': node.failure_reason,
      }
      for task_id, node in self._nodes.items()
    }
