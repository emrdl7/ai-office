# ORCH-01: Claude 팀장 오케스트레이션 테스트
import pytest
from unittest.mock import AsyncMock, patch


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
  loop = OrchestrationLoop(bus=bus, runner=runner, event_bus=ev_bus, workspace=ws, router=router)
  return loop, bus, runner


@pytest.mark.asyncio
async def test_claude_analyzes_user_instruction(loop_setup):
  '''Claude가 사용자 지시를 파싱하여 기획자에게 task_request를 전달한다 (ORCH-01)'''
  loop, bus, runner = loop_setup

  with patch('runners.claude_runner.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
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

  with patch('runners.claude_runner.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
    mock_claude.return_value = '{"direction": "기획을 시작하세요"}'
    msg = await loop.analyze_instruction('웹사이트 만들어줘')

  # to_agent가 반드시 planner여야 함 (D-04 위반 없음)
  assert msg.to_agent == 'planner'
  # developer, designer, qa 등 작업자에게 직접 전달하지 않음
  assert msg.to_agent not in ('developer', 'designer', 'qa')
