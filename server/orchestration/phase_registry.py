# 프로젝트 유형별 Phase 레지스트리 — 유형 Enum + 템플릿 + 회의 참여자
from __future__ import annotations
from enum import Enum


class ProjectType(str, Enum):
  WEB_DEVELOPMENT = 'web_development'
  MARKET_RESEARCH = 'market_research'
  CONTENT_CREATION = 'content_creation'
  DATA_ANALYSIS = 'data_analysis'
  BUSINESS_PLANNING = 'business_planning'
  GENERAL = 'general'


# 기존 workflow_optimizer 유형 → 새 ProjectType 매핑 (호환성)
_LEGACY_TYPE_MAP: dict[str, ProjectType] = {
  'website': ProjectType.WEB_DEVELOPMENT,
  'document': ProjectType.GENERAL,
  'analysis': ProjectType.DATA_ANALYSIS,
  'code': ProjectType.WEB_DEVELOPMENT,
}


def from_legacy_type(legacy: str) -> ProjectType:
  '''기존 workflow_optimizer 유형명을 ProjectType으로 변환한다.'''
  return _LEGACY_TYPE_MAP.get(legacy, ProjectType.GENERAL)


# ── 유형별 Phase 템플릿 ──────────────────────────────────────────

PHASE_TEMPLATES: dict[ProjectType, list[dict[str, str]]] = {

  ProjectType.WEB_DEVELOPMENT: [
    {
      'name': '기획-인수조건',
      'description': (
        '각 핵심 기능의 인수 조건을 Gherkin 문법(Given-When-Then)으로 작성하세요. '
        '기능당 정상 케이스와 예외 케이스를 각 1개 이상 포함하고, '
        '사용자 관점에서 측정 가능한 기준으로 서술하세요. '
        '이 문서는 QA 검수 및 개발 구현의 공식 기준이 됩니다.'
      ),
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '기획-IA설계',
      'description': '사용자 유형별 정보구조(IA) 트리를 설계하세요. GNB, 서브메뉴, 사용자 동선을 포함.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '기획-와이어프레임',
      'description': '메인화면 와이어프레임을 설계하세요. 섹션 배치, 콘텐츠 영역, CTA 위치를 명시.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '기획-콘텐츠요구사항',
      'description': '각 섹션별 필요 콘텐츠, 데이터 소스, 갱신 주기를 정의하세요.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '디자인-시스템',
      'description': '디자인 시스템을 정의하세요. 컬러 팔레트(hex), 타이포그래피(폰트/사이즈), 간격 체계, 아이콘 스타일.',
      'assigned_to': 'designer', 'group': '디자인', 'output_format': 'md',
    },
    {
      'name': '디자인-레이아웃',
      'description': '메인화면 레이아웃을 설계하세요. 반응형(모바일/태블릿/데스크탑) 브레이크포인트별 구성.',
      'assigned_to': 'designer', 'group': '디자인', 'output_format': 'md',
    },
    {
      'name': '디자인-컴포넌트',
      'description': '주요 UI 컴포넌트 명세를 작성하세요. 헤더, 히어로, 카드, 네비게이션, 푸터의 상세 스펙.',
      'assigned_to': 'designer', 'group': '디자인', 'output_format': 'md',
    },
    {
      'name': '퍼블리싱',
      'description': (
        '디자인 시안(Stitch HTML)과 디자인 명세를 기반으로 완성된 퍼블리싱 파일을 작성하세요. '
        '단일 index.html 파일에 HTML 구조 + CSS 스타일 + JS 인터랙션을 모두 포함. '
        '시맨틱 마크업, 반응형, 접근성(WCAG 2.1 AA)을 반영.'
      ),
      'assigned_to': 'developer', 'group': '퍼블리싱', 'output_format': 'html',
    },
  ],

  ProjectType.MARKET_RESEARCH: [
    {
      'name': '조사-범위설계',
      'description': '조사 목적, 범위, 핵심 질문, 분석 프레임워크(PEST/5Forces/SWOT 등)를 설계하세요.',
      'assigned_to': 'planner', 'group': '조사', 'output_format': 'md',
    },
    {
      'name': '조사-시장환경분석',
      'description': '시장 규모, 성장률, 트렌드, 주요 플레이어를 정량적으로 분석하세요.',
      'assigned_to': 'planner', 'group': '조사', 'output_format': 'md',
    },
    {
      'name': '조사-경쟁사분석',
      'description': '주요 경쟁사의 제품/서비스, 포지셔닝, 강약점을 분석하고 포지셔닝 맵을 작성하세요.',
      'assigned_to': 'developer', 'group': '조사', 'output_format': 'md+code',
    },
    {
      'name': '분석-인사이트도출',
      'description': '수집된 데이터에서 핵심 인사이트를 도출하고 전략적 시사점을 정리하세요.',
      'assigned_to': 'planner', 'group': '분석', 'output_format': 'md',
    },
    {
      'name': '시각화-차트설계',
      'description': '핵심 데이터를 차트/인포그래픽으로 시각화하세요. 차트 유형 선정, 레이아웃, 스토리텔링 포함.',
      'assigned_to': 'designer', 'group': '시각화', 'output_format': 'md',
    },
    {
      'name': '보고서-최종',
      'description': '모든 조사/분석 결과를 종합하여 최종 시장조사 보고서를 작성하세요. HTML 보고서도 생성.',
      'assigned_to': 'planner', 'group': '보고서', 'output_format': 'html+pdf',
    },
  ],

  ProjectType.CONTENT_CREATION: [
    {
      'name': '기획-콘텐츠전략',
      'description': '타겟 오디언스, 톤앤매너, 핵심 메시지, 채널 전략을 정의하세요.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '콘텐츠-초안작성',
      'description': '콘텐츠 전략에 따라 본문 초안을 작성하세요. SEO 키워드, 구조, 핵심 메시지를 반영.',
      'assigned_to': 'developer', 'group': '콘텐츠', 'output_format': 'md',
    },
    {
      'name': '콘텐츠-비주얼기획',
      'description': '콘텐츠에 필요한 이미지/인포그래픽 구성, 레이아웃, 시각적 스토리텔링을 기획하세요.',
      'assigned_to': 'designer', 'group': '콘텐츠', 'output_format': 'md',
    },
    {
      'name': '콘텐츠-최종편집',
      'description': '초안과 비주얼을 통합하여 최종 콘텐츠를 완성하세요. HTML 스타일드 미리보기도 생성.',
      'assigned_to': 'planner', 'group': '콘텐츠', 'output_format': 'html+pdf',
    },
  ],

  ProjectType.DATA_ANALYSIS: [
    {
      'name': '기획-분석설계',
      'description': '분석 목적, 범위, 방법론, 데이터 소스, 가설을 설계하세요.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '분석-데이터처리',
      'description': 'Python 코드로 데이터 수집/정제/분석을 수행하세요. 기술통계, 상관분석 등 포함.',
      'assigned_to': 'developer', 'group': '분석', 'output_format': 'md+code',
    },
    {
      'name': '분석-통계해석',
      'description': '분석 결과를 해석하고 핵심 인사이트를 도출하세요. 통계적 유의성과 실무 시사점 포함.',
      'assigned_to': 'planner', 'group': '분석', 'output_format': 'md',
    },
    {
      'name': '시각화-대시보드',
      'description': '핵심 지표를 대시보드 형태로 시각화하세요. 차트 유형, 레이아웃, 위젯 배치를 설계.',
      'assigned_to': 'designer', 'group': '시각화', 'output_format': 'md',
    },
    {
      'name': '보고서-최종',
      'description': '분석 결과를 종합하여 최종 보고서를 작성하세요. HTML 보고서도 생성.',
      'assigned_to': 'planner', 'group': '보고서', 'output_format': 'html+pdf',
    },
  ],

  ProjectType.BUSINESS_PLANNING: [
    {
      'name': '분석-환경분석',
      'description': '내외부 환경을 분석하세요. 산업 동향, 시장 기회, SWOT, 규제 환경 포함.',
      'assigned_to': 'planner', 'group': '분석', 'output_format': 'md',
    },
    {
      'name': '기획-비즈니스모델',
      'description': '비즈니스 모델 캔버스, 밸류 프로포지션, 수익 모델을 설계하세요.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '기획-실행전략',
      'description': '실행 로드맵, KPI, 마일스톤, 조직/인력 계획을 수립하세요.',
      'assigned_to': 'developer', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '기획-재무추정',
      'description': '매출/비용 추정, 손익분기점 분석, 시나리오별 재무 모델링을 수행하세요.',
      'assigned_to': 'developer', 'group': '기획', 'output_format': 'md+code',
    },
    {
      'name': '기획-발표자료',
      'description': '투자자/경영진 대상 피치덱 슬라이드를 설계하세요. 스토리라인, 슬라이드 구성, 비주얼 전략 포함.',
      'assigned_to': 'designer', 'group': '발표', 'output_format': 'html_slide+pdf',
    },
    {
      'name': '보고서-최종',
      'description': '전체 분석/기획을 종합하여 사업계획서를 작성하세요. HTML 보고서도 생성.',
      'assigned_to': 'planner', 'group': '보고서', 'output_format': 'html+pdf',
    },
  ],

  ProjectType.GENERAL: [
    {
      'name': '기획-요구분석',
      'description': '요구사항을 분석하고 작업 범위, 목표, 산출물 구조를 설계하세요.',
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '기획-인수조건',
      'description': (
        '각 핵심 요구사항의 인수 조건을 Gherkin 문법(Given-When-Then)으로 작성하세요. '
        '정상 케이스와 예외 케이스를 각 1개 이상 포함하고, 측정 가능한 기준으로 서술하세요.'
      ),
      'assigned_to': 'planner', 'group': '기획', 'output_format': 'md',
    },
    {
      'name': '작업-실행',
      'description': '설계에 따라 핵심 작업을 수행하세요. 조사, 분석, 콘텐츠 작성 등 요구사항에 맞게 실행.',
      'assigned_to': 'developer', 'group': '작업', 'output_format': 'md',
    },
    {
      'name': '검토-종합',
      'description': '작업 결과를 검토하고 보완할 부분을 정리하세요.',
      'assigned_to': 'planner', 'group': '검토', 'output_format': 'md',
    },
    {
      'name': '보고서-최종',
      'description': '모든 결과를 종합하여 최종 보고서를 작성하세요. HTML 보고서도 생성.',
      'assigned_to': 'planner', 'group': '보고서', 'output_format': 'html+pdf',
    },
  ],
}


# ── 유형별 회의 참여자 ──────────────────────────────────────────

_MEETING_PARTICIPANTS: dict[ProjectType, list[str]] = {
  ProjectType.WEB_DEVELOPMENT: ['planner', 'designer', 'developer'],
  ProjectType.MARKET_RESEARCH: ['planner', 'developer'],
  ProjectType.CONTENT_CREATION: ['planner', 'designer'],
  ProjectType.DATA_ANALYSIS: ['planner', 'developer'],
  ProjectType.BUSINESS_PLANNING: ['planner', 'developer', 'designer'],
  ProjectType.GENERAL: ['planner', 'developer'],
}


def get_phases(project_type: ProjectType) -> list[dict]:
  '''프로젝트 유형에 맞는 Phase 목록을 반환한다.'''
  return [dict(p) for p in PHASE_TEMPLATES.get(project_type, PHASE_TEMPLATES[ProjectType.GENERAL])]


def get_meeting_participants(project_type: ProjectType) -> list[str]:
  '''프로젝트 유형에 맞는 회의 참여자 목록을 반환한다.'''
  return list(_MEETING_PARTICIPANTS.get(project_type, ['planner', 'developer']))
