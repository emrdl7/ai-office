# PromptEvolver 규칙 자동 주입 검증 — auto_apply 경로.
#
# auto_triage_new_suggestion은 main.py 내부에 있지만 핵심 로직인
# `apply_prompt_or_rule`은 improvement.auto_apply로 추출되어 있어
# 해당 함수를 직접 호출해 규칙 파일 diff를 검증한다.
import json
import pytest


@pytest.fixture
def tmp_paths(tmp_path, monkeypatch):
  '''PromptEvolver 패치 디렉토리 + TeamMemory 저장소를 tmp로 격리.'''
  from improvement import prompt_evolver

  patches_dir = tmp_path / 'patches'
  patches_dir.mkdir()
  monkeypatch.setattr(prompt_evolver, 'PATCHES_DIR', patches_dir)

  # TeamMemory 기본 저장 경로를 tmp로
  import memory.team_memory as tm_mod
  orig_init = tm_mod.TeamMemory.__init__

  def _patched_init(self, memory_root='data/memory'):
    orig_init(self, tmp_path / 'memory')

  monkeypatch.setattr(tm_mod.TeamMemory, '__init__', _patched_init)

  return {'patches': patches_dir, 'memory': tmp_path / 'memory'}


@pytest.mark.asyncio
async def test_apply_prompt_rule_writes_patch_file(tmp_paths):
  '''prompt 타입 건의 auto_apply → target_agent의 patch json에 규칙 누적.'''
  from improvement.auto_apply import apply_prompt_or_rule

  suggestion = {
    'id': 'sug-001',
    'agent_id': 'qa',
    'target_agent': 'developer',
    'title': 'JSON 스키마 고정',
    'content': 'QA의 발언: "JSON 응답은 failure_reason 키를 항상 포함하라"',
    'category': 'quality',
    'suggestion_type': 'prompt',
  }

  ok = await apply_prompt_or_rule(suggestion)
  assert ok is True

  patch_file = tmp_paths['patches'] / 'developer.json'
  assert patch_file.exists()
  data = json.loads(patch_file.read_text(encoding='utf-8'))
  rules = data['rules']
  assert len(rules) == 1
  rule = rules[0]
  assert rule['id'] == 'suggestion-sug-001'
  assert rule['source'] == 'auto'
  assert 'failure_reason' in rule['rule']
  assert rule['active'] is True


@pytest.mark.asyncio
async def test_apply_prompt_rule_falls_back_to_agent_id(tmp_paths):
  '''target_agent 미지정 시 agent_id 본인에게 규칙이 주입된다.'''
  from improvement.auto_apply import apply_prompt_or_rule

  suggestion = {
    'id': 'sug-002',
    'agent_id': 'planner',
    'target_agent': '',
    'title': '회의 요약 규칙',
    'content': '회의 종료 시 의사결정 3줄 요약을 반드시 남겨라',
    'category': 'process',
    'suggestion_type': 'rule',
  }

  assert await apply_prompt_or_rule(suggestion, user_comment='좋아요') is True

  patch_file = tmp_paths['patches'] / 'planner.json'
  assert patch_file.exists()
  rule = json.loads(patch_file.read_text())['rules'][0]
  # user_comment가 있으면 source='manual'
  assert rule['source'] == 'manual'
  assert '사용자 코멘트' in rule['rule']


@pytest.mark.asyncio
async def test_apply_prompt_rule_appends_to_existing(tmp_paths):
  '''기존 규칙이 있을 때 누적 저장된다 (덮어쓰기 아님).'''
  from improvement.auto_apply import apply_prompt_or_rule

  base = {
    'agent_id': 'qa', 'target_agent': 'developer',
    'category': 'quality', 'suggestion_type': 'prompt',
  }
  await apply_prompt_or_rule({**base, 'id': 'a', 'title': 't', 'content': '첫번째 규칙'})
  await apply_prompt_or_rule({**base, 'id': 'b', 'title': 't', 'content': '두번째 규칙'})

  data = json.loads((tmp_paths['patches'] / 'developer.json').read_text())
  ids = [r['id'] for r in data['rules']]
  assert ids == ['suggestion-a', 'suggestion-b']
