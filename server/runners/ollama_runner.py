# Ollama HTTP 클라이언트 + 단일 요청 큐 (INFR-03)
# asyncio.Queue 단일 워커로 gemma4:26b 메모리 스래싱 방지 (Pitfall 2)
import asyncio
import httpx
from typing import Any

from .json_parser import parse_json

OLLAMA_BASE_URL = 'http://localhost:11434'
DEFAULT_MODEL = 'gemma4:26b'
REQUEST_TIMEOUT = 120.0  # gemma4:26b 초기 로딩 고려


class OllamaRunnerError(Exception):
    '''Ollama HTTP 호출 실패'''
    pass


class OllamaRunner:
    '''asyncio.Queue 기반 단일 워커 Ollama 클라이언트.

    모든 generate() 요청은 큐에 쌓이고 단일 워커가 순차 처리한다.
    이를 통해 gemma4:26b의 메모리 압박으로 인한 모델 스래싱을 방지한다.

    사용 예시 (FastAPI lifespan):
        runner = OllamaRunner()
        await runner.start()   # lifespan startup
        result = await runner.generate("설계 문서를 작성해줘")
        await runner.stop()    # lifespan shutdown
    '''

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        timeout: float = REQUEST_TIMEOUT,
    ):
        self.model = model
        self._base_url = base_url
        self._timeout = timeout
        self._queue: asyncio.Queue = asyncio.Queue()
        self._client: httpx.AsyncClient | None = None
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        '''워커 시작. FastAPI lifespan startup에서 호출.'''
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        '''워커 종료. FastAPI lifespan shutdown에서 호출.'''
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
        '''Ollama /api/generate 호출.

        format=json으로 구조화 출력 요청.
        system이 주어지면 에이전트 시스템 프롬프트를 주입한다 (D-03).
        응답의 'response' 필드 반환.
        '''
        if not self._client:
            raise OllamaRunnerError('OllamaRunner가 시작되지 않음. start()를 먼저 호출하세요.')

        # POST body 구성 — system이 있을 때만 추가
        body = {
            'model': self.model,
            'prompt': prompt,
            'format': 'json',   # Gemma4 구조화 출력 활성화
            'stream': False,
        }
        if system:
            body['system'] = system

        response = await self._client.post('/api/generate', json=body)
        response.raise_for_status()
        data = response.json()
        return data['response']

    async def generate(self, prompt: str, system: str = '') -> str:
        '''큐에 요청 추가 후 결과 대기.

        동시 호출 시 순차 처리됨 (단일 워커 보장).
        system 파라미터로 에이전트 시스템 프롬프트 주입 가능 (D-03).
        반환값은 Ollama raw 응답 문자열 (JSON 파싱은 호출자 책임).
        '''
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put((prompt, system, future))
        return await future

    async def generate_json(self, prompt: str, system: str = '') -> Any | None:
        '''generate() + parse_json() 파이프라인.

        Gemma4 JSON 출력을 2-pass 파싱하여 Python 객체로 반환.
        system 파라미터로 에이전트 시스템 프롬프트 주입 가능 (D-03).
        복구 불가 시 None 반환.
        '''
        raw = await self.generate(prompt, system)
        return parse_json(raw)
