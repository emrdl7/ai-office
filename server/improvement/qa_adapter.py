# QA 기준 적응기 — 프로젝트 유형에 따라 QA 검수 기준을 동적으로 조정한다
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

from improvement.metrics import MetricsCollector


# 프로젝트 유형별 QA 기준 시드
DEFAULT_CRITERIA: dict[str, dict[str, Any]] = {
  'website': {
    'focus': ['반응형 레이아웃', '접근성(WCAG 2.1 AA)', '시맨틱 마크업', '성능 최적화'],
    'weight': {'구체성': 0.3, '실행가능성': 0.4, '접근성': 0.3},
  },
  'document': {
    'focus': ['논리 구조', '근거 충분성', '실행 가능성', '완성도'],
    'weight': {'구체성': 0.5, '논리성': 0.3, '완성도': 0.2},
  },
  'analysis': {
    'focus': ['데이터 근거', '분석 깊이', '실행 제안', '시각화'],
    'weight': {'정확성': 0.4, '깊이': 0.3, '실행가능성': 0.3},
  },
  'code': {
    'focus': ['코드 품질', '테스트 커버리지', '보안', '성능'],
    'weight': {'정확성': 0.4, '안정성': 0.3, '유지보수성': 0.3},
  },
}

CRITERIA_PATH = Path(__file__).parent.parent / 'data' / 'improvement' / 'qa_criteria.json'


class QAAdapter:
  '''프로젝트 유형에 따라 QA 검수 기준을 동적으로 조정한다.'''

  def __init__(self, criteria_path: str | Path | None = None, metrics: MetricsCollector | None = None):
    self._path = Path(criteria_path) if criteria_path else CRITERIA_PATH
    self._path.parent.mkdir(parents=True, exist_ok=True)
    self._metrics = metrics
    self._criteria = self._load_criteria()

  def _load_criteria(self) -> dict[str, dict[str, Any]]:
    '''저장된 기준을 로드하거나 기본값을 반환한다.'''
    if self._path.exists():
      try:
        with open(self._path, encoding='utf-8') as f:
          return json.load(f)
      except (json.JSONDecodeError, OSError):
        pass
    return dict(DEFAULT_CRITERIA)

  def _save_criteria(self) -> None:
    '''현재 기준을 저장한다.'''
    tmp = self._path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
      json.dump(self._criteria, f, ensure_ascii=False, indent=2)
    os.rename(tmp, self._path)

  def get_criteria(self, project_type: str) -> dict[str, Any]:
    '''프로젝트 유형별 QA 기준을 반환한다. 없으면 document 기본값.'''
    return self._criteria.get(project_type, DEFAULT_CRITERIA.get('document', {}))

  def build_qa_prompt_supplement(self, project_type: str, past_failures: list[str] | None = None) -> str:
    '''QA 프롬프트에 주입할 유형별 기준 텍스트를 생성한다.'''
    criteria = self.get_criteria(project_type)
    if not criteria:
      return ''

    lines = [f'\n## 프로젝트 유형별 QA 기준 ({project_type})']

    focus = criteria.get('focus', [])
    if focus:
      lines.append('**중점 검수 항목:**')
      for item in focus:
        lines.append(f'- {item}')

    weights = criteria.get('weight', {})
    if weights:
      lines.append('\n**평가 가중치:**')
      for k, v in weights.items():
        lines.append(f'- {k}: {v*100:.0f}%')

    # 과거 실패 패턴에서 특히 주의 항목
    if past_failures:
      lines.append('\n**⚠️ 특히 주의 (과거 빈출 불합격 사유):**')
      for failure in past_failures[:5]:
        lines.append(f'- {failure}')

    return '\n'.join(lines)

  def update(self, report: Any) -> None:
    '''개선 보고서를 기반으로 QA 기준을 업데이트한다.'''
    # 반복 실패 패턴에서 새 focus 항목 도출
    for pattern in getattr(report, 'recurring_failures', []):
      group = pattern.group
      # 그룹명으로 프로젝트 유형 추론
      if '퍼블리싱' in group or '디자인' in group:
        ptype = 'website'
      else:
        ptype = 'document'

      criteria = self._criteria.setdefault(ptype, {'focus': [], 'weight': {}})
      focus = criteria.setdefault('focus', [])

      # 새 주의 항목 추가
      new_focus = f'{pattern.agent_name} {group} 품질 강화 ({pattern.failure_count}회 반복 불합격)'
      if new_focus not in focus:
        focus.append(new_focus)
        # 최대 8개 유지
        if len(focus) > 8:
          criteria['focus'] = focus[-8:]

    self._save_criteria()

  def classify_project_type(self, instruction: str) -> str:
    '''사용자 지시에서 프로젝트 유형을 자동 판단한다.'''
    instruction_lower = instruction.lower()

    website_keywords = ['사이트', '웹사이트', '홈페이지', '랜딩', '웹페이지', 'html', 'css', '퍼블리싱', '웹']
    code_keywords = ['코드', '프로그래밍', '개발', 'api', '서버', '앱', '프로그램', '구현', '코딩']
    analysis_keywords = ['분석', '조사', '리서치', '비교', '벤치마크', '데이터']
    document_keywords = ['기획', '문서', '보고서', '제안서', '전략', '계획', '설계']

    scores = {
      'website': sum(1 for kw in website_keywords if kw in instruction_lower),
      'code': sum(1 for kw in code_keywords if kw in instruction_lower),
      'analysis': sum(1 for kw in analysis_keywords if kw in instruction_lower),
      'document': sum(1 for kw in document_keywords if kw in instruction_lower),
    }

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else 'document'
