# ORCH-02: 에이전트 시스템 프롬프트 파일 테스트
from pathlib import Path

# 에이전트 파일 디렉토리: server/../agents/ = /Users/johyeonchang/ai-office/agents/
AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'


def test_planner_has_system_prompt():
  '''기획자 시스템 프롬프트 파일 존재 및 역할 섹션 포함 (ORCH-02)'''
  planner_path = AGENTS_DIR / 'planner.md'
  assert planner_path.exists(), f'파일 없음: {planner_path}'
  content = planner_path.read_text(encoding='utf-8')
  assert '## 역할' in content


def test_all_agents_have_system_prompts():
  '''4개 에이전트 모두 시스템 프롬프트 파일 존재 (ORCH-02)'''
  for agent in ['planner', 'designer', 'developer', 'qa']:
    path = AGENTS_DIR / f'{agent}.md'
    assert path.exists(), f'{agent} 프롬프트 파일 없음: {path}'


def test_each_agent_has_required_sections():
  '''각 에이전트 프롬프트에 필수 4개 섹션 포함 (D-02)'''
  required = ['## 성격', '## 판단력', '## 역할']
  for agent in ['planner', 'designer', 'developer', 'qa']:
    content = (AGENTS_DIR / f'{agent}.md').read_text(encoding='utf-8')
    for section in required:
      assert section in content, f'{agent}.md에 {section!r} 섹션 없음'


def test_qa_prompt_has_independence_rule():
  '''QA 프롬프트에 원본 요구사항 독립 참조 규칙 포함 (D-08)'''
  content = (AGENTS_DIR / 'qa.md').read_text(encoding='utf-8')
  assert '원본 요구사항' in content, 'QA 확증편향 방지 규칙 누락'
