# 산출물 출력 템플릿 — 단계별 필수 섹션 정의 + 검증
from __future__ import annotations
import re


# 단계 유형별 필수 섹션
TEMPLATES: dict[str, list[str]] = {
  # 기획 계열
  'IA설계':       ['정보구조', '메뉴 구조', '사용자 동선'],
  '와이어프레임':  ['섹션 배치', '콘텐츠 영역'],
  '콘텐츠요구사항': ['콘텐츠 목록', '데이터 소스'],
  '요구분석':     ['목표', '범위', '산출물'],
  '콘텐츠전략':   ['타겟', '톤앤매너', '핵심 메시지'],
  '분석설계':     ['분석 목적', '방법론', '가설'],
  '환경분석':     ['외부 환경', 'SWOT'],
  '비즈니스모델':  ['밸류 프로포지션', '수익 모델'],
  '범위설계':     ['조사 목적', '분석 프레임워크'],

  # 디자인 계열
  '디자인-시스템':  ['컬러 팔레트', '타이포그래피', '간격'],
  '디자인-레이아웃': ['브레이크포인트', '그리드'],
  '디자인-컴포넌트': ['헤더', '네비게이션', '푸터'],

  # 분석/보고서 계열
  '인사이트':     ['핵심 발견', '시사점'],
  '보고서':       ['요약', '분석', '결론'],
  '최종':        ['요약', '본문'],

  # 기본
  '_default':    ['개요', '본문'],
}


def get_template(phase_name: str) -> list[str]:
  '''단계 이름에서 해당하는 템플릿 섹션을 반환한다.'''
  for key, sections in TEMPLATES.items():
    if key in phase_name:
      return sections
  return TEMPLATES['_default']


def validate_output(phase_name: str, content: str) -> tuple[bool, list[str]]:
  '''산출물이 템플릿 필수 섹션을 포함하는지 검증한다.

  Returns:
    (통과 여부, 누락 섹션 목록)
  '''
  required = get_template(phase_name)
  missing = []
  content_lower = content.lower()

  for section in required:
    # 마크다운 헤더 또는 본문에서 키워드 존재 확인
    if section.lower() not in content_lower:
      missing.append(section)

  return (len(missing) == 0, missing)


def build_supplement_prompt(phase_name: str, missing: list[str], original: str) -> str:
  '''누락 섹션 보완을 위한 프롬프트를 생성한다.'''
  missing_text = ', '.join(missing)
  return (
    f'[보완 필요] 아래 산출물에 다음 섹션이 누락되었습니다: {missing_text}\n\n'
    f'누락된 섹션을 추가하여 완성된 산출물을 다시 작성하세요.\n\n'
    f'[기존 산출물]\n{original}'
  )


def detect_truncation(content: str) -> bool:
  '''산출물이 잘렸는지 감지한다.

  감지 기준:
  - 미닫힌 코드블록 (``` 개수가 홀수)
  - 문장 중간 끊김 (마지막 줄이 마침표/느낌표/물음표로 안 끝남)
  - "계속", "이어서" 등으로 끝남
  '''
  # 미닫힌 코드블록
  fence_count = content.count('```')
  if fence_count % 2 != 0:
    return True

  # 미닫힌 HTML 태그
  if content.rstrip().endswith(('<', '</', '="')):
    return True

  # 마지막 의미있는 줄 체크
  lines = [l for l in content.strip().split('\n') if l.strip()]
  if not lines:
    return True

  last_line = lines[-1].strip()
  # "계속", "이어서" 등으로 끝남
  truncation_markers = ('계속', '이어서', '다음으로', '...', '…')
  if any(last_line.endswith(m) for m in truncation_markers):
    return True

  # 너무 짧은 산출물 (500자 미만)
  if len(content.strip()) < 500:
    return True

  return False
