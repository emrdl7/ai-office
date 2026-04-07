# WKFL-02: QA 게이트 검수 테스트
import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def loop_setup(tmp_path):
    """OrchestrationLoop 테스트용 fixture"""
    from bus.message_bus import MessageBus
    from log_bus.event_bus import EventBus
    from workspace.manager import WorkspaceManager
    from runners.gemma_runner import GemmaRunner
    from orchestration.router import MessageRouter
    from orchestration.loop import OrchestrationLoop
    from orchestration.task_graph import TaskGraph, TaskStatus
    from bus.payloads import TaskRequestPayload

    bus = MessageBus(db_path=str(tmp_path / "test.db"))
    ev_bus = EventBus()
    ws = WorkspaceManager(
        task_id="test-task", workspace_root=str(tmp_path / "workspace")
    )
    runner = GemmaRunner()
    router = MessageRouter(bus=bus, event_bus=ev_bus)
    loop = OrchestrationLoop(
        bus=bus, runner=runner, event_bus=ev_bus, workspace=ws, router=router
    )

    # 테스트용 TaskNode 생성
    graph = TaskGraph()
    payload = TaskRequestPayload(
        task_id="qa-test-task",
        description="테스트 작업",
        requirements="홈페이지에 반응형 디자인이 적용되어야 한다",
        assigned_to="developer",
    )
    node = graph.add_task(payload)
    node.artifact_paths = ["workspace/qa-test-task/result.json"]

    return loop, node


@pytest.mark.asyncio
async def test_qa_receives_original_requirements(loop_setup):
    """QA 에이전트가 원본 요구사항을 독립적으로 참조한다 (WKFL-02, D-08)"""
    loop, node = loop_setup

    # generate_json mock — 성공 응답
    loop.runner.generate_json = AsyncMock(
        return_value={"status": "success", "summary": "검수 통과"}
    )

    await loop._run_qa_gate(node)

    # generate_json()에 node.requirements가 포함된 프롬프트 전달됐는지 확인
    call_args = loop.runner.generate_json.call_args
    prompt_arg = call_args[0][0]  # 첫 번째 위치 인수 (prompt)
    assert node.requirements in prompt_arg, (
        f"원본 요구사항이 QA 프롬프트에 포함되지 않음: {prompt_arg}"
    )
    assert "원본 요구사항" in prompt_arg


@pytest.mark.asyncio
async def test_qa_fail_returns_failure_reason(loop_setup):
    """QA 불합격 시 failure_reason이 구체적으로 포함된다 (WKFL-02, D-09)"""
    loop, node = loop_setup

    # generate_json mock — 실패 응답
    loop.runner.generate_json = AsyncMock(
        return_value={
            "status": "fail",
            "failure_reason": "요구사항 미충족",
            "summary": "반응형 디자인 미적용",
        }
    )

    result = await loop._run_qa_gate(node)

    assert result is False
    assert node.failure_reason == "요구사항 미충족"
