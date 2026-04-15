# Office 오케스트레이션 테스트
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def office_setup(tmp_path):
    '''Office 테스트용 fixture — 모든 외부 의존성을 tmp_path로 격리'''
    from bus.message_bus import MessageBus
    from log_bus.event_bus import EventBus
    from workspace.manager import WorkspaceManager
    from orchestration.office import Office

    bus = MessageBus(db_path=str(tmp_path / 'test.db'))
    ev_bus = EventBus()
    ws = WorkspaceManager(
        task_id='test-task', workspace_root=str(tmp_path / 'workspace')
    )
    office = Office(
        bus=bus,
        event_bus=ev_bus,
        workspace=ws,
        memory_root=tmp_path / 'memory',
    )
    return office, bus


@pytest.mark.asyncio
async def test_conversation_intent_direct_response(office_setup):
    '''대화 의도일 때 팀장이 직접 응답한다 (팀원 소집 없음)'''
    office, bus = office_setup

    with patch('orchestration.intent.run_claude_isolated', new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = '[CONVERSATION]\n저는 AI Office의 팀장입니다.'
        result = await office.receive('너 누구야?')

    assert result['state'] == 'completed'
    assert 'AI Office' in result['response']
    assert result['artifacts'] == []


@pytest.mark.asyncio
async def test_quick_task_routes_to_single_agent(office_setup):
    '''단순 요청은 담당 팀원 한 명에게만 전달된다'''
    office, bus = office_setup

    # project_runner 내부 LLM 호출(peer 기여·팀장 검수) mock — 재작업 루프 방지
    async def _fake_claude(prompt, *args, **kwargs):
        # peer 기여(second_opinion)는 "없음"으로 스킵, 팀장 검수는 PASS
        if '합격이면' in prompt:
            return '[PASS] 검수 완료'
        return '없음'

    with patch('orchestration.intent.run_claude_isolated', new_callable=AsyncMock) as mock_intent, \
         patch('orchestration.project_runner.run_claude_isolated', side_effect=_fake_claude):
        mock_intent.return_value = '[QUICK_TASK:developer]\n이 코드를 분석하세요.'

        # developer와 qa agent의 handle을 mock — QA 루프가 재작업을 트리거하지 않도록
        office.agents['developer'].handle = AsyncMock(return_value='코드 분석 결과입니다.')
        office.agents['qa'].handle = AsyncMock(
            return_value='{"status":"success","summary":"검수 통과","failure_reason":"","severity":"none"}'
        )

        result = await office.receive('이 코드 분석해줘')

    assert result['state'] == 'completed'
    assert '코드 분석 결과' in result['response']
    # 담당 에이전트(developer)만 handle 호출 — 다른 에이전트는 routing 되지 않음
    office.agents['developer'].handle.assert_called_once()
    for name, agent in office.agents.items():
        if name in ('developer', 'qa'):
            continue
        if hasattr(agent.handle, 'assert_not_called'):
            agent.handle.assert_not_called()


@pytest.mark.asyncio
async def test_project_triggers_meeting(office_setup):
    '''프로젝트 의도일 때 회의가 소집된다'''
    office, bus = office_setup

    with patch('orchestration.intent.run_claude_isolated', new_callable=AsyncMock) as mock_intent:
        mock_intent.return_value = '[PROJECT]\n사이트 리뉴얼 프로젝트입니다.'

        # 회의 및 이후 단계 mock
        with patch.object(office, '_handle_project', new_callable=AsyncMock) as mock_project:
            mock_project.return_value = {
                'state': 'completed',
                'response': '프로젝트 산출물',
                'artifacts': ['final/result.md'],
            }
            result = await office.receive('사이트 리뉴얼 기획해줘')

    assert result['state'] == 'completed'
    mock_project.assert_called_once()


@pytest.mark.asyncio
async def test_agents_have_personalities(office_setup):
    '''각 에이전트가 성격 섹션이 포함된 시스템 프롬프트를 갖는다'''
    office, bus = office_setup

    for name, agent in office.agents.items():
        prompt = agent._build_system_prompt()
        # 모든 에이전트에 성격 섹션이 있어야 함
        assert '## 성격' in prompt, f'{name} 에이전트에 성격 섹션이 없습니다'
        assert '## 판단력' in prompt, f'{name} 에이전트에 판단력 섹션이 없습니다'


@pytest.mark.asyncio
async def test_agent_can_speak_in_meeting(office_setup):
    '''에이전트가 회의에서 자기 관점으로 발언할 수 있다'''
    office, bus = office_setup

    planner = office.agents['planner']

    # planner는 Gemini 1차 → Sonnet 폴백 순으로 러너를 사용
    with patch('orchestration.agent.run_gemini', new_callable=AsyncMock) as mock_gemini:
        mock_gemini.return_value = '기획 관점에서 사용자 조사가 먼저 필요합니다.'
        opinion = await planner.speak('사이트 리뉴얼')

    assert len(opinion) > 0
    mock_gemini.assert_called_once()
