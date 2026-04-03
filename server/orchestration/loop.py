# 오케스트레이션 루프 — 전체 워크플로우 상태 머신 (ORCH-01, ORCH-04, WKFL-02)
# Claude 분석 → 기획자 → 작업자 → QA → Claude 최종검증 → 보완 루프
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
from orchestration.router import MessageRouter
from runners.claude_runner import run_claude_isolated
from runners.ollama_runner import OllamaRunner
from bus.message_bus import MessageBus
from bus.schemas import AgentMessage
from bus.payloads import TaskRequestPayload, TaskResultPayload
from log_bus.event_bus import EventBus, LogEvent
from workspace.manager import WorkspaceManager
from memory.agent_memory import AgentMemory, MemoryRecord

# 에이전트 시스템 프롬프트 파일 디렉토리 (프로젝트 루트 agents/)
AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'


class WorkflowState(str, Enum):
  '''오케스트레이션 워크플로우 상태 열거형'''
  IDLE = 'idle'                                     # 초기 대기 상태
  CLAUDE_ANALYZING = 'claude_analyzing'             # Claude 사용자 지시 분석 중
  PLANNER_PLANNING = 'planner_planning'             # 기획자 태스크 분해 중
  WORKER_EXECUTING = 'worker_executing'             # 작업자 태스크 실행 중
  QA_REVIEWING = 'qa_reviewing'                     # QA 게이트 검수 중
  CLAUDE_FINAL_VERIFYING = 'claude_final_verifying' # Claude 최종 검증 중
  REVISION_LOOPING = 'revision_looping'             # 보완 루프 — 재기획 진입 전
  COMPLETED = 'completed'                           # 워크플로우 완료
  ESCALATED = 'escalated'                           # 최대 반복 횟수 초과 에스컬레이션


class OrchestrationLoop:
  '''전체 워크플로우 상태 머신.

  Claude 분석 → 기획자 → 작업자 → QA → Claude 최종검증 → 보완 루프의
  전체 흐름을 상태 머신으로 관리한다.

  MAX_REVISION_ROUNDS 초과 시 ESCALATED 상태로 전환하여 루프를 종료한다 (D-11, D-12).
  '''

  MAX_REVISION_ROUNDS = 3  # 최대 보완 반복 횟수 (D-11, D-12)

  def __init__(
    self,
    bus: MessageBus,
    runner: OllamaRunner,
    event_bus: EventBus,
    workspace: WorkspaceManager,
    router: MessageRouter,
    memory_root: str | Path = 'data/memory',
  ):
    self.bus = bus
    self.runner = runner
    self.event_bus = event_bus
    self.workspace = workspace
    self.router = router
    self._state = WorkflowState.IDLE
    self._revision_count = 0
    self._task_graph: TaskGraph | None = None
    self._memory_root = Path(memory_root)

  async def _emit_status(self, state: WorkflowState) -> None:
    '''상태 변경 이벤트를 이벤트 버스에 발행한다'''
    await self.event_bus.publish(LogEvent(
      agent_id='orchestrator',
      event_type='status_change',
      message=f'상태: {state.value}',
    ))

  def _load_agent_prompt(self, agent_name: str) -> str:
    '''agents/{agent_name}.md 파일을 읽어 시스템 프롬프트를 반환한다.

    파일이 없을 경우 빈 문자열을 반환한다.
    '''
    prompt_path = AGENTS_DIR / f'{agent_name}.md'
    if prompt_path.exists():
      return prompt_path.read_text(encoding='utf-8')
    return ''

  async def run(self, user_instruction: str) -> WorkflowState:
    '''전체 오케스트레이션 루프를 실행한다.

    상태 전이 순서:
    1. IDLE → CLAUDE_ANALYZING: Claude 지시 분석
    2. CLAUDE_ANALYZING → PLANNER_PLANNING: 기획자 태스크 분해
    3. PLANNER_PLANNING → WORKER_EXECUTING: 작업자 태스크 실행
    4. WORKER_EXECUTING → QA_REVIEWING: QA 게이트 검수
    5. QA_REVIEWING → CLAUDE_FINAL_VERIFYING (all_done()) 또는 재작업
    6. CLAUDE_FINAL_VERIFYING → COMPLETED | REVISION_LOOPING
    7. REVISION_LOOPING: MAX 초과 시 ESCALATED, 아니면 PLANNER_PLANNING 재진입

    Returns:
        최종 WorkflowState (COMPLETED 또는 ESCALATED)
    '''
    self._task_graph = TaskGraph()

    # 1. IDLE → CLAUDE_ANALYZING
    self._state = WorkflowState.CLAUDE_ANALYZING
    await self._emit_status(self._state)
    await self.analyze_instruction(user_instruction)

    # 2. CLAUDE_ANALYZING → PLANNER_PLANNING
    while True:
      self._state = WorkflowState.PLANNER_PLANNING
      await self._emit_status(self._state)
      await self._run_planner()

      # 3. PLANNER_PLANNING → WORKER_EXECUTING
      self._state = WorkflowState.WORKER_EXECUTING
      await self._emit_status(self._state)

      # ready_tasks 순회 — 각 작업자 실행
      while True:
        ready = self._task_graph.ready_tasks()
        if not ready:
          break
        for node in ready:
          self._task_graph.update_status(node.task_id, TaskStatus.PROCESSING)
          await self._run_agent(node)

          # 4. WORKER_EXECUTING → QA_REVIEWING
          self._state = WorkflowState.QA_REVIEWING
          await self._emit_status(self._state)
          qa_passed = await self._run_qa_gate(node)

          if not qa_passed:
            # QA 불합격 — 해당 태스크 FAILED로 표시
            self._task_graph.update_status(
              node.task_id,
              TaskStatus.FAILED,
              failure_reason=node.failure_reason,
            )
          else:
            self._task_graph.update_status(node.task_id, TaskStatus.DONE)

      # 5. QA_REVIEWING → CLAUDE_FINAL_VERIFYING (모든 태스크 완료 시)
      if self._task_graph.all_done():
        self._state = WorkflowState.CLAUDE_FINAL_VERIFYING
        await self._emit_status(self._state)
        passed = await self._claude_final_verify(self._task_graph)

        if passed:
          # 6a. COMPLETED
          break
        else:
          # 6b. REVISION_LOOPING 또는 ESCALATED
          if self._state == WorkflowState.ESCALATED:
            break
          # REVISION_LOOPING → PLANNER_PLANNING 재진입
          # revision_count 리셋 및 task_graph 초기화
          self._task_graph = TaskGraph()
          continue
      else:
        # 태스크가 없거나 모두 완료되지 않은 경우 루프 종료
        self._state = WorkflowState.COMPLETED
        await self._emit_status(self._state)
        break

    return self._state

  async def _run_planner(self) -> None:
    '''기획자 에이전트를 실행하여 태스크를 분해하고 task_graph에 추가한다.

    기획자 응답을 파싱하여 각 태스크를 TaskGraph에 등록한다.
    응답 파싱 실패 시 기본 태스크를 하나 추가한다.
    '''
    system_prompt = self._load_agent_prompt('planner')
    prompt = '태스크 목록을 JSON으로 응답하라.'

    result = await self.runner.generate_json(prompt, system=system_prompt)

    if result and isinstance(result, dict) and 'tasks' in result:
      for task_data in result['tasks']:
        payload = TaskRequestPayload(
          task_id=task_data.get('task_id', ''),
          description=task_data.get('description', ''),
          requirements=task_data.get('requirements', ''),
          assigned_to=task_data.get('assigned_to', 'developer'),
          depends_on=task_data.get('depends_on', []),
        )
        self._task_graph.add_task(payload)

  async def _run_agent(self, node: TaskNode) -> TaskResultPayload | None:
    '''에이전트를 실행하여 태스크를 처리하고 결과를 workspace에 저장한다.

    Args:
        node: 실행할 TaskNode

    Returns:
        TaskResultPayload 또는 실패 시 None
    '''
    system_prompt = self._load_agent_prompt(node.assigned_to)

    # 이전 경험 주입 (AMEM-02, D-03)
    memory = AgentMemory(node.assigned_to, memory_root=self._memory_root)
    task_type = node.assigned_to  # 에이전트 이름을 task_type으로 활용
    experiences = memory.load_relevant(task_type=task_type, limit=5)
    if experiences:
      lines = []
      for exp in experiences:
        status_str = '성공' if exp.success else '실패'
        lines.append(f'- [{status_str}] {exp.feedback} (태그: {", ".join(exp.tags)})')
      system_prompt += '\n\n## 이전 경험\n' + '\n'.join(lines)

    # 원본 요구사항과 작업 지시를 함께 전달
    prompt = (
      f'[작업 지시]\n{node.description}\n\n'
      f'[원본 요구사항]\n{node.requirements}'
    )

    result_data = await self.runner.generate_json(prompt, system=system_prompt)

    if result_data and isinstance(result_data, dict):
      try:
        result = TaskResultPayload(
          task_id=node.task_id,
          status=result_data.get('status', 'fail'),
          artifact_paths=result_data.get('artifact_paths', []),
          summary=result_data.get('summary', ''),
          failure_reason=result_data.get('failure_reason'),
        )
      except Exception:
        result = TaskResultPayload(
          task_id=node.task_id,
          status='fail',
          artifact_paths=[],
          summary='에이전트 응답 파싱 실패',
          failure_reason='결과 파싱 오류',
        )
    else:
      result = TaskResultPayload(
        task_id=node.task_id,
        status='fail',
        artifact_paths=[],
        summary='에이전트 응답 없음',
        failure_reason='generate_json() 반환값 없음',
      )

    # workspace에 결과 저장
    try:
      self.workspace.write_artifact(
        f'{node.task_id}/result.json',
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
      )
    except Exception:
      pass  # workspace 저장 실패는 태스크 결과에 영향 없음

    # task_graph 업데이트
    if result.status == 'success':
      self._task_graph.update_status(
        node.task_id,
        TaskStatus.DONE,
        artifact_paths=result.artifact_paths,
      )
      # 성공 경험 기록 (AMEM-01: 성공 패턴도 저장)
      success_memory = AgentMemory(node.assigned_to, memory_root=self._memory_root)
      success_memory.record(MemoryRecord(
        task_id=node.task_id,
        task_type=node.assigned_to,
        success=True,
        feedback=result.summary,
        tags=['success'],
        timestamp=datetime.now(timezone.utc).isoformat(),
      ))
    else:
      self._task_graph.update_status(
        node.task_id,
        TaskStatus.FAILED,
        failure_reason=result.failure_reason,
      )

    return result

  async def _run_qa_gate(self, node: TaskNode) -> bool:
    '''QA 게이트 — 원본 요구사항 대비 작업 결과물을 검수한다 (D-08, Pattern 4).

    확증편향 방지: QA는 결과물만 보지 않고 반드시 원본 요구사항 대비 검증한다.

    Args:
        node: 검수할 TaskNode

    Returns:
        QA 통과 시 True, 불합격 시 False (node.failure_reason에 이유 설정)
    '''
    system_prompt = self._load_agent_prompt('qa')

    # Pattern 4 — 확증편향 방지 프롬프트
    prompt = (
      f'[원본 요구사항]\n{node.requirements}\n\n'
      f'[작업 결과물 경로]\n{node.artifact_paths}\n\n'
      '위 원본 요구사항을 기준으로 작업 결과물을 검수하라.\n'
      '결과물만 보고 판단하지 말고 반드시 원본 요구사항 대비 검증하라.'
    )

    result_data = await self.runner.generate_json(prompt, system=system_prompt)

    if result_data and isinstance(result_data, dict):
      if result_data.get('status') == 'success':
        return True
      else:
        # 불합격 — failure_reason을 노드에 기록
        node.failure_reason = result_data.get('failure_reason', 'QA 불합격')
        # QA 불합격 즉시 경험 기록 (AMEM-03, D-05)
        memory = AgentMemory(node.assigned_to, memory_root=self._memory_root)
        memory.record(MemoryRecord(
          task_id=node.task_id,
          task_type=node.assigned_to,
          success=False,
          feedback=node.failure_reason,
          tags=['qa_fail'],
          timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        return False

    # 응답 없음 — 안전하게 실패 처리
    node.failure_reason = 'QA 응답 없음'
    return False

  async def _claude_final_verify(self, task_graph: TaskGraph) -> bool:
    '''Claude 최종 검증 — 산출물이 원본 요구사항을 충족하는지 검증한다 (ORCH-04).

    PASS 응답 시: COMPLETED 상태 전환, True 반환
    FAIL 응답 시: revision_count 증가
      - MAX_REVISION_ROUNDS 초과: ESCALATED 상태 전환, False 반환
      - 초과 전: REVISION_LOOPING 상태 전환, False 반환

    Args:
        task_graph: 완료된 태스크 그래프

    Returns:
        검증 통과 시 True, 불합격 시 False
    '''
    # 모든 완료 태스크의 artifact_paths 수집
    artifact_summary = '\n'.join(
      f'- {node.task_id}: {node.artifact_paths}'
      for node in task_graph._nodes.values()
      if node.status == TaskStatus.DONE
    )

    prompt = (
      f'[산출물 목록]\n{artifact_summary}\n\n'
      '위 산출물이 원본 요구사항을 충족하는지 검증하라. '
      'PASS 또는 FAIL과 함께 이유를 명시하라.'
    )

    response = await run_claude_isolated(prompt)

    # 대소문자 무관 PASS/FAIL 확인
    response_upper = response.upper()
    if 'PASS' in response_upper:
      self._state = WorkflowState.COMPLETED
      await self._emit_status(self._state)
      return True
    else:
      # FAIL 또는 응답 불명확 — 불합격 처리
      # Claude 보완 지시 즉시 경험 기록 (AMEM-03, D-06)
      for node in task_graph._nodes.values():
        if node.status == TaskStatus.DONE:
          mem = AgentMemory(node.assigned_to, memory_root=self._memory_root)
          mem.record(MemoryRecord(
            task_id=node.task_id,
            task_type=node.assigned_to,
            success=False,
            feedback=f'Claude 최종검증 불합격: {response[:200]}',
            tags=['claude_revision'],
            timestamp=datetime.now(timezone.utc).isoformat(),
          ))
      self._revision_count += 1
      if self._revision_count >= self.MAX_REVISION_ROUNDS:
        # 최대 반복 횟수 초과 → 에스컬레이션 (D-12)
        self._state = WorkflowState.ESCALATED
        await self._emit_status(self._state)
      else:
        # 보완 루프 재진입 (D-10)
        self._state = WorkflowState.REVISION_LOOPING
        await self._emit_status(self._state)
      return False

  async def analyze_instruction(self, instruction: str) -> AgentMessage:
    '''사용자 지시를 분석하여 기획자에게 진행방향 메시지를 발행한다 (ORCH-01, D-04).

    Claude CLI를 통해 지시를 분석하고, 반드시 기획자(planner)에게만 전달한다.
    Claude는 작업자에게 직접 지시하지 않는다 (D-04).

    Args:
        instruction: 사용자 지시 텍스트

    Returns:
        AgentMessage (to_agent='planner')
    '''
    prompt = (
      f'다음 사용자 지시를 분석하여 기획자에게 전달할 작업 방향을 JSON으로 응답하라: '
      f'{instruction}'
    )

    response = await run_claude_isolated(prompt)

    # AgentMessage 생성 — 반드시 planner에게만 전달 (D-04)
    msg = AgentMessage(
      type='task_request',
      **{'from': 'claude', 'to': 'planner'},
      payload={'claude_analysis': response, 'original_instruction': instruction},
    )

    await self.router.route(msg)
    return msg
