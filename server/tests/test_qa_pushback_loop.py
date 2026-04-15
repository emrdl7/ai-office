# _qa_pushback_round & _file_qa_rule_suggestion 단위 테스트.
# QA 불합격 → 팀원 의견 → 팀장 중재 ADOPT/MODIFY/REJECT 3시나리오.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def office_stub(tmp_path, monkeypatch):
  import db.suggestion_store as store
  monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'sugg.db')

  from log_bus.event_bus import LogEvent

  office = MagicMock()

  async def _fake_emit(agent_id, message, event_type='message'):
    return LogEvent(agent_id=agent_id, event_type=event_type, message=message)

  office._emit = AsyncMock(side_effect=_fake_emit)
  return office


@pytest.mark.asyncio
async def test_pushback_adopt_files_rule(office_stub):
  '''팀원 [지지] 의견 다수 + 팀장 ADOPT → draft 건의 등록.'''
  from orchestration import agent_interactions, suggestion_filer
  from db.suggestion_store import list_suggestions

  responses = iter([
    '[지지] 사용자 입장에서 QA 지적이 타당합니다.',
    '[지지] 이 정도 누락은 재작업이 맞습니다.',
    '{"decision":"ADOPT","rule":"섹션별 필수 항목 누락 금지","reason":"팀원 모두 지지"}',
  ])

  async def _fake_claude(*args, **kwargs):
    return next(responses)

  with patch(
    'orchestration.agent_interactions.run_claude_isolated',
    new=AsyncMock(side_effect=_fake_claude),
  ):
    result = await agent_interactions._qa_pushback_round(
      office_stub,
      offending_agent='developer',
      failure_reason='필수 섹션 누락',
      phase_name='구현',
      user_input='웹사이트 개발',
      content='산출물 내용',
      source_log_id='log-qa-1',
    )

  assert result['decision'] == 'ADOPT'
  assert '섹션' in result['rule']
  assert len(result['opinions']) == 2

  await suggestion_filer._file_qa_rule_suggestion(
    office_stub,
    offending_agent='developer',
    rule_text=result['rule'],
    failure_reason='필수 섹션 누락',
    arb_reason=result['reason'],
    opinions=result['opinions'],
    phase_name='구현',
    source_log_id='log-qa-1',
  )

  suggestions = list_suggestions(status='draft')
  assert len(suggestions) == 1
  s = suggestions[0]
  assert s['target_agent'] == 'developer'
  assert s['category'] == 'QA 규칙'
  assert s['source_log_id'] == 'log-qa-1'
  assert '[QA규칙]' in s['title']


@pytest.mark.asyncio
async def test_pushback_reject_skips_suggestion(office_stub):
  '''팀원 [반박] 의견 + 팀장 REJECT → 건의 등록 안 됨.'''
  from orchestration import agent_interactions, suggestion_filer
  from db.suggestion_store import list_suggestions

  responses = iter([
    '[반박] QA 기준이 과도합니다. 실무상 허용 범위입니다.',
    '[반박] 이 수준이면 통과해도 무리 없습니다.',
    '{"decision":"REJECT","rule":"","reason":"팀원 반박 타당"}',
  ])

  async def _fake_claude(*args, **kwargs):
    return next(responses)

  with patch(
    'orchestration.agent_interactions.run_claude_isolated',
    new=AsyncMock(side_effect=_fake_claude),
  ):
    result = await agent_interactions._qa_pushback_round(
      office_stub,
      offending_agent='designer',
      failure_reason='사소한 여백 이슈',
      phase_name='디자인',
      user_input='랜딩페이지',
      content='디자인 산출물',
    )

  assert result['decision'] == 'REJECT'
  assert result['rule'] == ''

  # REJECT이므로 건의 등록 호출하지 않는 게 정상 흐름 — 직접 호출해도 rule 빈 문자열이면 skip
  await suggestion_filer._file_qa_rule_suggestion(
    office_stub,
    offending_agent='designer',
    rule_text=result['rule'],
    failure_reason='사소한 여백 이슈',
    arb_reason=result['reason'],
    opinions=result['opinions'],
    phase_name='디자인',
  )
  assert list_suggestions(status='draft') == []


@pytest.mark.asyncio
async def test_pushback_modify_with_mixed_opinions(office_stub):
  '''지지/보강 혼합 + 팀장 MODIFY → 수정된 규칙으로 draft 등록.'''
  from orchestration import agent_interactions, suggestion_filer
  from db.suggestion_store import list_suggestions

  responses = iter([
    '[지지] 지적은 맞지만 범위가 넓습니다.',
    '[보강] 특정 섹션만 엄격히 적용하면 어떨까요.',
    '{"decision":"MODIFY","rule":"핵심 섹션(요약·결론)에 한해 필수 항목 검사","reason":"보강 의견 반영"}',
  ])

  async def _fake_claude(*args, **kwargs):
    return next(responses)

  with patch(
    'orchestration.agent_interactions.run_claude_isolated',
    new=AsyncMock(side_effect=_fake_claude),
  ):
    result = await agent_interactions._qa_pushback_round(
      office_stub,
      offending_agent='planner',
      failure_reason='모든 섹션 누락 검사 미흡',
      phase_name='기획',
      user_input='보고서',
      content='기획 산출물',
      source_log_id='log-qa-2',
    )

  assert result['decision'] == 'MODIFY'
  assert '핵심 섹션' in result['rule']

  await suggestion_filer._file_qa_rule_suggestion(
    office_stub,
    offending_agent='planner',
    rule_text=result['rule'],
    failure_reason='모든 섹션 누락 검사 미흡',
    arb_reason=result['reason'],
    opinions=result['opinions'],
    phase_name='기획',
    source_log_id='log-qa-2',
  )

  suggestions = list_suggestions(status='draft')
  assert len(suggestions) == 1
  assert suggestions[0]['target_agent'] == 'planner'
  assert '핵심 섹션' in suggestions[0]['content']
