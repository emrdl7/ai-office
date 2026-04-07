# QA 게이트 검수 테스트
import pytest
from unittest.mock import AsyncMock

from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
from bus.payloads import TaskRequestPayload


@pytest.fixture
def office_setup(tmp_path):
    '''Office + QA 테스트용 fixture'''
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

    # 테스트용 TaskNode 생성
    graph = TaskGraph()
    payload = TaskRequestPayload(
        task_id='qa-test-task',
        description='테스트 작업',
        requirements='홈페이지에 반응형 디자인이 적용되어야 한다',
        assigned_to='developer',
    )
    node = graph.add_task(payload)
    node.artifact_paths = ['workspace/qa-test-task/result.md']

    return office, node


@pytest.mark.asyncio
async def test_qa_receives_original_requirements(office_setup):
    '''QA 에이전트가 원본 요구사항을 참조한다'''
    office, node = office_setup

    # qa agent의 handle을 mock
    office.agents['qa'].handle = AsyncMock(
        return_value='{"status": "success", "summary": "검수 통과", "failure_reason": null}'
    )

    result = await office._run_qa_check(office.agents['qa'], node, '테스트 산출물 내용')

    # handle()에 requirements가 포함된 프롬프트 전달됐는지 확인
    call_args = office.agents['qa'].handle.call_args
    prompt_arg = call_args[0][0]
    assert node.requirements in prompt_arg


@pytest.mark.asyncio
async def test_qa_fail_returns_failure_reason(office_setup):
    '''QA 불합격 시 failure_reason이 설정된다'''
    office, node = office_setup

    office.agents['qa'].handle = AsyncMock(
        return_value='{"status": "fail", "summary": "반응형 미적용", "failure_reason": "모바일 뷰포트 미대응"}'
    )

    result = await office._run_qa_check(office.agents['qa'], node, '산출물')

    assert result is False
    assert '모바일 뷰포트' in node.failure_reason
