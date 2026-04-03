# Phase 1: Infra Foundation - Research

**Researched:** 2026-04-03
**Domain:** SQLite WAL 메시지 버스, Claude CLI subprocess, Ollama/Gemma4 HTTP 클라이언트, FastAPI WebSocket 로그 버스, 파일시스템 산출물 저장
**Confidence:** HIGH (기존 STACK/ARCHITECTURE/PITFALLS 리서치 + 환경 프로브 기반)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Python (FastAPI)을 오케스트레이션 서버 언어로 사용한다. Ollama Python SDK, CrewAI 생태계와 직접 연결되며 AI 에이전트 관리에 강점이 있다.
- **D-02:** 에이전트 간 메시지 스키마를 풍부하게 설계한다. 필수 필드(type, from, to, payload, reply_to) 외에 priority, tags, metadata, ack_at, created_at, status 등을 초기부터 정의한다.
- **D-03:** 메시지 타입은 최소 task_request, task_result, status_update 3가지를 지원하며, 확장 가능하도록 type 필드 기반 디스패치 구조를 사용한다.
- **D-04:** 기능별 디렉토리 분리 — server/ (FastAPI 오케스트레이션), dashboard/ (React 프론트엔드), agents/ (Gemma4 역할별 시스템 프롬프트 및 러너), shared/ (메시지 스키마, 유틸리티).
- **D-05:** Python subprocess로 Claude CLI를 직접 호출한다. stdin/stdout JSON-lines 프로토콜로 통신하며, SDK 추상화 없이 출력 파싱을 직접 구현한다.
- **D-06:** 토큰 격리를 위해 Claude CLI 호출 시 최소한의 컨텍스트만 주입한다. 불필요한 글로벌 설정 상속을 방지한다.

### Claude's Discretion
- SQLite 테이블 스키마 상세 설계
- 로그 버스 구현 방식 (in-process event emitter vs SQLite 기반)
- Ollama HTTP 클라이언트 구현 세부사항
- atomic write 패턴 구현 방식

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFR-01 | SQLite(WAL 모드) 기반 메시지 큐로 에이전트 간 태스크 전달 및 상태 공유를 처리한다 | SQLite 3.51.0 (시스템), WAL pragma, tmp+rename atomic write 패턴 |
| INFR-02 | Claude CLI는 subprocess로 실행되며, 토큰 격리(최소 컨텍스트 주입)를 적용한다 | Claude Code 2.1.91, `--bare` + `--print` + `--output-format stream-json` 플래그 조합 |
| INFR-03 | Gemma4는 Ollama 로컬 인스턴스에서 실행되며, 단일 요청 큐로 순차 처리한다 | Ollama 0.20.0, gemma4:26b 모델 설치 확인, asyncio.Queue 기반 순차 큐 패턴 |
| INFR-04 | 모든 에이전트 이벤트를 수집하는 로그 버스가 존재하며, 대시보드에 실시간 전달된다 | FastAPI WebSocket 네이티브 지원, asyncio.Queue 팬아웃 패턴 |
| INFR-05 | Gemma4의 구조화 출력(JSON)에 대한 파싱+복구 전략이 적용된다 | Ollama `format: json` 파라미터, 2-pass 파싱(strict → repair) 패턴 |
| ARTF-01 | 모든 에이전트 산출물은 프로젝트 폴더에 실제 파일로 즉시 저장된다 | workspace/<task-id>/ 격리 디렉토리, pathlib.Path 경로 검증 패턴 |
| ARTF-02 | 산출물은 코드, 디자인 명세, 문서 등 다양한 형식을 지원한다 | 파일 확장자 기반 타입 레지스트리, 포맷 메타데이터 저장 |
</phase_requirements>

---

## Summary

Phase 1은 이후 모든 에이전트·서버 레이어가 의존하는 하부 인프라를 구축한다. 크게 세 가지 독립적인 런타임 연결(SQLite WAL 메시지 버스, Claude CLI subprocess, Ollama HTTP 클라이언트)과 두 가지 지원 시스템(WebSocket 로그 버스, workspace 파일시스템)으로 구성된다. 이 다섯 컴포넌트는 순서에 따라 테스트 가능하므로 빌드 순서가 중요하다.

환경 프로브 결과: Python 3.12는 uv를 통해 관리 가능(3.12.12 이미 uv 캐시에 존재), Ollama 0.20.0 설치됨, gemma4:26b 모델 설치 확인, Claude Code 2.1.91에 `--bare` 플래그 존재(토큰 격리 핵심). 프로젝트 레벨 Python 패키지(sqlmodel, crewai, ollama SDK 등)는 미설치 상태이므로 Wave 0에서 uv 환경 구성이 선행되어야 한다.

로그 버스는 in-process `asyncio.Queue` 방식이 권장된다. SQLite 기반 로그 버스는 대시보드와의 실시간 연결(WebSocket)에 불필요한 폴링 레이어를 추가한다. FastAPI 내부에서 `asyncio.Queue`로 이벤트를 발행하고 WebSocket 핸들러가 구독하면 폴링 없이 즉시 브로드캐스트된다.

**Primary recommendation:** uv로 Python 3.12 가상환경을 구성하고, SQLite WAL 버스 → Claude CLI runner → Ollama runner → 로그 버스 → workspace 관리자 순서로 각 컴포넌트를 독립 테스트하며 구축한다.

---

## Standard Stack

### Core (Phase 1 범위)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12.12 | 서버 런타임 | uv 캐시에 존재, asyncio 성숙, subprocess 관리 |
| FastAPI | 0.135.x | API + WebSocket 서버 | 시스템에 0.128.8 설치됨 — uv 환경에서 0.135.x 사용. WebSocket 네이티브 지원 |
| uvicorn | 0.34.x | ASGI 서버 | 시스템에 0.34.3 설치됨 — uv 환경에 복제 |
| SQLite (stdlib) | 3.51.0 | 메시지 버스 + 상태 저장소 | Python 내장, 별도 설치 불필요. WAL 모드 지원 |
| SQLModel | 0.0.22+ | SQLite ORM + Pydantic 통합 | FastAPI와 Pydantic 버전 공유. 시스템 미설치 → uv 설치 |
| httpx | 0.28.x | Ollama REST 호출 | 시스템에 0.28.1 설치됨. asyncio 네이티브 비동기 HTTP 클라이언트 |
| pydantic-settings | 2.x | 환경 설정 관리 | pydantic 2.11.7 시스템 설치됨. .env 포트/경로 분리 |

### Dev/Test

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.0.2 | 테스트 러너 | 시스템 설치됨 |
| pytest-asyncio | 0.24+ | 비동기 테스트 지원 | FastAPI WebSocket, asyncio.Queue 테스트에 필수. 미설치 → uv 설치 |
| uv | 0.9.17 | Python 패키지/환경 관리 | 시스템 설치됨. `uv sync` lockfile 기반 재현 가능 환경 |

### Not Needed in Phase 1

| Package | Why Deferred |
|---------|-------------|
| crewai 1.13.0 | Phase 2에서 에이전트 역할 정의 시 필요. Phase 1은 infra only |
| ollama Python SDK 0.6.1 | Phase 1에서는 httpx로 Ollama REST API 직접 호출 (더 투명하고 의존성 최소화). SDK는 Phase 2에서 도입 고려 |

**Installation:**
```bash
# uv로 Python 3.12 가상환경 구성 (프로젝트 루트)
uv init --python 3.12 server
cd server
uv add fastapi "uvicorn[standard]" sqlmodel pydantic-settings httpx
uv add --dev pytest pytest-asyncio httpx
```

---

## Architecture Patterns

### Recommended Project Structure (Phase 1 범위)

```
ai-office/
├── server/                        # FastAPI 오케스트레이션 서버
│   ├── pyproject.toml             # uv 프로젝트 정의
│   ├── main.py                    # FastAPI 앱 진입점, WebSocket 엔드포인트
│   ├── bus/
│   │   ├── __init__.py
│   │   ├── message_bus.py         # SQLite WAL 기반 메시지 버스
│   │   └── schemas.py             # Pydantic 메시지 스키마 (D-02, D-03)
│   ├── runners/
│   │   ├── __init__.py
│   │   ├── claude_runner.py       # Claude CLI subprocess 래퍼 (D-05, D-06)
│   │   └── ollama_runner.py       # Ollama HTTP 클라이언트 (asyncio.Queue 순차 처리)
│   ├── log_bus/
│   │   ├── __init__.py
│   │   └── event_bus.py           # asyncio.Queue 기반 인-프로세스 이벤트 버스
│   ├── workspace/
│   │   ├── __init__.py
│   │   └── manager.py             # 태스크별 격리 디렉토리 + atomic write
│   └── db/
│       ├── __init__.py
│       └── client.py              # SQLite 연결, WAL 모드 pragma, 마이그레이션
├── agents/                        # 에이전트 시스템 프롬프트 (Phase 2에서 채워짐)
│   └── .gitkeep
├── workspace/                     # 산출물 저장 루트 (런타임 생성)
│   └── .gitkeep
└── data/                          # SQLite DB 파일 (런타임 생성)
    └── .gitkeep
```

**Note:** `dashboard/`와 `shared/`는 D-04에 따라 존재하나 Phase 1에서는 비어있다. `shared/`는 Pydantic 메시지 스키마가 서버와 향후 대시보드 사이에 공유될 때 사용된다.

---

### Pattern 1: SQLite WAL 모드 메시지 버스

**What:** SQLite를 WAL(Write-Ahead Logging) 모드로 열어 다중 에이전트 동시 읽기/쓰기를 안전하게 처리. 메시지 삽입은 tmp+rename atomic write로, DB는 pragma journal_mode=WAL로 설정.

**When to use:** 모든 에이전트 간 메시지 교환.

```python
# server/db/client.py
import sqlite3
from pathlib import Path

DB_PATH = Path('data/bus.db')

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')  # WAL 모드에서 FULL 대비 2-3x 빠름
    conn.execute('PRAGMA foreign_keys=ON')
    conn.row_factory = sqlite3.Row
    return conn
```

```python
# server/bus/schemas.py
from pydantic import BaseModel, Field
from typing import Literal, Optional, Any
from datetime import datetime
import uuid

MessageType = Literal['task_request', 'task_result', 'status_update']
AgentId = Literal['claude', 'planner', 'developer', 'designer', 'qa', 'orchestrator']
Priority = Literal['normal', 'high', 'urgent']
Status = Literal['pending', 'processing', 'done', 'failed']

class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    from_agent: AgentId = Field(alias='from')
    to_agent: AgentId | Literal['broadcast'] = Field(alias='to')
    payload: Any
    reply_to: Optional[str] = None
    priority: Priority = 'normal'
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    ack_at: Optional[datetime] = None
    status: Status = 'pending'

    class Config:
        populate_by_name = True
```

**SQLite 메시지 테이블 스키마:**
```sql
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    payload     TEXT NOT NULL,  -- JSON string
    reply_to    TEXT,
    priority    TEXT NOT NULL DEFAULT 'normal',
    tags        TEXT NOT NULL DEFAULT '[]',  -- JSON array
    metadata    TEXT NOT NULL DEFAULT '{}',  -- JSON object
    created_at  TEXT NOT NULL,
    ack_at      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_messages_to_status
    ON messages(to_agent, status, created_at);
```

---

### Pattern 2: Claude CLI subprocess (토큰 격리)

**What:** `--bare` 플래그를 사용해 CLAUDE.md 자동 로드, MCP 플러그인, 훅, LSP를 모두 비활성화. `--print --output-format stream-json`으로 비대화형 JSON-lines 응답.

**핵심 발견:** Claude Code 2.1.91에 `--bare` 플래그 존재 확인됨. 이 플래그는 CLAUDE.md 자동 탐색, 훅, 플러그인 동기화, 키체인 읽기를 모두 차단하며 CLAUDE_CODE_SIMPLE=1을 설정한다. PITFALLS Pitfall 1에서 기술한 토큰 폭발 문제의 직접적 해결책.

```python
# server/runners/claude_runner.py
import subprocess
import json
import asyncio
from pathlib import Path

ISOLATION_DIR = Path('/tmp/ai-office-claude-isolated')

async def run_claude_isolated(prompt: str) -> str:
    '''
    --bare: CLAUDE.md 자동 로드, MCP, 훅, 플러그인 모두 비활성화
    --print: 비대화형 모드 (stdin → stdout → 종료)
    --output-format stream-json: JSON-lines 응답
    --no-session-persistence: 세션을 디스크에 저장하지 않음
    '''
    ISOLATION_DIR.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        'claude',
        '--bare',
        '--print',
        '--output-format', 'stream-json',
        '--no-session-persistence',
        prompt,
        cwd=str(ISOLATION_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    result_text = []
    stdout, stderr = await proc.communicate()

    for line in stdout.decode().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            # stream-json 이벤트: type='assistant', content 추출
            if msg.get('type') == 'assistant':
                for block in msg.get('message', {}).get('content', []):
                    if block.get('type') == 'text':
                        result_text.append(block['text'])
        except json.JSONDecodeError:
            pass  # 파싱 불가 라인 무시

    return ''.join(result_text)
```

**중요:** `--bare` + 격리 디렉토리 조합으로 토큰 격리 달성. `--setting-sources project,local` 플래그도 추가 방어층으로 사용 가능하나, `--bare`만으로 CLAUDE.md 자동 발견을 차단한다.

---

### Pattern 3: Ollama 단일 요청 큐 (순차 처리)

**What:** `asyncio.Queue`로 Ollama 요청을 직렬화. OLLAMA_NUM_PARALLEL=1 설정과 함께 사용해 Gemma4 메모리 과부하 방지.

**환경 확인:** Ollama 0.20.0, gemma4:26b 설치됨 (17GB, 현재 GPU 100%로 32768 컨텍스트 실행 중).

```python
# server/runners/ollama_runner.py
import asyncio
import httpx
import json
from typing import Any

OLLAMA_BASE_URL = 'http://localhost:11434'
DEFAULT_MODEL = 'gemma4:26b'

class OllamaRunner:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self._queue: asyncio.Queue = asyncio.Queue()
        self._client = httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=120.0)
        self._worker_task: asyncio.Task | None = None

    async def start(self):
        '''FastAPI lifespan에서 호출'''
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        await self._queue.join()
        if self._worker_task:
            self._worker_task.cancel()
        await self._client.aclose()

    async def _worker(self):
        '''단일 워커 — 순차 처리 보장'''
        while True:
            prompt, response_future = await self._queue.get()
            try:
                result = await self._call_ollama(prompt)
                response_future.set_result(result)
            except Exception as exc:
                response_future.set_exception(exc)
            finally:
                self._queue.task_done()

    async def _call_ollama(self, prompt: str) -> str:
        response = await self._client.post('/api/generate', json={
            'model': self.model,
            'prompt': prompt,
            'format': 'json',   # Gemma4 구조화 출력 활성화
            'stream': False,
        })
        response.raise_for_status()
        return response.json()['response']

    async def generate(self, prompt: str) -> str:
        '''큐에 요청 추가 후 결과 대기'''
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put((prompt, future))
        return await future
```

---

### Pattern 4: asyncio.Queue 기반 로그 버스 (in-process)

**What:** FastAPI 프로세스 내부의 `asyncio.Queue`로 이벤트를 발행하고 WebSocket 핸들러가 구독. SQLite를 경유하지 않아 즉시 브로드캐스트.

**결정 근거 (Claude's Discretion):** SQLite 기반 로그 버스는 폴링 레이어가 필요하고 실시간성이 낮음. in-process asyncio.Queue는 FastAPI와 동일 프로세스라 오버헤드 없이 즉시 WebSocket 팬아웃 가능. 로그 영속화가 필요하면 발행 시 SQLite에도 동시 기록.

```python
# server/log_bus/event_bus.py
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import uuid

@dataclass
class LogEvent:
    agent_id: str
    event_type: str   # 'log', 'status_change', 'task_start', 'task_done', 'error'
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

class EventBus:
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.remove(q)

    async def publish(self, event: LogEvent):
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 느린 클라이언트 드롭, 버스는 블록되지 않음

# FastAPI WebSocket 엔드포인트 예시
# @app.websocket('/ws/logs')
# async def log_stream(ws: WebSocket):
#     await ws.accept()
#     q = event_bus.subscribe()
#     try:
#         while True:
#             event = await q.get()
#             await ws.send_json(asdict(event))
#     finally:
#         event_bus.unsubscribe(q)
```

---

### Pattern 5: atomic write + 경로 검증 (workspace)

**What:** 모든 파일 쓰기는 tmp+rename 패턴. 경로는 workspace/<task-id>/ 하위로만 허용.

```python
# server/workspace/manager.py
import os
import json
from pathlib import Path
from typing import Literal

WORKSPACE_ROOT = Path('workspace')
SUPPORTED_TYPES = {
    'code': ['.py', '.ts', '.js', '.tsx', '.jsx', '.html', '.css', '.scss'],
    'doc': ['.md', '.txt', '.rst'],
    'design': ['.json', '.yaml', '.yml'],
    'data': ['.csv', '.json'],
}

class WorkspaceManager:
    def __init__(self, task_id: str):
        self.task_dir = WORKSPACE_ROOT / task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def safe_path(self, relative_path: str) -> Path:
        '''경로 순회 공격 방지 — workspace/<task-id>/ 외부 접근 차단'''
        target = (self.task_dir / relative_path).resolve()
        if not str(target).startswith(str(self.task_dir.resolve())):
            raise ValueError(f'경로 순회 감지: {relative_path}')
        return target

    def write_artifact(self, relative_path: str, content: str | bytes) -> Path:
        '''atomic write: tmp 파일 쓰고 rename'''
        target = self.safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = target.with_suffix(target.suffix + f'.tmp.{os.getpid()}')
        try:
            mode = 'wb' if isinstance(content, bytes) else 'w'
            encoding = None if isinstance(content, bytes) else 'utf-8'
            with open(tmp_path, mode, encoding=encoding) as f:
                f.write(content)
            os.rename(tmp_path, target)  # macOS APFS에서 원자적
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return target
```

---

### Anti-Patterns to Avoid

- **직접 파일 쓰기:** `open(path, 'w').write(...)` 사용 금지 — 반드시 tmp+rename 패턴 사용
- **SQLite WAL 없이 열기:** `sqlite3.connect(path)` 단독 사용 시 journal_mode 기본값(DELETE)으로 열림 — 반드시 `PRAGMA journal_mode=WAL` 적용
- **Claude CLI를 `--bare` 없이 subprocess 실행:** CLAUDE.md + MCP + 훅이 모두 주입되어 토큰 폭발 발생
- **Ollama 동시 요청:** asyncio.Queue 없이 여러 coroutine에서 Ollama 직접 호출 시 gemma4:26b 메모리 압박으로 모델 스래싱 발생
- **경로 검증 없이 에이전트 파일 쓰기:** LLM이 할루시네이션한 경로(`../../etc/passwd` 등)로 쓰기 가능 — 항상 `safe_path()`로 검증

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQLite 동시 쓰기 안전성 | 커스텀 파일 락 | SQLite WAL pragma | WAL 모드가 이미 MVCC 제공, 중복 구현 불필요 |
| JSON-lines 스트림 파싱 | 커스텀 버퍼 파서 | `stdout.splitlines()` + `json.loads` per line | JSON-lines는 줄 단위 파싱이 표준, 중간 버퍼 불필요 |
| HTTP 비동기 클라이언트 | `urllib` 래퍼 | `httpx.AsyncClient` | 이미 시스템에 0.28.1 설치, asyncio 네이티브 |
| 환경 설정 파싱 | argparse / os.environ 직접 | `pydantic-settings` | `.env` 파일 + 타입 안전성 자동 제공 |
| WebSocket 연결 관리 | 커스텀 소켓 서버 | FastAPI WebSocket | Starlette 기반 네이티브 지원, 재연결 처리 포함 |

**Key insight:** Phase 1 인프라 컴포넌트는 모두 Python stdlib 또는 이미 시스템에 설치된 패키지로 구현 가능하다. 새 대형 의존성(crewai, ollama SDK)은 Phase 2 진입 전까지 불필요.

---

## Common Pitfalls

### Pitfall 1: Claude CLI 토큰 폭발 (CRITICAL)
**What goes wrong:** `--bare` 없이 subprocess 실행 시 CLAUDE.md + MCP 플러그인 + 훅이 모두 주입되어 단일 호출에 ~50,000 토큰 소모.
**Why it happens:** CLI는 대화형 단일 세션용으로 설계 — 전체 사용자 컨텍스트를 자동으로 상속.
**How to avoid:** `--bare --print --output-format stream-json --no-session-persistence` 조합 필수. 격리 디렉토리(`/tmp/ai-office-claude-isolated/`)에서 실행해 추가 CLAUDE.md 탐색 차단.
**Warning signs:** 첫 응답 전 10-30초 지연, 토큰 카운터 급등.

### Pitfall 2: Ollama 메모리 스래싱
**What goes wrong:** gemma4:26b는 17GB. 동시 요청 시 Ollama가 추가 컨텍스트 슬롯 확장 → 통합 메모리 초과 → 모델 언로드/리로드 반복.
**How to avoid:** `asyncio.Queue` 단일 워커 패턴으로 요청 직렬화. Ollama 설정에 `OLLAMA_NUM_PARALLEL=1` 환경변수. 큐 깊이 모니터링.
**Warning signs:** `ollama ps`에서 모델이 자주 사라졌다 나타남, 응답 시간이 첫 요청보다 이후 요청이 더 김.

### Pitfall 3: SQLite 동시 쓰기 락 타임아웃
**What goes wrong:** WAL 모드에서도 동시 쓰기가 많으면 `SQLITE_BUSY` 에러 발생.
**How to avoid:** `PRAGMA busy_timeout = 5000` (5초) 설정. 쓰기 트랜잭션을 짧게 유지. SQLModel의 `session.commit()`으로 트랜잭션 즉시 닫기.
**Warning signs:** `sqlite3.OperationalError: database is locked` 에러.

### Pitfall 4: asyncio.Queue 구독자 메모리 누수
**What goes wrong:** WebSocket 연결 종료 시 `unsubscribe()` 호출 없으면 이벤트 버스가 닫힌 큐에 계속 put_nowait 시도.
**How to avoid:** `finally:` 블록에서 반드시 `unsubscribe()`. `maxsize=500` 설정으로 큐 무한 성장 방지.

### Pitfall 5: atomic write 실패 시 tmp 파일 잔존
**What goes wrong:** `os.rename()` 전에 프로세스가 종료되면 `.tmp.{pid}` 파일이 workspace에 남음.
**How to avoid:** `try/except` 블록에서 tmp 파일을 `unlink(missing_ok=True)`로 정리. 서버 시작 시 workspace의 `.tmp.*` 파일을 클린업하는 초기화 루틴 추가.

---

## Code Examples

### FastAPI 앱 진입점 (lifespan)

```python
# server/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from .runners.ollama_runner import OllamaRunner
from .log_bus.event_bus import EventBus
from dataclasses import asdict

ollama_runner = OllamaRunner()
event_bus = EventBus()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ollama_runner.start()
    yield
    await ollama_runner.stop()

app = FastAPI(lifespan=lifespan)

@app.websocket('/ws/logs')
async def log_stream(ws: WebSocket):
    await ws.accept()
    q = event_bus.subscribe()
    try:
        while True:
            event = await q.get()
            await ws.send_json(asdict(event))
    except Exception:
        pass
    finally:
        event_bus.unsubscribe(q)
```

### SQLite WAL 활성화 확인 테스트

```python
# server/tests/test_db.py
import sqlite3
import pytest
from server.db.client import get_connection

def test_wal_mode_enabled():
    conn = get_connection()
    result = conn.execute('PRAGMA journal_mode').fetchone()
    assert result[0] == 'wal'
    conn.close()
```

### Ollama REST 직접 호출 (httpx)

```python
# Ollama /api/generate 호출 — format: json으로 구조화 출력 강제
async def _call_ollama(self, prompt: str) -> str:
    response = await self._client.post('/api/generate', json={
        'model': self.model,
        'prompt': prompt,
        'format': 'json',
        'stream': False,
        'options': {
            'num_ctx': 4096,     # 최소 컨텍스트로 메모리 절약
            'temperature': 0.1,  # 구조화 출력 안정성
        },
    })
    response.raise_for_status()
    raw = response.json()['response']
    return self._safe_parse_json(raw)

def _safe_parse_json(self, raw: str) -> str:
    '''2-pass 파싱: strict → markdown 코드블록 추출 → 폴백'''
    import json, re
    try:
        json.loads(raw)   # 유효하면 그대로 반환
        return raw
    except json.JSONDecodeError:
        # markdown 코드블록 추출 시도
        match = re.search(r'```(?:json)?\n(.*?)\n```', raw, re.DOTALL)
        if match:
            return match.group(1)
        return raw  # 복구 불가 시 원본 반환하고 상위에서 로깅
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SQLite 기본 journal 모드 | WAL 모드 | SQLite 3.7.0 (2010) | 읽기/쓰기 동시성, 다중 에이전트 환경 필수 |
| `subprocess.Popen` 동기 호출 | `asyncio.create_subprocess_exec` | Python 3.4+ | FastAPI 이벤트 루프 블로킹 없이 Claude CLI 실행 |
| Ollama streaming=True 스트림 처리 | streaming=False + format:json | Ollama 0.1.x+ | 구조화 출력 용도에서는 완성된 JSON 단일 수신이 파싱 안전 |
| Claude CLI `--print` 단독 | `--bare --print` 조합 | Claude Code 2.x | 토큰 격리 — CLAUDE.md, MCP, 훅 차단 |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | 서버 런타임 | uv 관리 | 3.12.12 (uv 캐시) | — |
| Python 3.11 (시스템) | fallback | ✓ | 3.11.13 | uv로 3.12 사용 |
| uv | 패키지 관리 | ✓ | 0.9.17 | — |
| Ollama | Gemma4 실행 | ✓ | 0.20.0 | — |
| gemma4:26b | 에이전트 모델 | ✓ | 설치됨 (17GB) | gemma4:e4b (더 작음) |
| claude (CLI) | Claude runner | ✓ | Claude Code 2.1.91 | — |
| `--bare` flag | 토큰 격리 | ✓ | 2.1.91 확인 | `--setting-sources project,local` (약한 격리) |
| sqlite3 | 메시지 버스 | ✓ | 3.51.0 (내장) | — |
| fastapi | API 서버 | ✓ (시스템 0.128.8) | uv 환경에서 0.135.x | — |
| httpx | Ollama HTTP | ✓ | 0.28.1 | — |
| pytest | 테스트 | ✓ | 9.0.2 | — |
| sqlmodel | SQLite ORM | ✗ | — | `uv add sqlmodel` |
| pytest-asyncio | 비동기 테스트 | ✗ | — | `uv add --dev pytest-asyncio` |
| Node.js | 대시보드 빌드 | ✓ | 22.21.1 | — (Phase 4까지 불필요) |

**Missing dependencies with no fallback:**
- 없음 — 모든 블로킹 의존성 설치 가능

**Missing dependencies with fallback:**
- `sqlmodel`: `uv add sqlmodel`로 즉시 해결
- `pytest-asyncio`: `uv add --dev pytest-asyncio`로 즉시 해결

**중요 관찰:** 현재 gemma4:26b 모델이 GPU 100%로 실행 중 (32768 컨텍스트). Phase 1 Ollama 테스트 전에 기존 세션 종료 필요. `ollama stop gemma4:26b` 또는 Ollama 재시작.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 0.24+ |
| Config file | `server/pyproject.toml` — `[tool.pytest.ini_options]` 섹션 |
| Quick run command | `cd server && pytest tests/ -x -q` |
| Full suite command | `cd server && pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFR-01 | SQLite WAL 모드 활성화 확인 | unit | `pytest tests/test_db.py::test_wal_mode_enabled -x` | ❌ Wave 0 |
| INFR-01 | 메시지 왕복 (write → read) | integration | `pytest tests/test_message_bus.py::test_message_roundtrip -x` | ❌ Wave 0 |
| INFR-01 | atomic write tmp+rename 패턴 | unit | `pytest tests/test_message_bus.py::test_atomic_write -x` | ❌ Wave 0 |
| INFR-02 | Claude CLI subprocess 실행 및 JSON-lines 응답 | integration | `pytest tests/test_claude_runner.py::test_run_claude_isolated -x` | ❌ Wave 0 |
| INFR-02 | `--bare` 플래그로 CLAUDE.md 차단 확인 | integration | `pytest tests/test_claude_runner.py::test_token_isolation -x` | ❌ Wave 0 |
| INFR-03 | Ollama REST 호출 및 응답 수신 | integration | `pytest tests/test_ollama_runner.py::test_ollama_generate -x` | ❌ Wave 0 |
| INFR-03 | 단일 큐 순차 처리 확인 (동시 요청 → 순차 실행) | integration | `pytest tests/test_ollama_runner.py::test_sequential_queue -x` | ❌ Wave 0 |
| INFR-04 | EventBus 발행 → WebSocket 수신 | integration | `pytest tests/test_event_bus.py::test_publish_subscribe -x` | ❌ Wave 0 |
| INFR-05 | Gemma4 JSON 출력 2-pass 파싱 | unit | `pytest tests/test_ollama_runner.py::test_json_repair -x` | ❌ Wave 0 |
| ARTF-01 | workspace/<task-id>/ 격리 디렉토리 생성 및 파일 저장 | unit | `pytest tests/test_workspace.py::test_write_artifact -x` | ❌ Wave 0 |
| ARTF-01 | 경로 순회 공격 방지 | unit | `pytest tests/test_workspace.py::test_path_traversal_blocked -x` | ❌ Wave 0 |
| ARTF-02 | 다양한 포맷(.py, .md, .json) 파일 저장 | unit | `pytest tests/test_workspace.py::test_multiple_formats -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd server && pytest tests/ -x -q`
- **Per wave merge:** `cd server && pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `server/tests/__init__.py` — 테스트 패키지
- [ ] `server/tests/conftest.py` — 공유 픽스처 (tmp DB, 임시 workspace 경로)
- [ ] `server/tests/test_db.py` — INFR-01 DB 레이어 테스트
- [ ] `server/tests/test_message_bus.py` — INFR-01 메시지 버스 테스트
- [ ] `server/tests/test_claude_runner.py` — INFR-02 Claude runner 테스트
- [ ] `server/tests/test_ollama_runner.py` — INFR-03, INFR-05 Ollama runner 테스트
- [ ] `server/tests/test_event_bus.py` — INFR-04 이벤트 버스 테스트
- [ ] `server/tests/test_workspace.py` — ARTF-01, ARTF-02 workspace 테스트
- [ ] Framework install: `cd server && uv add --dev pytest pytest-asyncio` — pytest-asyncio 미설치

---

## Project Constraints (from CLAUDE.md)

전역 CLAUDE.md (사용자 레벨) 적용 지시사항:
- **CSS 방법론:** BEM — Phase 1은 백엔드/인프라 only, CSS 없음. 적용 제외.
- **전처리기:** SCSS (dart-sass) — Phase 1 적용 제외.
- **패키지 매니저:** npm — 프론트엔드 한정. 백엔드는 uv 사용 (프로젝트 CLAUDE.md에 명시됨).
- **들여쓰기:** 2 spaces — Python은 PEP 8 기준 4 spaces. **Python 파일은 4 spaces, 향후 TypeScript/JS는 2 spaces 적용.**
- **따옴표:** single quote — Python 코드에서 `'single'` 사용.
- **세미콜론 없음:** Python 기본값과 일치.
- **주석 한국어:** Python docstring 및 인라인 주석은 한국어로 작성.
- **인라인 스타일 사용 금지:** Phase 1 적용 없음.
- **`!important` 사용 금지:** Phase 1 적용 없음.
- **`alt` 속성 필수, `aria-label` 필수, 키보드 네비게이션 지원:** Phase 1 적용 없음 (UI 없음).

**프로젝트 CLAUDE.md 추가 제약:**
- GSD workflow 외 직접 파일 편집 금지 (`/gsd:execute-phase` 경유)
- AI 런타임: Claude = CLI only, Gemma4 = Ollama 로컬 only
- 외부 API/클라우드 서비스 사용 금지

---

## Open Questions

1. **Python 3.9.6 vs 3.12 — 시스템 Python 충돌 가능성**
   - What we know: 시스템 Python은 3.9.6, uv에 3.12.12 캐시됨
   - What's unclear: 일부 macOS 시스템 도구가 `/usr/bin/python3` 사용 시 uv 가상환경과 충돌 여부
   - Recommendation: `uv init --python 3.12 server`로 프로젝트 격리. 가상환경 활성화 후 개발.

2. **gemma4:26b vs e4b 선택**
   - What we know: gemma4:26b (17GB) 설치됨. STACK.md는 16GB RAM 기준 e4b 권장.
   - What's unclear: 현재 머신의 실제 RAM이 몇 GB인지 프로브하지 않음.
   - Recommendation: 첫 Ollama 테스트에서 응답 시간과 `ollama ps` 메모리 사용량 측정. 스래싱 발생 시 gemma4:e4b로 전환.

3. **Claude CLI `--bare` + OAuth 인증**
   - What we know: `--bare` 모드에서 "OAuth와 키체인은 읽지 않음, ANTHROPIC_API_KEY 또는 apiKeyHelper 필요"
   - What's unclear: 현재 환경의 인증 방식이 API Key인지 OAuth인지 미확인
   - Recommendation: `echo 'hello' | claude --bare --print` 연기 전 인증 테스트 먼저 실행.

---

## Sources

### Primary (HIGH confidence)
- Claude Code 2.1.91 `--help` 출력 — `--bare`, `--print`, `--output-format`, `--no-session-persistence` 플래그 직접 확인
- SQLite 3.51.0 stdlib — WAL pragma, atomic rename macOS APFS 보장
- Ollama 0.20.0 `/api/generate` API — `format: json` 파라미터 확인 (공식 REST API)
- `.planning/research/PITFALLS.md` — Claude CLI 토큰 폭발(Pitfall 1), atomic write(Pitfall 6), Ollama 직렬화(Pitfall 2)
- `.planning/research/STACK.md` — 검증된 스택 버전
- `.planning/research/ARCHITECTURE.md` — Hub-Spoke 패턴, 빌드 순서

### Secondary (MEDIUM confidence)
- `.planning/phases/01-infra-foundation/01-CONTEXT.md` — 사용자 결정사항 직접 출처
- 환경 프로브 결과 (2026-04-03) — `ollama list`, `python3 -c "import ..."`, `claude --version`

### Tertiary (LOW confidence)
- 없음

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 시스템 환경 직접 프로브, 설치 버전 확인
- Architecture: HIGH — 기존 ARCHITECTURE.md 기반 + Phase 1 범위로 구체화
- Pitfalls: HIGH — PITFALLS.md 기존 연구 (다중 독립 소스 검증됨) + 환경 특이사항 추가

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (Ollama, Claude CLI 버전은 빠르게 변경될 수 있음)
