# _build_phase_prompt 단위 테스트 — 프롬프트 조립 규칙 고정.
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def office():
  o = MagicMock()
  o._create_handoff_guide = AsyncMock(return_value='가이드 본문')
  return o


@pytest.mark.asyncio
async def test_planning_phase_includes_full_project_and_reference(office):
  from orchestration.project_runner import _build_phase_prompt
  phase = {
    'name': '기획-요구사항', 'group': '기획',
    'description': '요구사항 정리', 'output_format': 'md',
  }
  prompt = await _build_phase_prompt(
    office, phase, {}, '사이트 리뉴얼 [첨부된 참조 자료] 브리프',
    reference_context='추가 리서치',
  )
  assert '사이트 리뉴얼 [첨부된 참조 자료] 브리프' in prompt
  assert '[참조 자료]\n추가 리서치' in prompt
  assert '마크다운 형식으로 작성' in prompt
  office._create_handoff_guide.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_planning_phase_strips_attachment(office):
  '''기획 이외 그룹은 [첨부된 참조 자료] 이후 본문을 잘라낸다.'''
  from orchestration.project_runner import _build_phase_prompt
  phase = {
    'name': '디자인-와이어', 'group': '디자인',
    'description': '와이어프레임', 'output_format': 'md',
  }
  prompt = await _build_phase_prompt(
    office, phase, {}, '본문만 필요\n[첨부된 참조 자료]\n긴 첨부',
    reference_context='리서치',
  )
  assert '본문만 필요' in prompt
  assert '긴 첨부' not in prompt
  # 기획 그룹이 아니라 reference_context도 주입 안 됨
  assert '[참조 자료]' not in prompt


@pytest.mark.asyncio
async def test_same_group_results_embedded_fulltext(office):
  from orchestration.project_runner import _build_phase_prompt
  phase = {
    'name': '기획-IA', 'group': '기획',
    'description': 'IA 설계', 'output_format': 'md',
  }
  all_results = {'기획-요구사항': '요구사항 초안 본문'}
  prompt = await _build_phase_prompt(office, phase, all_results, '입력', '')
  assert '[이전 작업: 기획-요구사항]\n요구사항 초안 본문' in prompt
  office._create_handoff_guide.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_group_results_via_handoff_guide(office):
  '''타 그룹 산출물은 _create_handoff_guide 결과로 참조 가이드 주입.'''
  from orchestration.project_runner import _build_phase_prompt
  phase = {
    'name': '개발-구현', 'group': '개발',
    'description': '구현', 'output_format': 'md',
  }
  all_results = {'기획-요구사항': 'A', '기획-IA': 'B'}
  prompt = await _build_phase_prompt(office, phase, all_results, '입력', '')
  office._create_handoff_guide.assert_awaited_once()
  assert '[기획 단계 참조 가이드]\n가이드 본문' in prompt


@pytest.mark.asyncio
async def test_html_format_instruction(office):
  from orchestration.project_runner import _build_phase_prompt
  phase = {
    'name': '퍼블리싱', 'group': '퍼블리싱',
    'description': 'HTML', 'output_format': 'html+pdf',
  }
  prompt = await _build_phase_prompt(office, phase, {}, '입력', '')
  assert '```html 코드블록' in prompt
  assert '<!DOCTYPE html>' in prompt
