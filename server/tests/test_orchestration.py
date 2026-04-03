# ORCH-01: Claude 팀장 오케스트레이션 테스트
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def loop_setup(tmp_path):
  '''OrchestrationLoop 테스트용 fixture — 모든 외부 의존성을 tmp_path로 격리'''
  from bus.message_bus import MessageBus
  from log_bus.event_bus import EventBus
  from workspace.manager import WorkspaceManager
  from runners.ollama_runner import OllamaRunner
  from orchestration.router import MessageRouter
  from orchestration.loop import OrchestrationLoop

  bus = MessageBus(db_path=str(tmp_path / 'test.db'))
  ev_bus = EventBus()
  ws = WorkspaceManager(task_id='test-task', workspace_root=str(tmp_path / 'workspace'))
  runner = OllamaRunner()
  router = MessageRouter(bus=bus, event_bus=ev_bus)
  loop = OrchestrationLoop(
    bus=bus,
    runner=runner,
    event_bus=ev_bus,
    workspace=ws,
    router=router,
    memory_root=tmp_path / 'memory',
  )
  return loop, bus, runner


@pytest.mark.asyncio
async def test_claude_analyzes_user_instruction(loop_setup):
  '''Claude가 사용자 지시를 파싱하여 기획자에게 task_request를 전달한다 (ORCH-01)'''
  loop, bus, runner = loop_setup

  with patch('orchestration.loop.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
    mock_claude.return_value = '{"direction": "홈페이지 기획을 시작하세요"}'
    msg = await loop.analyze_instruction('홈페이지 만들어줘')

  # run_claude_isolated()가 1회 호출돼야 함
  mock_claude.assert_called_once()
  # 반환 메시지가 planner에게 전달돼야 함
  assert msg.to_agent == 'planner'


@pytest.mark.asyncio
async def test_claude_routes_only_to_planner(loop_setup):
  '''Claude는 작업자에게 직접 지시하지 않고 반드시 기획자를 경유한다 (ORCH-01, D-04)'''
  loop, bus, runner = loop_setup

  with patch('orchestration.loop.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
    mock_claude.return_value = '{"direction": "기획을 시작하세요"}'
    msg = await loop.analyze_instruction('웹사이트 만들어줘')

  # to_agent가 반드시 planner여야 함 (D-04 위반 없음)
  assert msg.to_agent == 'planner'
  # developer, designer, qa 등 작업자에게 직접 전달하지 않음
  assert msg.to_agent not in ('developer', 'designer', 'qa')


@pytest.mark.asyncio
async def test_memory_inject_on_run_agent(loop_setup, tmp_path):
  '''_run_agent() 실행 시 이전 경험이 system_prompt에 주입된다 (AMEM-02, D-03)'''
  from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
  from memory.agent_memory import MemoryRecord

  loop, bus, runner = loop_setup
  # _task_graph 초기화 (loop.run() 없이 직접 호출 시 필요)
  loop._task_graph = TaskGraph()

  # AgentMemory.load_relevant가 경험 1건을 반환하도록 mock
  mock_experience = MemoryRecord(
    task_id='prev-task-001',
    task_type='developer',
    success=False,
    feedback='JSON 응답 형식 오류 발생',
    tags=['json_error'],
    timestamp='2026-04-03T00:00:00+00:00',
  )

  # runner.generate_json mock — system 인자를 캡처하기 위해 AsyncMock 사용
  runner.generate_json = AsyncMock(return_value={
    'status': 'success',
    'artifact_paths': [],
    'summary': '작업 완료',
    'failure_reason': None,
  })

  with patch('orchestration.loop.AgentMemory') as MockAgentMemory:
    mock_mem_instance = MagicMock()
    mock_mem_instance.load_relevant.return_value = [mock_experience]
    mock_mem_instance.record = MagicMock()
    MockAgentMemory.return_value = mock_mem_instance

    # TaskNode 생성 후 task_graph에 등록
    from bus.payloads import TaskRequestPayload
    payload = TaskRequestPayload(
      task_id='task-001',
      description='API 개발',
      requirements='REST API를 구현하라',
      assigned_to='developer',
      depends_on=[],
    )
    loop._task_graph.add_task(payload)
    loop._task_graph.update_status('task-001', TaskStatus.PROCESSING)
    node = loop._task_graph._nodes['task-001']

    await loop._run_agent(node)

  # runner.generate_json에 전달된 system 인자 확인
  call_kwargs = runner.generate_json.call_args
  system_arg = call_kwargs.kwargs.get('system') or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else '')

  # '## 이전 경험' 섹션이 system_prompt에 포함돼야 함
  assert '## 이전 경험' in system_arg, f'system_prompt에 이전 경험이 없음: {system_arg!r}'
  assert 'JSON 응답 형식 오류 발생' in system_arg


@pytest.mark.asyncio
async def test_memory_inject_no_experience(loop_setup):
  '''_run_agent() 경험이 없을 때 system_prompt는 기존과 동일하다 (AMEM-02)'''
  from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus

  loop, bus, runner = loop_setup
  # _task_graph 초기화 (loop.run() 없이 직접 호출 시 필요)
  loop._task_graph = TaskGraph()

  runner.generate_json = AsyncMock(return_value={
    'status': 'success',
    'artifact_paths': [],
    'summary': '완료',
    'failure_reason': None,
  })

  with patch('orchestration.loop.AgentMemory') as MockAgentMemory:
    mock_mem_instance = MagicMock()
    mock_mem_instance.load_relevant.return_value = []  # 경험 없음
    mock_mem_instance.record = MagicMock()
    MockAgentMemory.return_value = mock_mem_instance

    from bus.payloads import TaskRequestPayload
    payload = TaskRequestPayload(
      task_id='task-002',
      description='테스트 작업',
      requirements='요구사항',
      assigned_to='developer',
      depends_on=[],
    )
    loop._task_graph.add_task(payload)
    loop._task_graph.update_status('task-002', TaskStatus.PROCESSING)
    node = loop._task_graph._nodes['task-002']

    await loop._run_agent(node)

  # system_prompt에 '## 이전 경험' 없어야 함
  call_kwargs = runner.generate_json.call_args
  system_arg = call_kwargs.kwargs.get('system') or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else '')
  assert '## 이전 경험' not in system_arg


@pytest.mark.asyncio
async def test_memory_record_on_qa_fail(loop_setup):
  '''QA 불합격 시 즉시 해당 에이전트의 실패 경험이 기록된다 (AMEM-03, D-05)'''
  from orchestration.task_graph import TaskNode, TaskStatus

  loop, bus, runner = loop_setup

  # QA가 실패 응답 반환하도록 runner mock 설정
  runner.generate_json = AsyncMock(return_value={
    'status': 'fail',
    'failure_reason': 'API 응답 형식 불일치',
  })

  with patch('orchestration.loop.AgentMemory') as MockAgentMemory:
    mock_mem_instance = MagicMock()
    mock_mem_instance.record = MagicMock()
    MockAgentMemory.return_value = mock_mem_instance

    node = TaskNode(
      task_id='task-003',
      description='API 개발',
      requirements='요구사항',
      assigned_to='developer',
      depends_on=[],
    )
    node.artifact_paths = []

    result = await loop._run_qa_gate(node)

  # QA 불합격 확인
  assert result is False

  # record() 호출 확인 — success=False, tags=['qa_fail']
  mock_mem_instance.record.assert_called_once()
  call_args = mock_mem_instance.record.call_args[0][0]
  assert call_args.success is False
  assert 'qa_fail' in call_args.tags
