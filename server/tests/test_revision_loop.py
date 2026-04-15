# 팀장 최종 검수 및 보완 루프 테스트
# TODO: Office 생성자가 크게 바뀌어 이 테스트는 구식. 신규 리뷰/보완 흐름은
# test_qa_pushback_loop, test_retrospective 가 커버한다. 재작성 전까지 skip.
import pytest

pytestmark = pytest.mark.skip(reason='stale — removed runners.gemma_runner, Office 시그니처 변경')

from unittest.mock import AsyncMock, patch


@pytest.fixture
def office_setup(tmp_path):
    '''Office 테스트용 fixture'''
    from bus.message_bus import MessageBus
    from log_bus.event_bus import EventBus
    from workspace.manager import WorkspaceManager
    from runners.gemma_runner import GemmaRunner
    from orchestration.office import Office

    bus = MessageBus(db_path=str(tmp_path / 'test.db'))
    ev_bus = EventBus()
    ws = WorkspaceManager(
        task_id='test-task', workspace_root=str(tmp_path / 'workspace')
    )
    runner = GemmaRunner()
    office = Office(
        bus=bus, runner=runner, event_bus=ev_bus, workspace=ws,
        memory_root=tmp_path / 'memory',
    )
    return office


@pytest.mark.asyncio
async def test_teamlead_review_pass(office_setup, tmp_path):
    '''팀장 검수 통과 시 True를 반환한다'''
    office = office_setup

    # 최종 산출물 파일 생성
    final_dir = tmp_path / 'workspace' / 'test-task' / 'final'
    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / 'result.md').write_text('a' * 3000)

    from orchestration.task_graph import TaskGraph
    graph = TaskGraph()

    with patch('orchestration.office.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = '[PASS] 모든 요구사항을 충족합니다.'
        result = await office._teamlead_final_review('테스트 지시', graph)

    assert result is True


@pytest.mark.asyncio
async def test_teamlead_review_fail(office_setup, tmp_path):
    '''팀장 검수 불합격 시 False를 반환하고 피드백이 저장된다'''
    office = office_setup

    final_dir = tmp_path / 'workspace' / 'test-task' / 'final'
    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / 'result.md').write_text('a' * 3000)

    from orchestration.task_graph import TaskGraph
    graph = TaskGraph()

    with patch('orchestration.office.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = '[FAIL] 디자인 섹션이 피상적입니다.'
        result = await office._teamlead_final_review('테스트 지시', graph)

    assert result is False
    assert '디자인 섹션' in office._last_review_feedback


@pytest.mark.asyncio
async def test_max_revision_escalates(office_setup):
    '''최대 보완 횟수 초과 시 ESCALATED 상태가 된다'''
    from orchestration.office import Office
    office = office_setup
    assert office.MAX_REVISION_ROUNDS == 3
