# Gemma Ollama HTTP 러너 — subprocess 대신 직접 API 호출
from __future__ import annotations
# subprocess 인자 전달 시 특수문자로 인한 잘림 문제 해결
import asyncio
import httpx
from typing import Any

from .json_parser import parse_json

OLLAMA_URL = 'http://localhost:11434'
MODEL = 'gemma4:26b'
NUM_CTX = 65536
NUM_PREDICT = 16384
REQUEST_TIMEOUT = 600.0
THINK_TIMEOUT = 60.0  # thinking 무한 반복 방지


class GemmaRunnerError(Exception):
  '''Gemma 호출 실패'''
  pass


class GemmaRunner:
  '''asyncio.Queue 기반 단일 워커 Ollama HTTP 클라이언트.

  모든 generate() 요청은 큐에 쌓이고 단일 워커가 순차 처리한다.
  subprocess 대신 Ollama /api/chat을 직접 호출하여
  특수문자 인자 전달 문제를 방지한다.
  '''

  def __init__(self):
    self._queue: asyncio.Queue = asyncio.Queue()
    self._worker_task: asyncio.Task | None = None
    self._client: httpx.AsyncClient | None = None

  async def start(self) -> None:
    '''워커 + HTTP 클라이언트 시작'''
    self._client = httpx.AsyncClient(
      base_url=OLLAMA_URL,
      timeout=REQUEST_TIMEOUT,
    )
    self._worker_task = asyncio.create_task(self._worker())

  async def stop(self) -> None:
    '''워커 + HTTP 클라이언트 종료'''
    if self._worker_task:
      self._worker_task.cancel()
      try:
        await self._worker_task
      except asyncio.CancelledError:
        pass
    if self._client:
      await self._client.aclose()

  async def _worker(self) -> None:
    '''단일 워커 — 큐에서 하나씩 처리하여 순차 처리 보장'''
    while True:
      prompt, system, future = await self._queue.get()
      try:
        result = await self._call_ollama(prompt, system)
        if not future.done():
          future.set_result(result)
      except Exception as exc:
        if not future.done():
          future.set_exception(exc)
      finally:
        self._queue.task_done()

  async def _call_ollama(self, prompt: str, system: str = '') -> str:
    '''Ollama /api/chat 호출 (스트리밍).

    think: true로 1차 시도, thinking 타임아웃 시 think: false로 재시도.
    '''
    if not self._client:
      raise GemmaRunnerError('GemmaRunner가 시작되지 않음. start()를 먼저 호출하세요.')

    # 1차: thinking ON
    result = await self._stream_chat(prompt, system, think=True)
    if result is not None:
      return result

    # thinking 타임아웃 → thinking OFF로 재시도
    result = await self._stream_chat(prompt, system, think=False)
    if result is not None:
      return result

    raise GemmaRunnerError('Ollama 응답 없음')

  async def _stream_chat(self, prompt: str, system: str, think: bool) -> str | None:
    '''Ollama /api/chat 스트리밍 호출.

    thinking 무한 반복 감지 시 None을 반환하여 재시도를 유도한다.
    '''
    messages = []
    if system:
      messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})

    body = {
      'model': MODEL,
      'messages': messages,
      'think': think,
      'stream': True,
      'options': {
        'num_ctx': NUM_CTX,
        'num_predict': NUM_PREDICT,
        'temperature': 0.7,
      },
    }

    content_parts = []
    got_content = False

    try:
      async with self._client.stream('POST', '/api/chat', json=body, timeout=REQUEST_TIMEOUT) as resp:
        resp.raise_for_status()
        think_start = asyncio.get_event_loop().time()

        async for line in resp.aiter_lines():
          if not line.strip():
            continue
          try:
            import json
            chunk = json.loads(line)
          except (ValueError, KeyError):
            continue

          # 텍스트 수집 (thinking 내용 제외, 답변만)
          msg_content = chunk.get('message', {}).get('content', '')
          if msg_content:
            if not got_content:
              got_content = True
            content_parts.append(msg_content)

          # thinking 타임아웃 체크: 답변 없이 thinking만 계속되면 중단
          if not got_content and think:
            elapsed = asyncio.get_event_loop().time() - think_start
            if elapsed > THINK_TIMEOUT:
              return None  # 타임아웃 → 재시도 유도

          # 완료 체크
          if chunk.get('done', False):
            break

    except httpx.TimeoutException:
      raise GemmaRunnerError('Ollama 요청 타임아웃')
    except httpx.HTTPStatusError as e:
      raise GemmaRunnerError(f'Ollama HTTP 오류: {e.response.status_code}')

    return ''.join(content_parts).strip() if content_parts else None

  async def generate(self, prompt: str, system: str = '') -> str:
    '''큐에 요청 추가 후 결과 대기. 순차 처리 보장.'''
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    await self._queue.put((prompt, system, future))
    return await future

  async def generate_json(self, prompt: str, system: str = '') -> Any | None:
    '''generate() + parse_json() 파이프라인'''
    raw = await self.generate(prompt, system)
    return parse_json(raw)
