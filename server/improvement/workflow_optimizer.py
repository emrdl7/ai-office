# 워크플로우 최적화기 — 프로젝트 유형별로 PHASES를 동적으로 구성한다
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from improvement.metrics import MetricsCollector


@dataclass
class Phase:
  '''워크플로우 단계 정의.'''
  name: str
  description: str
  assigned_to: str
  group: str


# 프로젝트 유형별 기본 PHASES 템플릿
PHASE_TEMPLATES: dict[str, list[dict[str, str]]] = {
  'website': [
    {'name': '기획-IA설계', 'description': '사용자 유형별 정보구조(IA) 트리를 설계하세요. GNB, 서브메뉴, 사용자 동선을 포함.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-와이어프레임', 'description': '메인화면 와이어프레임을 설계하세요. 섹션 배치, 콘텐츠 영역, CTA 위치를 명시.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-콘텐츠요구사항', 'description': '각 섹션별 필요 콘텐츠, 데이터 소스, 갱신 주기를 정의하세요.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '디자인-시스템', 'description': '디자인 시스템을 정의하세요. 컬러 팔레트(hex), 타이포그래피(폰트/사이즈), 간격 체계, 아이콘 스타일.', 'assigned_to': 'designer', 'group': '디자인'},
    {'name': '디자인-레이아웃', 'description': '메인화면 레이아웃을 설계하세요. 반응형(모바일/태블릿/데스크탑) 브레이크포인트별 구성.', 'assigned_to': 'designer', 'group': '디자인'},
    {'name': '디자인-컴포넌트', 'description': '주요 UI 컴포넌트 명세를 작성하세요. 헤더, 히어로, 카드, 네비게이션, 푸터의 상세 스펙.', 'assigned_to': 'designer', 'group': '디자인'},
    {'name': '퍼블리싱', 'description': '디자인 시안(Stitch HTML)과 디자인 명세를 기반으로 완성된 퍼블리싱 파일을 작성하세요. 단일 index.html 파일에 HTML 구조 + CSS 스타일 + JS 인터랙션을 모두 포함. 시맨틱 마크업, 반응형, 접근성(WCAG 2.1 AA)을 반영.', 'assigned_to': 'developer', 'group': '퍼블리싱'},
  ],
  'document': [
    {'name': '기획-구조설계', 'description': '문서의 전체 구조를 설계하세요. 목차, 섹션 구성, 핵심 메시지를 정의.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-콘텐츠', 'description': '각 섹션의 상세 콘텐츠를 작성하세요. 근거 자료, 데이터, 사례를 포함.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-실행계획', 'description': '실행 로드맵, 예산, 일정, 담당자를 정의하세요.', 'assigned_to': 'planner', 'group': '기획'},
  ],
  'analysis': [
    {'name': '기획-분석설계', 'description': '분석 프레임워크를 설계하세요. 분석 범위, 방법론, 데이터 소스를 정의.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-데이터수집', 'description': '분석에 필요한 데이터를 수집하고 정리하세요.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-분석실행', 'description': '프레임워크에 따라 분석을 실행하고 인사이트를 도출하세요.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-제안', 'description': '분석 결과를 바탕으로 구체적 실행 제안을 작성하세요.', 'assigned_to': 'planner', 'group': '기획'},
  ],
  'code': [
    {'name': '기획-아키텍처', 'description': '시스템 아키텍처를 설계하세요. 기술 스택, 모듈 구조, API 설계를 포함.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '기획-요구사항', 'description': '기능 요구사항과 비기능 요구사항을 정의하세요.', 'assigned_to': 'planner', 'group': '기획'},
    {'name': '개발-구현', 'description': '설계에 따라 코드를 구현하세요.', 'assigned_to': 'developer', 'group': '개발'},
  ],
}

OPTIMIZER_DATA_PATH = Path(__file__).parent.parent / 'data' / 'improvement' / 'workflow_data.json'


class WorkflowOptimizer:
  '''프로젝트 유형과 과거 성과를 기반으로 최적 PHASES를 반환한다.'''

  def __init__(self, metrics: MetricsCollector | None = None, data_path: str | Path | None = None):
    self._metrics = metrics
    self._data_path = Path(data_path) if data_path else OPTIMIZER_DATA_PATH
    self._data_path.parent.mkdir(parents=True, exist_ok=True)
    self._customizations = self._load_customizations()

  def _load_customizations(self) -> dict[str, Any]:
    if self._data_path.exists():
      try:
        with open(self._data_path, encoding='utf-8') as f:
          data: dict[str, Any] = json.load(f)
          return data
      except (json.JSONDecodeError, OSError):
        pass
    return {}

  def _save_customizations(self) -> None:
    tmp = self._data_path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
      json.dump(self._customizations, f, ensure_ascii=False, indent=2)
    os.rename(tmp, self._data_path)

  def get_phases(self, project_type: str, instruction: str = '') -> list[Phase]:
    '''프로젝트 유형과 과거 성과를 기반으로 최적 PHASES를 반환한다.'''
    # 1. 기본 템플릿 로드
    template = PHASE_TEMPLATES.get(project_type, PHASE_TEMPLATES['website'])
    phases = [Phase(**p) for p in template]

    # 2. 사용자 지시에서 명시적 스킵 감지
    instruction_lower = instruction.lower()
    skip_keywords = {
      '디자인': ['디자인 없이', '디자인 스킵', '디자인 생략', '코드만'],
      '기획': ['기획 없이', '기획 스킵', '바로 개발', '바로 코딩'],
    }
    skip_groups = set()
    for group, keywords in skip_keywords.items():
      if any(kw in instruction_lower for kw in keywords):
        skip_groups.add(group)

    if skip_groups:
      phases = [p for p in phases if p.group not in skip_groups]

    # 3. 과거 병목 데이터 반영 (커스텀 설명 보강)
    customizations = self._customizations.get(project_type, {})
    for phase in phases:
      extra = customizations.get(phase.name, {}).get('extra_description', '')
      if extra:
        phase.description += f'\n{extra}'

    return phases

  def update(self, report: Any) -> None:
    '''개선 보고서를 기반으로 워크플로우 커스텀을 업데이트한다.'''
    for bottleneck in getattr(report, 'bottlenecks', []):
      # 병목 단계에 추가 지시 삽입
      for ptype, template in PHASE_TEMPLATES.items():
        for phase_def in template:
          if phase_def['name'] == bottleneck.phase_name:
            customs = self._customizations.setdefault(ptype, {})
            phase_custom = customs.setdefault(bottleneck.phase_name, {})
            if bottleneck.revision_rate >= 0.5:
              phase_custom['extra_description'] = (
                f'⚠️ 이 단계는 과거 보완 비율이 {bottleneck.revision_rate*100:.0f}%입니다. '
                f'첫 제출에서 완성도를 높이세요.'
              )
    self._save_customizations()

  def get_phase_dicts(self, project_type: str, instruction: str = '') -> list[dict[str, str]]:
    '''get_phases()의 dict 버전 — office.py의 PHASES와 동일 형태.'''
    phases = self.get_phases(project_type, instruction)
    return [
      {
        'name': p.name,
        'description': p.description,
        'assigned_to': p.assigned_to,
        'group': p.group,
      }
      for p in phases
    ]
