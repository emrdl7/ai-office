# Groq 클라우드 러너 — 무료 LLM API (Llama 3.3 70B)
from __future__ import annotations
import asyncio
import httpx
import json
import os
from typing import Any

from .json_parser import parse_json

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = 'llama-3.3-70b-versatile'
MAX_TOKENS = 8192
REQUEST_TIMEOUT = 120.0


class GroqRunnerError(Exception):
  pass


class GroqRunner:
  '''Groq 클라우드 API 클라이언트.

  OpenAI 호환 API로 Llama 3.3 70B를 호출한다.
  무료 한도: 분당 30회, 일 14,400회.
  '''

  def __init__(self):
    self._client: httpx.AsyncClient | None = None
    self._api_key = os.environ.get('GROQ_API_KEY', '')

  async def start(self) -> None:
    self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

  async def stop(self) -> None:
    if self._client:
      await self._client.aclose()

  async def generate(self, prompt: str, system: str = '', model: str = '') -> str:
    '''Groq API를 호출하여 텍스트 응답을 반환한다.'''
    if not self._client:
      await self.start()
    assert self._client is not None  # start() 후 보장

    if not self._api_key:
      raise GroqRunnerError('GROQ_API_KEY가 설정되지 않았습니다.')

    messages = []
    if system:
      messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})

    body = {
      'model': model or MODEL,
      'messages': messages,
      'max_tokens': MAX_TOKENS,
      'temperature': 0.7,
    }

    max_retries = 3
    for attempt in range(max_retries):
      try:
        resp = await self._client.post(
          GROQ_URL,
          json=body,
          headers={
            'Authorization': f'Bearer {self._api_key}',
            'Content-Type': 'application/json',
          },
        )
        resp.raise_for_status()
        data = resp.json()
        content: str = data['choices'][0]['message']['content']
        return content.strip()
      except httpx.TimeoutException:
        raise GroqRunnerError(f'Groq 타임아웃 ({REQUEST_TIMEOUT}초)')
      except httpx.HTTPStatusError as e:
        if e.response.status_code == 429 and attempt < max_retries - 1:
          # Rate limit — 대기 후 재시도
          wait = (attempt + 1) * 10  # 10초, 20초
          await asyncio.sleep(wait)
          continue
        error_body = e.response.text[:300]
        raise GroqRunnerError(f'Groq HTTP {e.response.status_code}: {error_body}')
      except (KeyError, IndexError) as e:
        raise GroqRunnerError(f'Groq 응답 파싱 실패: {e}')
    raise GroqRunnerError(f'Groq 재시도 {max_retries}회 초과')

  async def generate_json(self, prompt: str, system: str = '') -> Any | None:
    '''generate() + JSON 파싱 파이프라인'''
    raw = await self.generate(prompt, system)
    return parse_json(raw)
