# project_runner E2E — 단일 시나리오.
#
# 흐름: 사용자 프로젝트 입력 → (회의/질문 skip) → 2-phase 실행 →
#       phase1 peer_review(CONCERN) → phase2 정상 → 팀장 최종 리뷰 → 완료.
# 목적: P2의 `_execute_project` 분할 리팩터 때 행동 회귀 검증용 시나리오.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def office(tmp_path, monkeypatch):
  from bus.message_bus import MessageBus
  from log_bus.event_bus import EventBus
  from workspace.manager import WorkspaceManager
  from orchestration.office import Office
  import db.suggestion_store as sugg_store
  import db.task_store as task_store

  monkeypatch.setattr(sugg_store, 'DB_PATH', tmp_path / 'sugg.db')
  monkeypatch.setattr(task_store, 'DB_PATH', tmp_path / 'tasks.db')

  bus = MessageBus(db_path=str(tmp_path / 'bus.db'))
  office = Office(
    bus=bus, event_bus=EventBus(),
    workspace=WorkspaceManager(task_id='e2e-task', workspace_root=str(tmp_path / 'ws')),
    memory_root=tmp_path / 'memory',
  )
  return office


def _script_phases():
  '''단일 그룹 2단계 — 그룹 전환 없이 phase-end peer review 트리거.'''
  return [
    {
      'name': '기획-요구사항', 'assigned_to': 'planner',
      'group': '기획', 'output_format': 'md',
      'description': '핵심 요구사항 정리',
    },
    {
      'name': '기획-상세', 'assigned_to': 'planner',
      'group': '기획', 'output_format': 'md',
      'description': '상세 기획',
    },
  ]


@pytest.mark.asyncio
async def test_project_executes_phases_with_peer_concern_revision(office):
  '''PROJECT intent → 2 phases 실행 → phase1 peer CONCERN → revision → 완료.

  검증:
    - 각 에이전트 handle 호출 횟수 (phase1: 초기+보완, phase2: 초기)
    - peer_review 호출 횟수 (그룹 마지막마다 1회씩 = 2회)
    - 최종 state == completed
  '''
  # ── 인텐트 고정 + 회의 skip + 각종 보조 메서드 no-op ──
  from orchestration import office as office_mod
  from orchestration import intent as intent_mod
  from orchestration.intent import IntentResult, IntentType

  async def _fake_classify(*a, **kw):
    return IntentResult(
      intent=IntentType.PROJECT,
      analysis='간단한 샘플 프로젝트',
    )

  # agent.handle 스크립트 — phase별 + revision별 응답
  planner_responses = [
    '# 기획-요구사항 초안\n\n초안 내용입니다.',        # phase1 초기
    '# 기획-상세 초안\n\n상세 기획 내용입니다.',       # phase2 초기 (그룹 마지막)
  ]
  revised_content = '# 기획-상세 보완\n\nCONCERN 반영한 보완본.'

  office.agents['planner'].handle = AsyncMock(side_effect=planner_responses)
  office.agents['developer'].handle = AsyncMock(return_value='')
  office.agents['qa'].handle = AsyncMock(
    return_value='{"status":"success","summary":"OK","failure_reason":"","severity":"none"}'
  )
  office.agents['designer'].handle = AsyncMock(return_value='')

  # peer_review 결과: phase1(=기획 그룹 마지막)에는 CONCERN + revised, phase2에는 정상
  async def _fake_peer_review(worker, phase_name, content, user_input):
    # 그룹 마지막(기획-상세)에서 CONCERN + revised content 반환
    if '상세' in phase_name:
      return [{
        'reviewer': 'designer',
        'comment': 'UX 관점에서 보완 필요 [CONCERN]',
        'revised': True,
        'content': revised_content,
        'concern': True,
      }]
    return []

  async def _fake_meeting_run(self):
    self.discussions = []

  from contextlib import ExitStack
  from orchestration.phase_registry import ProjectType

  noop_methods = [
    '_work_commentary', '_team_reaction', '_task_acknowledgment',
    '_phase_intro', '_handoff_comment', '_run_planner_synthesize',
    '_team_retrospective', '_auto_export', '_route_agent_mentions',
    '_cross_review',
  ]
  configured = {
    '_plan_project_phases': AsyncMock(return_value=_script_phases()),
    '_extract_user_questions': AsyncMock(return_value=''),
    '_consult_peers': AsyncMock(return_value=''),
    '_peer_review': AsyncMock(side_effect=_fake_peer_review),
    '_check_user_directive': AsyncMock(return_value=None),
    '_run_qa_check': AsyncMock(return_value=True),
    '_create_handoff_guide': AsyncMock(return_value=''),
    '_teamlead_final_review': AsyncMock(return_value=True),
  }

  with ExitStack() as stack:
    stack.enter_context(patch('orchestration.office.classify_intent', side_effect=_fake_classify))
    stack.enter_context(patch('orchestration.meeting.Meeting.run', _fake_meeting_run))
    stack.enter_context(patch('orchestration.project_runner.classify_project_type',
                              AsyncMock(return_value=ProjectType.GENERAL)))
    stack.enter_context(patch('orchestration.project_runner.run_claude_isolated',
                              AsyncMock(return_value='모든 단계가 정상 완료되었습니다.')))
    stack.enter_context(patch.object(office.improvement_engine, 'on_project_complete', AsyncMock()))
    for name in noop_methods:
      stack.enter_context(patch.object(office, name, AsyncMock()))
    for name, mock in configured.items():
      stack.enter_context(patch.object(office, name, mock))

    result = await office.receive('샘플 프로젝트 만들어줘')
    peer_review_calls = configured['_peer_review'].await_count

  # ── 검증 ──
  assert result['state'] == 'completed'
  # phase1 + phase2 (같은 그룹) → planner.handle 2회
  assert office.agents['planner'].handle.await_count == 2
  # 그룹 마지막(phase2)에서만 peer_review 1회
  assert peer_review_calls == 1
  # CONCERN으로 돌아온 revised content가 최종 산출물에 반영
  phase2_file = office.workspace.task_dir / '기획-상세' / 'planner-result.md'
  assert phase2_file.exists()
  assert 'CONCERN 반영한 보완본' in phase2_file.read_text(encoding='utf-8')
  # 2 phases 모두 artifact 기록
  assert len(result['artifacts']) >= 2
