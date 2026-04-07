# 프롬프트 진화기 — 패턴 분석 결과를 바탕으로 에이전트 프롬프트를 동적 보강한다
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from improvement.analyzer import ImprovementReport, RecurringPattern


PATCHES_DIR = Path(__file__).parent.parent / 'data' / 'improvement' / 'prompt_patches'
MAX_RULES_PER_AGENT = 10


@dataclass
class PromptRule:
  '''에이전트 보완 규칙.'''
  id: str
  created_at: str
  source: str           # 'pattern_analysis' | 'manual'
  category: str         # 'quality' | 'structure' | 'completeness'
  rule: str             # 규칙 본문
  evidence: str         # 근거
  priority: str = 'medium'  # 'high' | 'medium' | 'low'
  active: bool = True
  hit_count: int = 0    # 적용 후 해당 패턴 재발 횟수 (낮을수록 효과적)


class PromptEvolver:
  '''패턴 분석 결과를 바탕으로 에이전트별 보완 규칙을 생성/관리한다.

  agents/*.md 원본은 건드리지 않고, data/improvement/prompt_patches/{agent}.json에
  보완 규칙을 누적하여 _build_system_prompt()에서 동적으로 주입한다.
  '''

  def __init__(self, patches_dir: str | Path | None = None):
    self._patches_dir = Path(patches_dir) if patches_dir else PATCHES_DIR
    self._patches_dir.mkdir(parents=True, exist_ok=True)

  def _patch_path(self, agent_name: str) -> Path:
    return self._patches_dir / f'{agent_name}.json'

  def load_rules(self, agent_name: str) -> list[PromptRule]:
    '''에이전트의 보완 규칙 목록을 로드한다.'''
    path = self._patch_path(agent_name)
    if not path.exists():
      return []
    try:
      with open(path, encoding='utf-8') as f:
        data = json.load(f)
      return [PromptRule(**r) for r in data.get('rules', [])]
    except (json.JSONDecodeError, TypeError):
      return []

  def save_rules(self, agent_name: str, rules: list[PromptRule]) -> None:
    '''에이전트의 보완 규칙을 저장한다.'''
    path = self._patch_path(agent_name)
    data = {
      'rules': [asdict(r) for r in rules],
      'meta': {
        'total_rules': len(rules),
        'last_updated': datetime.now(timezone.utc).isoformat(),
      },
    }
    tmp = path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
      json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp, path)

  async def evolve(self, report: ImprovementReport) -> dict[str, list[str]]:
    '''개선 보고서를 바탕으로 에이전트별 새 규칙을 생성한다.

    Returns:
      에이전트별 새로 추가된 규칙 목록 {'designer': ['규칙1', ...]}
    '''
    new_rules: dict[str, list[str]] = {}

    for pattern in report.recurring_failures:
      agent = pattern.agent_name
      rule_text = self._generate_rule(pattern)
      if not rule_text:
        continue

      rules = self.load_rules(agent)

      # 중복 체크
      if any(r.rule == rule_text for r in rules):
        continue

      now = datetime.now(timezone.utc).isoformat()
      rule = PromptRule(
        id=f'rule-{len(rules)+1:03d}',
        created_at=now,
        source='pattern_analysis',
        category='quality',
        rule=rule_text,
        evidence=pattern.description,
        priority='high' if pattern.failure_count >= 5 else 'medium',
      )
      rules.append(rule)

      # 규칙 수 제한 — 오래된 저효과 규칙 정리
      if len(rules) > MAX_RULES_PER_AGENT:
        rules = self._compact_rules(rules)

      self.save_rules(agent, rules)
      new_rules.setdefault(agent, []).append(rule_text)

    return new_rules

  def _generate_rule(self, pattern: RecurringPattern) -> str:
    '''반복 실패 패턴에서 구체적 규칙 1줄을 생성한다.

    LLM 호출 없이 패턴 기반으로 규칙을 생성한다.
    충분한 데이터가 쌓이면 LLM 기반으로 전환 가능.
    '''
    agent = pattern.agent_name
    group = pattern.group
    count = pattern.failure_count

    # 에이전트+그룹별 규칙 템플릿
    templates = {
      ('designer', '디자인'): f'{group} 작업 시 hex 코드, 폰트 사이즈(px), 간격(rem) 등 수치를 반드시 명시할 것 ({count}회 불합격 이력)',
      ('planner', '기획'): f'{group} 작업 시 각 섹션의 목적, 타겟 사용자, 기대 효과를 구체적으로 서술할 것 ({count}회 불합격 이력)',
      ('developer', '퍼블리싱'): f'{group} 작업 시 반응형(모바일/태블릿/데스크탑), 시맨틱 마크업, 접근성을 모두 반영할 것 ({count}회 불합격 이력)',
    }

    key = (agent, group)
    if key in templates:
      return templates[key]

    # 일반 템플릿
    return f'{group} 단계에서 QA 지적사항을 사전에 방지할 것: 구체성과 완성도를 높이세요 ({count}회 반복 불합격)'

  def _compact_rules(self, rules: list[PromptRule]) -> list[PromptRule]:
    '''규칙 수가 MAX_RULES_PER_AGENT 초과 시 오래된 저효과 규칙을 정리한다.'''
    # 활성 규칙만 대상
    active = [r for r in rules if r.active]
    inactive = [r for r in rules if not r.active]

    if len(active) <= MAX_RULES_PER_AGENT:
      return active + inactive

    # hit_count가 높은(= 재발이 잦은 = 효과 낮은) 규칙을 비활성화
    sorted_rules = sorted(active, key=lambda r: (r.hit_count, r.created_at))
    keep = sorted_rules[:MAX_RULES_PER_AGENT]
    deactivate = sorted_rules[MAX_RULES_PER_AGENT:]
    for r in deactivate:
      r.active = False

    return keep + deactivate + inactive

  def get_active_rules_text(self, agent_name: str) -> str:
    '''에이전트의 활성 규칙을 프롬프트 주입용 텍스트로 반환한다.'''
    rules = self.load_rules(agent_name)
    active = [r for r in rules if r.active]
    if not active:
      return ''

    lines = ['## 학습된 품질 규칙 (반드시 준수할 것)']
    for r in active:
      priority_mark = '⚠️ ' if r.priority == 'high' else ''
      lines.append(f'- {priority_mark}{r.rule}')

    return '\n'.join(lines)

  def toggle_rule(self, agent_name: str, rule_id: str, active: bool) -> bool:
    '''규칙 활성화/비활성화 토글.'''
    rules = self.load_rules(agent_name)
    for r in rules:
      if r.id == rule_id:
        r.active = active
        self.save_rules(agent_name, rules)
        return True
    return False
