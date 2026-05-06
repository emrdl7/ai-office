# Office 오케스트레이션 테스트
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


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


@pytest.fixture
def isolated_workreport_db(tmp_path, monkeypatch):
    from db import workreport_store

    monkeypatch.setattr(workreport_store, '_DB', tmp_path / 'workreport.db')
    workreport_store.init_db()
    return workreport_store


@pytest.mark.asyncio
async def test_conversation_intent_direct_response(office_setup):
    '''대화 의도일 때 비서가 직접 응답한다 (전문 역할 소집 없음)'''
    office, bus = office_setup

    with patch('orchestration.intent.run_claude_isolated', new_callable=AsyncMock) as mock_route, \
         patch('orchestration.intent.generate_teamlead_reply', new_callable=AsyncMock) as mock_reply:
        mock_route.return_value = '[CONVERSATION]'
        mock_reply.return_value = '저는 AI 오피스의 개인 업무 비서입니다.'
        result = await office.receive('너 누구야?')

    assert result['state'] == 'completed'
    assert 'AI 오피스' in result['response']
    assert result['artifacts'] == []


@pytest.mark.asyncio
async def test_natural_worklog_creates_task(office_setup, isolated_workreport_db):
    office, _ = office_setup

    result = await office.receive('랜딩 페이지 작업 시작')

    tasks = isolated_workreport_db.get_recent_tasks(5)
    assert result['state'] == 'completed'
    assert tasks[0]['task_name'] == '랜딩 페이지'
    assert tasks[0]['status'] == 'active'


@pytest.mark.asyncio
async def test_worklog_help_request_links_job(office_setup, isolated_workreport_db):
    office, _ = office_setup
    await office.receive('랜딩 페이지 작업 시작')

    with patch('orchestration.intent.map_to_job_spec', new_callable=AsyncMock) as mock_map, \
         patch('orchestration.office._generate_job_title', new_callable=AsyncMock) as mock_title, \
         patch('jobs.runner.submit', new_callable=AsyncMock) as mock_submit:
        mock_map.return_value = ('research', {'topic': '랜딩 페이지'}, 0.9)
        mock_title.return_value = '랜딩 페이지 리서치'
        mock_submit.return_value = SimpleNamespace(id='job-123', title='랜딩 페이지 리서치')

        result = await office.receive('도와줘')

    tasks = isolated_workreport_db.get_recent_tasks(5)
    assert result['state'] == 'completed'
    assert tasks[0]['linked_job_id'] == 'job-123'
    assert tasks[0]['status'] == 'delegated'


@pytest.mark.asyncio
async def test_worklog_followup_updates_recent_task(office_setup, isolated_workreport_db):
    office, _ = office_setup
    task = isolated_workreport_db.create_task(task_name='랜딩 페이지', progress=10)
    office._last_worklog_task = task

    result = await office.receive('이거 완료')

    updated = isolated_workreport_db.get_recent_tasks(1)[0]
    assert result['state'] == 'completed'
    assert updated['task_name'] == '랜딩 페이지'
    assert updated['progress'] == 100
    assert updated['status'] == 'done'


@pytest.mark.asyncio
async def test_worklog_followup_moves_recent_task_date(office_setup, isolated_workreport_db):
    office, _ = office_setup
    task = isolated_workreport_db.create_task(task_name='제안서 작성', progress=20)
    office._last_worklog_task = task

    result = await office.receive('이거 내일로 미뤄')

    from core.dates import kst_today
    from datetime import timedelta
    updated = isolated_workreport_db.get_recent_tasks(1)[0]
    assert result['state'] == 'completed'
    assert updated['date'] == (kst_today() + timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_worklog_followup_deletes_named_task(office_setup, isolated_workreport_db):
    office, _ = office_setup
    isolated_workreport_db.create_task(task_name='제안서 작성', progress=20)
    isolated_workreport_db.create_task(task_name='랜딩 페이지', progress=20)

    result = await office.receive('제안서 삭제')

    tasks = isolated_workreport_db.get_recent_tasks(10)
    assert result['state'] == 'completed'
    assert [t['task_name'] for t in tasks] == ['랜딩 페이지']


@pytest.mark.asyncio
async def test_worklog_followup_pauses_and_resumes_named_task(office_setup, isolated_workreport_db):
    office, _ = office_setup
    isolated_workreport_db.create_task(task_name='제안서 작성', progress=20)

    paused = await office.receive('제안서 보류')
    task = isolated_workreport_db.get_recent_tasks(1)[0]
    assert paused['state'] == 'completed'
    assert task['status'] == 'paused'

    resumed = await office.receive('제안서 재개')
    task = isolated_workreport_db.get_recent_tasks(1)[0]
    assert resumed['state'] == 'completed'
    assert task['status'] == 'active'


@pytest.mark.asyncio
async def test_chat_registers_and_removes_day_off(office_setup, isolated_workreport_db):
    office, _ = office_setup

    registered = await office.receive('2026-05-08 연차 등록')
    days_off = isolated_workreport_db.list_days_off('2026-05')

    assert registered['state'] == 'completed'
    assert days_off[0]['date'] == '2026-05-08'
    assert days_off[0]['name'] == '연차'

    removed = await office.receive('2026-05-08 연차 해제')

    assert removed['state'] == 'completed'
    assert isolated_workreport_db.list_days_off('2026-05') == []


@pytest.mark.asyncio
async def test_chat_registers_half_day_off(office_setup, isolated_workreport_db):
    office, _ = office_setup

    await office.receive('2026-05-08 오전반차 등록')
    morning = isolated_workreport_db.list_days_off('2026-05')[0]

    assert morning['name'] == '오전반차'
    assert morning['kind'] == 'half_day_am'

    await office.receive('2026-05-09 오후 반차 등록')
    days_off = isolated_workreport_db.list_days_off('2026-05')

    assert days_off[1]['date'] == '2026-05-09'
    assert days_off[1]['name'] == '오후반차'
    assert days_off[1]['kind'] == 'half_day_pm'


def test_workreport_monthly_calendar_stats(isolated_workreport_db):
    isolated_workreport_db.create_task(
        task_name='기획 정리',
        project='alpha',
        progress=100,
        work_date='2026-05-06',
        work_time='09:00',
    )
    isolated_workreport_db.create_task(
        task_name='리뷰',
        project='alpha',
        progress=50,
        due_date='2026-05-05',
        work_date='2026-05-06',
        work_time='10:00',
    )
    isolated_workreport_db.create_task(
        task_name='다른 달 작업',
        project='beta',
        progress=0,
        work_date='2026-06-01',
    )

    monthly = isolated_workreport_db.get_monthly_tasks('2026-05')

    assert monthly['month'] == '2026-05'
    assert monthly['total'] == 2
    assert len(monthly['days']) == 1
    day = monthly['days'][0]
    assert day['date'] == '2026-05-06'
    assert day['task_count'] == 2
    assert day['done_count'] == 1
    assert day['overdue_count'] == 1
    assert day['avg_progress'] == 75.0
    assert [task['task_name'] for task in day['tasks']] == ['기획 정리', '리뷰']


def test_workreport_days_off_crud(isolated_workreport_db):
    day_off = isolated_workreport_db.upsert_day_off('2026-05-08', '연차')

    assert day_off['date'] == '2026-05-08'
    assert day_off['name'] == '연차'
    assert isolated_workreport_db.list_days_off('2026-05') == [day_off]
    assert isolated_workreport_db.list_days_off('2026-06') == []
    assert isolated_workreport_db.delete_day_off('2026-05-08') is True
    assert isolated_workreport_db.list_days_off('2026-05') == []


def test_workreport_dashboard_action_items(isolated_workreport_db):
    today = isolated_workreport_db.kst_today().isoformat()
    isolated_workreport_db.create_task(
        task_name='오늘 마감 작업',
        progress=30,
        due_date=today,
        work_date=today,
    )
    isolated_workreport_db.create_task(
        task_name='보류 작업',
        progress=40,
        status='paused',
        work_date=today,
    )
    isolated_workreport_db.create_task(
        task_name='실행 연결 작업',
        progress=20,
        linked_job_id='job-1',
        status='delegated',
        work_date=today,
    )

    dashboard = isolated_workreport_db.get_dashboard()

    action_items = dashboard['action_items']
    assert [task['task_name'] for task in action_items['due_today']] == ['오늘 마감 작업']
    assert [task['task_name'] for task in action_items['paused']] == ['보류 작업']
    assert [task['task_name'] for task in action_items['delegated']] == ['실행 연결 작업']


@pytest.mark.skip(reason='QUICK_TASK 직접 라우팅 제거됨 — 현재는 Job 파이프라인으로 처리 (2026-04)')
@pytest.mark.asyncio
async def test_quick_task_routes_to_single_agent(office_setup):
    '''단순 요청은 담당 전문 역할 하나에만 전달된다'''
    office, bus = office_setup

    # project_runner 내부 LLM 호출(peer 기여·비서 검수) mock — 재작업 루프 방지
    async def _fake_claude(prompt, *args, **kwargs):
        # peer 기여(second_opinion)는 "없음"으로 스킵, 비서 검수는 PASS
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


@pytest.mark.skip(reason='_handle_project 메서드 제거됨 (2026-04 리팩터링)')
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


@pytest.mark.skip(reason='orchestration.agent.run_gemini 제거됨 (2026-04 리팩터링)')
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
