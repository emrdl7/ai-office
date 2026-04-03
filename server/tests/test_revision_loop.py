# ORCH-04: Claude 최종 검증 및 보완 루프 테스트
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def loop_setup(tmp_path):
  '''OrchestrationLoop 테스트용 fixture'''
  from bus.message_bus import MessageBus
  from log_bus.event_bus import EventBus
  from workspace.manager import WorkspaceManager
  from runners.ollama_runner import OllamaRunner
  from orchestration.router import MessageRouter
  from orchestration.loop import OrchestrationLoop
  from orchestration.task_graph import TaskGraph

  bus = MessageBus(db_path=str(tmp_path / 'test.db'))
  ev_bus = EventBus()
  ws = WorkspaceManager(task_id='test-task', workspace_root=str(tmp_path / 'workspace'))
  runner = OllamaRunner()
  router = MessageRouter(bus=bus, event_bus=ev_bus)
  loop = OrchestrationLoop(bus=bus, runner=runner, event_bus=ev_bus, workspace=ws, router=router)
  graph = TaskGraph()
  return loop, graph


@pytest.mark.asyncio
async def test_claude_final_verification_pass(loop_setup):
  '''Claude 최종 검증이 PASS 응답 시 COMPLETED 상태로 전환된다 (ORCH-04)'''
  from orchestration.loop import WorkflowState
  loop, graph = loop_setup

  with patch('runners.claude_runner.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
    mock_claude.return_value = '모든 요구사항을 충족합니다. PASS'
    result = await loop._claude_final_verify(graph)

  assert result is True
  assert loop._state == WorkflowState.COMPLETED


@pytest.mark.asyncio
async def test_claude_final_verification_fail_triggers_revision(loop_setup):
  '''Claude 최종 검증 불합격 시 revision_count 증가 및 REVISION_LOOPING 상태 전환 (ORCH-04, D-10)'''
  from orchestration.loop import WorkflowState
  loop, graph = loop_setup

  with patch('runners.claude_runner.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
    mock_claude.return_value = '요구사항을 충족하지 못합니다. FAIL — 디자인 보완 필요'
    result = await loop._claude_final_verify(graph)

  assert result is False
  assert loop._revision_count == 1
  assert loop._state == WorkflowState.REVISION_LOOPING


@pytest.mark.asyncio
async def test_max_revision_rounds_escalates(loop_setup):
  '''최대 반복 횟수(3) 초과 시 ESCALATED 상태로 전환된다 (ORCH-04, D-12)'''
  from orchestration.loop import WorkflowState, OrchestrationLoop
  loop, graph = loop_setup

  # revision_count를 MAX_REVISION_ROUNDS와 동일하게 설정
  loop._revision_count = OrchestrationLoop.MAX_REVISION_ROUNDS

  with patch('runners.claude_runner.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
    mock_claude.return_value = '여전히 미흡합니다. FAIL'
    result = await loop._claude_final_verify(graph)

  assert result is False
  assert loop._state == WorkflowState.ESCALATED
