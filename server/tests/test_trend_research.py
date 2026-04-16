'''trend_research 모듈 — 인사이트 추출/규칙 등록 흐름 검증.

외부 의존성(web_search, run_gemini)은 monkeypatch로 대체.
'''
import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from orchestration import trend_research
from improvement.prompt_evolver import PromptEvolver


class _StubBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class _StubOffice:
    def __init__(self) -> None:
        self.event_bus = _StubBus()


@pytest.fixture
def office_and_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_research, '_STATE_PATH', tmp_path / 'state.json')
    # PromptEvolver는 PATCHES_DIR 모듈 상수를 fallback 으로 쓰므로 그것도 격리
    from improvement import prompt_evolver as _pe
    monkeypatch.setattr(_pe, 'PATCHES_DIR', tmp_path / 'patches')
    return _StubOffice()


def test_pick_query_filters_used():
    bank = trend_research._QUERY_BANK['planner']
    used = bank[:2]
    picked = trend_research._pick_query('planner', used)
    assert picked in bank
    assert picked not in used


def test_pick_query_returns_empty_when_all_used():
    bank = trend_research._QUERY_BANK['planner']
    assert trend_research._pick_query('planner', list(bank)) == ''


def test_pick_query_unknown_speaker_returns_empty():
    assert trend_research._pick_query('unknown', []) == ''


@pytest.mark.asyncio
async def test_maybe_research_registers_rule_and_emits(monkeypatch, office_and_paths):
    office = office_and_paths

    async def fake_gemini(prompt: str = '', **_kw) -> str:
        return json.dumps({
            'target_agent': 'designer',
            'headline': 'WAI-ARIA live region 사용',
            'rule': '동적 콘텐츠 변경 시 aria-live="polite" 영역에 알림을 발행하여 스크린리더 사용자에게 전달할 것.',
            'evidence': '검색 결과 1번 항목 — WCAG 3 라이브 리전 가이드',
            'source': 'https://example.com/wcag3-live-region',
        })

    monkeypatch.setattr(trend_research, 'run_gemini', fake_gemini)

    def fake_search(query: str, max_results: int = 5) -> str:
        return (
            '1. WCAG 3 라이브 리전\n   https://example.com/wcag3-live-region\n   '
            'Use aria-live polite for dynamic content updates.\n\n'
            '2. Designing for screen readers\n   https://example.com/sr\n   ...'
        )

    monkeypatch.setattr('harness.file_reader.web_search', fake_search)

    ok = await trend_research.maybe_research(office, 'designer')
    assert ok is True

    # 규칙이 designer.json에 등록되었는지
    evolver = PromptEvolver()
    rules = evolver.load_rules('designer')
    trend_rules = [r for r in rules if r.source == 'trend_research']
    assert len(trend_rules) == 1
    assert 'aria-live' in trend_rules[0].rule

    # 자율 발화 + system_notice 두 이벤트 발생
    types = [e.event_type for e in office.event_bus.events]
    assert 'autonomous' in types
    assert 'system_notice' in types
    autonomous = next(e for e in office.event_bus.events if e.event_type == 'autonomous')
    assert autonomous.agent_id == 'designer'
    assert '🔎' in autonomous.message


@pytest.mark.asyncio
async def test_maybe_research_skips_when_search_empty(monkeypatch, office_and_paths):
    office = office_and_paths

    monkeypatch.setattr('harness.file_reader.web_search', lambda q, m=5: '')

    async def fake_gemini(prompt: str = '', **_kw) -> str:
        raise AssertionError('LLM이 호출되면 안 됨 — 검색 결과가 없으면 조기 반환')

    monkeypatch.setattr(trend_research, 'run_gemini', fake_gemini)
    ok = await trend_research.maybe_research(office, 'planner')
    assert ok is False


@pytest.mark.asyncio
async def test_maybe_research_skips_when_llm_returns_null(monkeypatch, office_and_paths):
    office = office_and_paths

    monkeypatch.setattr(
        'harness.file_reader.web_search',
        lambda q, m=5: (
            '1. 어떤 검색 결과 제목입니다\n   https://example.com/foo\n'
            '   비교적 충분히 긴 스니펫을 반환해야 80자 길이 가드를 통과합니다.'
        ),
    )

    async def fake_gemini(prompt: str = '', **_kw) -> str:
        return 'null'

    monkeypatch.setattr(trend_research, 'run_gemini', fake_gemini)
    ok = await trend_research.maybe_research(office, 'qa')
    assert ok is False
    rules = PromptEvolver().load_rules('qa')
    assert all(r.source != 'trend_research' for r in rules)
    # 검색어는 사용된 것으로 마킹되어야 함 (반복 방지)
    state = json.loads((trend_research._STATE_PATH).read_text())
    assert state['queries_today'].get('qa')


@pytest.mark.asyncio
async def test_maybe_research_rejects_invalid_target(monkeypatch, office_and_paths):
    office = office_and_paths
    monkeypatch.setattr(
        'harness.file_reader.web_search',
        lambda q, m=5: '1. foo\n   https://example.com\n   xxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    )

    async def fake_gemini(prompt: str = '', **_kw) -> str:
        return json.dumps({
            'target_agent': 'teamlead',  # 허용되지 않는 대상
            'headline': 'x',
            'rule': '뭔가 50자 이상이지만 대상이 잘못된 규칙입니다 어쩌고 저쩌고 길게 길게',
            'evidence': '근거',
            'source': 'https://example.com',
        })

    monkeypatch.setattr(trend_research, 'run_gemini', fake_gemini)
    ok = await trend_research.maybe_research(office, 'developer')
    assert ok is False


# ── 예외 처리 / 비정상 응답 케이스 ────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_research_handles_web_search_network_error(monkeypatch, office_and_paths):
    """web_search가 네트워크 예외를 던지면 False를 반환하고 crash하지 않는다."""
    office = office_and_paths

    def failing_search(query: str, max_results: int = 5) -> str:
        raise ConnectionError('네트워크 연결 실패')

    monkeypatch.setattr('harness.file_reader.web_search', failing_search)

    async def fake_gemini(prompt: str = '', **_kw) -> str:
        raise AssertionError('LLM이 호출되면 안 됨 — 검색 자체가 실패했으므로')

    monkeypatch.setattr(trend_research, 'run_gemini', fake_gemini)
    ok = await trend_research.maybe_research(office, 'developer')
    assert ok is False


@pytest.mark.asyncio
async def test_maybe_research_handles_web_search_timeout(monkeypatch, office_and_paths):
    """web_search가 TimeoutError를 던져도 False를 반환하고 정상 종료한다."""
    office = office_and_paths

    def timeout_search(query: str, max_results: int = 5) -> str:
        raise TimeoutError('요청 시간 초과')

    monkeypatch.setattr('harness.file_reader.web_search', timeout_search)
    monkeypatch.setattr(trend_research, 'run_gemini', AsyncMock(side_effect=AssertionError))
    ok = await trend_research.maybe_research(office, 'qa')
    assert ok is False


@pytest.mark.asyncio
async def test_maybe_research_handles_gemini_exception(monkeypatch, office_and_paths):
    """run_gemini가 예외를 던지면 insight가 None이 되어 False를 반환한다."""
    office = office_and_paths

    monkeypatch.setattr(
        'harness.file_reader.web_search',
        lambda q, m=5: (
            '1. 충분히 긴 검색 결과 제목입니다\n'
            '   https://example.com/result\n'
            '   This content should be long enough to pass the 80-char guard check.'
        ),
    )

    async def failing_gemini(prompt: str = '', **_kw) -> str:
        raise RuntimeError('Gemini API 503 Service Unavailable')

    monkeypatch.setattr(trend_research, 'run_gemini', failing_gemini)
    ok = await trend_research.maybe_research(office, 'planner')
    assert ok is False
    # Gemini 실패해도 검색어는 사용된 것으로 마킹되어야 함
    state = json.loads(trend_research._STATE_PATH.read_text())
    assert state['queries_today'].get('planner')


@pytest.mark.asyncio
async def test_maybe_research_handles_malformed_json_from_gemini(monkeypatch, office_and_paths):
    """Gemini가 유효하지 않은 JSON을 반환해도 crash 없이 False를 반환한다."""
    office = office_and_paths

    monkeypatch.setattr(
        'harness.file_reader.web_search',
        lambda q, m=5: (
            '1. 검색 결과\n   https://example.com\n'
            '   길이가 충분히 길어야 80자 길이 가드를 통과합니다. 테스트용 텍스트.'
        ),
    )

    async def malformed_gemini(prompt: str = '', **_kw) -> str:
        return '{invalid json: not closed'

    monkeypatch.setattr(trend_research, 'run_gemini', malformed_gemini)
    ok = await trend_research.maybe_research(office, 'designer')
    assert ok is False


@pytest.mark.asyncio
async def test_maybe_research_handles_gemini_empty_response(monkeypatch, office_and_paths):
    """Gemini가 빈 문자열을 반환해도 False를 반환하고 crash하지 않는다."""
    office = office_and_paths

    monkeypatch.setattr(
        'harness.file_reader.web_search',
        lambda q, m=5: (
            '1. 검색 결과 항목입니다\n   https://example.com\n'
            '   테스트용 충분히 긴 스니펫 텍스트 내용입니다.'
        ),
    )

    async def empty_gemini(prompt: str = '', **_kw) -> str:
        return ''

    monkeypatch.setattr(trend_research, 'run_gemini', empty_gemini)
    ok = await trend_research.maybe_research(office, 'qa')
    assert ok is False


@pytest.mark.asyncio
async def test_extract_insight_returns_none_on_gemini_exception(monkeypatch):
    """_extract_insight: run_gemini 예외 → None 반환, 예외 전파 없음."""

    async def failing_gemini(prompt: str = '', **_kw) -> str:
        raise OSError('API 연결 거부')

    monkeypatch.setattr(trend_research, 'run_gemini', failing_gemini)
    result = await trend_research._extract_insight('developer', 'test query', '검색 결과 텍스트')
    assert result is None


@pytest.mark.asyncio
async def test_extract_insight_returns_none_on_partial_json(monkeypatch):
    """_extract_insight: Gemini가 필수 필드 누락 JSON을 반환하면 None."""

    async def partial_gemini(prompt: str = '', **_kw) -> str:
        # rule 필드가 너무 짧음 (30자 미만)
        return json.dumps({
            'target_agent': 'developer',
            'headline': '짧은 규칙',
            'rule': '짧다',
            'evidence': '근거',
            'source': 'https://example.com',
        })

    monkeypatch.setattr(trend_research, 'run_gemini', partial_gemini)
    result = await trend_research._extract_insight('developer', 'query', '검색 결과 텍스트')
    assert result is None


@pytest.mark.asyncio
async def test_research_for_discussion_handles_all_sources_failing(monkeypatch, office_and_paths):
    """research_for_discussion: 검색/RSS 모두 실패해도 None 반환, crash 없음."""
    import random as _random

    monkeypatch.setattr(_random, 'random', lambda: 0.1)  # 경로 1: 동적 검색어 강제

    async def failing_gemini(prompt: str = '', **_kw) -> str:
        raise ConnectionError('Gemini 연결 실패')

    monkeypatch.setattr(trend_research, 'run_gemini', failing_gemini)

    def failing_search(query: str, max_results: int = 5) -> str:
        raise ConnectionError('웹 검색 실패')

    monkeypatch.setattr('harness.file_reader.web_search', failing_search)

    result = await trend_research.research_for_discussion('developer')
    assert result is None


@pytest.mark.asyncio
async def test_research_for_discussion_handles_rss_failure(monkeypatch, office_and_paths):
    """research_for_discussion: RSS 피드가 모두 실패해도 None 반환."""
    import random as _random

    monkeypatch.setattr(_random, 'random', lambda: 0.6)  # 경로 2: RSS 강제

    def failing_rss(max_items: int = 8) -> list:
        raise ConnectionError('RSS 네트워크 오류')

    monkeypatch.setattr(trend_research, '_fetch_rss_items', failing_rss)

    result = await trend_research.research_for_discussion('qa')
    assert result is None


@pytest.mark.asyncio
async def test_research_for_discussion_handles_summarize_exception(monkeypatch, office_and_paths):
    """_summarize_for_discussion이 예외를 던지면 None을 반환한다."""
    import random as _random

    monkeypatch.setattr(_random, 'random', lambda: 0.9)  # 경로 3: 고정 뱅크

    monkeypatch.setattr(
        'harness.file_reader.web_search',
        lambda q, m=5: (
            '1. 충분히 긴 검색 결과 제목\n   https://example.com\n'
            '   This is long enough content to pass the minimum length guard of 80 characters.'
        ),
    )

    async def failing_summarize(speaker_name: str, raw: str, source: str) -> None:
        raise RuntimeError('요약 LLM 실패')

    monkeypatch.setattr(trend_research, '_summarize_for_discussion', failing_summarize)

    result = await trend_research.research_for_discussion('planner')
    assert result is None
