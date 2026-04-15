# run_retrospective — 메트릭 주입 / 팀장 종합 / retrospective.md 저장 단위 테스트.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mk_metric(name, phase, qa_passed=True, rev=0, duration=60.0):
  from improvement.metrics import PhaseMetrics
  return PhaseMetrics(
    phase_name=phase, agent_name=name,
    started_at='2026-04-15T00:00:00Z', finished_at='2026-04-15T00:01:00Z',
    duration_seconds=duration, qa_passed=qa_passed, revision_count=rev,
  )


@pytest.fixture
def office_stub(tmp_path):
  from memory.team_memory import TeamMemory
  from log_bus.event_bus import LogEvent

  office = MagicMock()
  office.team_memory = TeamMemory(tmp_path)
  office._active_project_id = 'proj-1'

  # workspace 스텁 — write_artifact 내용 기록
  saved = {}
  ws = MagicMock()
  def _write(path, content):
    saved[path] = content
    return tmp_path / path
  ws.write_artifact = MagicMock(side_effect=_write)
  office.workspace = ws
  office._workspace_saved = saved

  async def _fake_emit(agent_id, message, event_type='message'):
    return LogEvent(agent_id=agent_id, event_type=event_type, message=message)
  office._emit = AsyncMock(side_effect=_fake_emit)

  # agents — _build_system_prompt만 쓰임
  def _mk_agent():
    a = MagicMock()
    a._build_system_prompt = MagicMock(return_value='sys')
    return a
  office.agents = {
    'planner': _mk_agent(),
    'designer': _mk_agent(),
    'developer': _mk_agent(),
  }

  office._phase_metrics = [
    _mk_metric('planner', '기획', qa_passed=True, rev=0),
    _mk_metric('designer', '디자인', qa_passed=False, rev=1, duration=120.0),
    _mk_metric('developer', '개발', qa_passed=True, rev=0),
  ]
  office._phase_feedback = [
    {'from': '튜링', 'phase': '기획', 'content': '요구사항 모호'},
    {'from': '아이브', 'phase': '기획', 'content': '레이아웃 영향 고려 필요'},
  ]
  return office


def test_metrics_context_includes_qa_and_revisions(office_stub):
  from orchestration.teamlead_review import _build_agent_metrics_context
  ctx = _build_agent_metrics_context(office_stub, 'designer')
  assert 'QA 불합격 1회' in ctx
  assert '리비전 1회' in ctx


def test_metrics_context_includes_received_feedback(office_stub):
  from orchestration.teamlead_review import _build_agent_metrics_context
  # planner는 튜링·아이브로부터 피드백 받음
  ctx = _build_agent_metrics_context(office_stub, 'planner')
  assert '받은 피드백' in ctx
  assert '튜링' in ctx or '아이브' in ctx


@pytest.mark.asyncio
async def test_retrospective_saves_artifact_and_lessons(office_stub):
  from orchestration import teamlead_review

  retro_texts = {
    'planner': '요구사항 모호할 때 드러내는 질문 먼저 던져야',
    'designer': '리비전 반복 → 초안에 AC 체크 먼저',
    'developer': '개발 전 레이아웃 확정이 속도를 올린다',
  }
  synth = (
    '## 이번 프로젝트 핵심\n프로젝트 진행.\n\n'
    '## 관통하는 실마리\n초안 단계 검증 부족.\n\n'
    '## 다음 프로젝트에 적용할 액션\n- 드러커: 초안 AC 체크리스트 제공'
  )

  call_count = {'n': 0}
  async def _fake_claude(prompt, **kwargs):
    call_count['n'] += 1
    # 팀장 종합 프롬프트는 "팀원들의 회고 발언을 종합" 문구 포함
    if '종합' in prompt:
      return synth
    # 에이전트별 회고 프롬프트는 display_name을 포함
    for name, text in retro_texts.items():
      if f'당신({teamlead_review.display_name(name)})' in prompt:
        return text
    return '기본 회고'

  all_results = {
    '기획': 'planner 산출', '디자인': 'designer 산출', '개발': 'developer 산출',
  }

  with patch(
    'orchestration.teamlead_review.run_claude_isolated',
    new=AsyncMock(side_effect=_fake_claude),
  ):
    await teamlead_review.run_retrospective(
      office_stub,
      project_title='테스트 프로젝트',
      project_type='website',
      all_results=all_results,
      user_input='간단한 랜딩 페이지',
      duration=360.0,
    )

  # retrospective.md 저장됨
  assert 'retrospective.md' in office_stub._workspace_saved
  doc = office_stub._workspace_saved['retrospective.md']
  assert '# 테스트 프로젝트 — 팀 회고' in doc
  assert '관통하는 실마리' in doc
  assert '팀원별 배운 점' in doc

  # SharedLesson 저장됨
  lessons = office_stub.team_memory.get_all_lessons()
  assert len(lessons) >= 1
  assert all(l.project_title == '테스트 프로젝트' for l in lessons)
