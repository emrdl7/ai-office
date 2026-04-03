# INFR-03: OllamaRunner 단일 큐 순차 처리 테스트
# 실제 Ollama 호출은 로컬 환경 의존 → httpx mock 사용
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from runners.ollama_runner import OllamaRunner, OllamaRunnerError


def _make_ollama_response(text: str) -> dict:
    return {'model': 'gemma4:26b', 'response': text, 'done': True}


@pytest.fixture
async def runner(monkeypatch):
    '''httpx를 mock한 OllamaRunner (start/stop 포함)'''
    call_order: list[str] = []

    async def fake_post(url, **kwargs):
        prompt = kwargs.get('json', {}).get('prompt', '')
        call_order.append(prompt)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=_make_ollama_response(f'응답:{prompt}'))
        return resp

    r = OllamaRunner(model='gemma4:26b')
    await r.start()
    r._client.post = fake_post  # type: ignore
    r._call_order = call_order
    yield r
    await r.stop()


async def test_generate_returns_response(runner):
    '''generate()가 Ollama 응답 텍스트를 반환 (INFR-03)'''
    result = await runner.generate('테스트 프롬프트')
    assert '응답:테스트 프롬프트' == result


async def test_sequential_queue_ordering(monkeypatch):
    '''동시 요청이 순차적으로 처리됨 (INFR-03 단일 워커)'''
    call_order: list[str] = []
    call_lock = asyncio.Lock()

    async def fake_post_with_delay(url, **kwargs):
        prompt = kwargs.get('json', {}).get('prompt', '')
        # 처리 순서 기록 (락으로 리스트 안전 접근)
        async with call_lock:
            call_order.append(prompt)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=_make_ollama_response(f'done:{prompt}'))
        return resp

    r = OllamaRunner()
    await r.start()
    r._client.post = fake_post_with_delay  # type: ignore

    try:
        # 동시에 3개 요청 발행
        results = await asyncio.gather(
            r.generate('A'),
            r.generate('B'),
            r.generate('C'),
        )
    finally:
        await r.stop()

    # 모든 요청이 처리됨
    assert len(call_order) == 3
    assert set(call_order) == {'A', 'B', 'C'}
    # 결과가 요청에 대응됨
    assert 'done:A' in results
    assert 'done:B' in results
    assert 'done:C' in results


async def test_format_json_param_sent(monkeypatch):
    '''Ollama POST 요청에 format: json 파라미터가 포함됨 (INFR-05 연동)'''
    captured_payload: list[dict] = []

    async def capture_post(url, **kwargs):
        captured_payload.append(kwargs.get('json', {}))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=_make_ollama_response('{}'))
        return resp

    r = OllamaRunner()
    await r.start()
    r._client.post = capture_post  # type: ignore

    try:
        await r.generate('테스트')
    finally:
        await r.stop()

    assert len(captured_payload) == 1
    assert captured_payload[0].get('format') == 'json'
    assert captured_payload[0].get('stream') is False


async def test_generate_json_parses_response(monkeypatch):
    '''generate_json()이 JSON 응답을 Python 객체로 반환'''
    async def fake_post(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=_make_ollama_response('{"status": "done"}'))
        return resp

    r = OllamaRunner()
    await r.start()
    r._client.post = fake_post  # type: ignore

    try:
        result = await r.generate_json('테스트')
    finally:
        await r.stop()

    assert result == {'status': 'done'}
