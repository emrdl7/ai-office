---
phase: 01-infra-foundation
verified: 2026-04-03T00:00:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Phase 1: Infra Foundation Verification Report

**Phase Goal:** 모든 에이전트와 서버가 의존하는 로컬 인프라가 가동되고 검증된다
**Verified:** 2026-04-03
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SQLite WAL 모드 메시지 버스에 메시지를 쓰고 읽는 왕복이 성공하며, atomic write(tmp+rename) 패턴이 적용된다 | VERIFIED | `test_message_bus.py` 5개 테스트 PASSED. `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000` 적용 확인. 파일 기반 DB에서 WAL 모드 실제 활성화 확인(`journal_mode=wal`). |
| 2 | Claude CLI가 subprocess로 실행되어 JSON-lines 응답을 반환하고, 불필요한 컨텍스트 주입 없이 최소 토큰으로 동작한다 | VERIFIED | `test_claude_runner.py` 5개 테스트 PASSED. `--bare`, `--print`, `--output-format stream-json`, `--no-session-persistence` 플래그 확인. `/tmp/ai-office-claude-isolated` 격리 디렉토리 CWD 확인. |
| 3 | Ollama/Gemma4가 HTTP REST 호출을 받아 응답하며, 단일 요청 큐로 순차 처리됨이 확인된다 | VERIFIED | `test_ollama_runner.py` 4개 테스트 PASSED. `asyncio.Queue` 단일 워커, `format: json` 파라미터, `parse_json` 연동 모두 확인. `test_sequential_queue_ordering` 동시 3개 요청 순차 처리 검증. |
| 4 | 에이전트 이벤트가 로그 버스에 기록되고 WebSocket 채널로 브로드캐스트된다 | VERIFIED | `test_log_bus.py` 6개 테스트 PASSED. EventBus pub/sub/unsubscribe, QueueFull 드롭 처리 확인. FastAPI `/ws/logs` WebSocket 엔드포인트 및 `finally` 구독 해제 확인. |
| 5 | 에이전트가 생성한 파일이 태스크별 격리 디렉토리(`workspace/<task-id>/`)에 즉시 저장되며, 코드·문서·디자인 명세 등 다양한 형식으로 저장된다 | VERIFIED | `test_workspace.py` 7개 테스트 PASSED. `os.rename` atomic write 확인, 경로 순회 차단(`ValueError`) 확인, `.py/.md/.json/.css/.yaml/.tsx` 다중 형식 저장 확인. |

**Score:** 5/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/pyproject.toml` | uv 프로젝트 정의, 의존성 선언 | VERIFIED | `fastapi`, `uvicorn`, `sqlmodel`, `httpx`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `asyncio_mode = "auto"` 모두 포함 |
| `server/db/client.py` | SQLite WAL 연결 관리 | VERIFIED | `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA synchronous=NORMAL`, `check_same_thread=False`, `init_schema()` 모두 포함 |
| `server/bus/schemas.py` | AgentMessage Pydantic 스키마 | VERIFIED | `AgentMessage`, `MessageType`, `AgentId`, `Priority`, `Status` 모두 정의. 11개 필드 모두 포함 |
| `server/bus/message_bus.py` | MessageBus publish/consume/ack | VERIFIED | `class MessageBus`, `publish`, `consume`, `ack`, `json.dumps` payload 직렬화 모두 포함 |
| `server/workspace/manager.py` | WorkspaceManager atomic write + 경로 검증 | VERIFIED | `class WorkspaceManager`, `os.rename`, `경로 순회 감지`, `SUPPORTED_EXTENSIONS` 딕셔너리 모두 포함 |
| `server/runners/json_parser.py` | Gemma4 JSON 2-pass 파싱+복구 | VERIFIED | `parse_json`, `_extract_json_block`, `_remove_trailing_commas` 모두 구현 |
| `server/runners/claude_runner.py` | run_claude_isolated() 비동기 함수 | VERIFIED | `--bare`, `ISOLATION_DIR`, `ClaudeRunnerError`, `asyncio.create_subprocess_exec` 모두 포함 |
| `server/runners/ollama_runner.py` | OllamaRunner asyncio.Queue 단일 워커 | VERIFIED | `asyncio.Queue`, `async def _worker`, `'format': 'json'`, `from .json_parser import parse_json` 모두 포함 |
| `server/log_bus/event_bus.py` | EventBus subscribe/publish/unsubscribe | VERIFIED | `class EventBus`, `class LogEvent`, `maxsize=500`, `asyncio.QueueFull`, `event_bus = EventBus()` 싱글턴 모두 포함 |
| `server/main.py` | FastAPI 앱 + /ws/logs WebSocket | VERIFIED | `@app.websocket('/ws/logs')`, `event_bus.subscribe()`, `event_bus.unsubscribe(q)` (finally 블록), `await ws.send_json`, `lifespan`, `ollama_runner.start()` 모두 포함 |
| `server/tests/conftest.py` | pytest fixture (in_memory_db, tmp_workspace) | VERIFIED | `:memory:` SQLite fixture, `tmp_workspace` fixture 모두 존재 |
| `agents/.gitkeep` | 에이전트 디렉토리 | VERIFIED | 존재 |
| `workspace/.gitkeep` | 워크스페이스 디렉토리 | VERIFIED | 존재 |
| `data/.gitkeep` | 데이터 디렉토리 | VERIFIED | 존재 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `server/tests/conftest.py` | `server/db/client.py` | in-memory SQLite fixture | WIRED | `:memory:` 패턴 존재, fixture에서 WAL PRAGMA 직접 설정 |
| `server/bus/schemas.py` | `server/bus/message_bus.py` | AgentMessage import | WIRED | `from .schemas import AgentMessage` 확인 |
| `server/bus/message_bus.py` | `server/db/client.py` | get_connection() 호출 | WIRED | `from db.client import get_connection, init_schema` 확인 |
| `server/workspace/manager.py` | `workspace/<task-id>/` | safe_path() + write_artifact() | WIRED | `os.rename` atomic write 패턴 구현 확인 |
| `server/runners/ollama_runner.py` | `http://localhost:11434/api/generate` | httpx.AsyncClient.post() | WIRED | `httpx.AsyncClient`, `/api/generate` POST 호출 확인 |
| `server/runners/json_parser.py` | `server/runners/ollama_runner.py` | generate() 결과 parse_json 사용 | WIRED | `from .json_parser import parse_json`, `generate_json()` 파이프라인 확인 |
| `server/main.py` | `server/log_bus/event_bus.py` | event_bus 싱글턴 + WebSocket 핸들러 | WIRED | `event_bus.subscribe()`, `event_bus.unsubscribe(q)` 모두 `/ws/logs` 핸들러 내부에서 사용 |
| `server/runners/claude_runner.py` | claude CLI | asyncio.create_subprocess_exec | WIRED | `asyncio.create_subprocess_exec('claude', '--bare', ...)` 확인 |

---

### Data-Flow Trace (Level 4)

이 페이즈는 데이터를 렌더링하는 UI 컴포넌트가 없다. 모든 아티팩트는 인프라 레이어(CLI 러너, DB, 큐, 파일 시스템)이며 데이터 흐름은 테스트를 통해 end-to-end 검증됨.

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `MessageBus.consume()` | `list[AgentMessage]` | SQLite `messages` 테이블 (`SELECT * WHERE status='pending'`) | Yes | FLOWING |
| `WorkspaceManager.write_artifact()` | 파일 내용 | 호출자가 전달하는 `content` 파라미터 → `os.rename` | Yes | FLOWING |
| `OllamaRunner.generate()` | Ollama `response` 필드 | `POST /api/generate` HTTP 응답 | Yes | FLOWING |
| `EventBus.publish()` | `LogEvent` | 호출자 생성 후 asyncio.Queue 팬아웃 | Yes | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SQLite WAL 모드 활성화 (file-based) | `get_connection(tmp_path)` → `PRAGMA journal_mode` | `wal` | PASS |
| SQLite busy_timeout 설정 | `get_connection(':memory:')` → `PRAGMA busy_timeout` | `5000` | PASS |
| FastAPI 라우트 등록 | `from main import app; [r.path for r in app.routes]` | `['/health', '/ws/logs']` 포함 | PASS |
| JSON 2-pass 파싱 (pass 1) | `parse_json('{"task": "design"}')` | `{'task': 'design'}` | PASS |
| JSON 2-pass 파싱 (pass 2b - 전후 텍스트) | `parse_json('Hello {"status": "done"} end')` | `{'status': 'done'}` | PASS |
| JSON 2-pass 파싱 (pass 2a - 코드 펜스) | 마크다운 펜스 입력 | `{'key': 'value'}` | PASS |
| JSON 2-pass 파싱 (pass 2c - 후행 쉼표) | `parse_json('{"a": 1,}')` | `{'a': 1}` | PASS |
| JSON unrecoverable → None | `parse_json('completely invalid')` | `None` | PASS |
| WorkspaceManager atomic write | `write_artifact('main.py', ...)` | 파일 생성, tmp 파일 없음 | PASS |
| WorkspaceManager 경로 순회 차단 | `safe_path('../etc/passwd')` | `ValueError` 발생 | PASS |
| WorkspaceManager 다중 형식 | `.md`, `.json`, `.css`, `.yaml` 저장 | 모두 성공 | PASS |
| EventBus pub→sub 전달 | `publish()` 후 `q.get_nowait()` | 이벤트 수신 확인 | PASS |
| EventBus unsubscribe 차단 | `unsubscribe()` 후 `publish()` | `q.empty() == True` | PASS |
| 전체 테스트 스위트 | `uv run pytest --tb=short -q` | **35 passed**, 0 failed | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| INFR-01 | 01-02-PLAN | SQLite(WAL 모드) 기반 메시지 큐로 에이전트 간 태스크 전달 및 상태 공유 | SATISFIED | `MessageBus` publish/consume/ack, WAL+busy_timeout 설정, 5개 테스트 PASSED |
| INFR-02 | 01-04-PLAN | Claude CLI는 subprocess로 실행되며, 토큰 격리(최소 컨텍스트 주입) 적용 | SATISFIED | `run_claude_isolated()`, `--bare` 플래그, 격리 디렉토리 CWD, 5개 테스트 PASSED |
| INFR-03 | 01-05-PLAN | Gemma4는 Ollama 로컬 인스턴스에서 실행되며, 단일 요청 큐로 순차 처리 | SATISFIED | `OllamaRunner` asyncio.Queue 단일 워커, 4개 테스트 PASSED |
| INFR-04 | 01-06-PLAN | 모든 에이전트 이벤트를 수집하는 로그 버스 존재, 대시보드에 실시간 전달 | SATISFIED | `EventBus` pub/sub, FastAPI `/ws/logs` WebSocket, 6개 테스트 PASSED |
| INFR-05 | 01-03-PLAN | Gemma4의 구조화 출력(JSON)에 대한 파싱+복구 전략 적용 | SATISFIED | `parse_json()` 2-pass 전략(strict→repair), 8개 테스트 PASSED |
| ARTF-01 | 01-03-PLAN | 모든 에이전트 산출물은 프로젝트 폴더에 실제 파일로 즉시 저장 | SATISFIED | `WorkspaceManager.write_artifact()` atomic write, `workspace/<task-id>/` 격리, 7개 테스트 PASSED |
| ARTF-02 | 01-03-PLAN | 산출물은 코드, 디자인 명세, 문서 등 다양한 형식 지원 | SATISFIED | `SUPPORTED_EXTENSIONS` 레지스트리 (code/doc/design/data), `.py/.ts/.md/.json/.yaml` 등 다중 형식 저장 확인 |

**Coverage:** 7/7 Phase 1 requirements SATISFIED. ORPHANED requirements: 없음.

---

### Anti-Patterns Found

전체 구현 파일(`server/**/*.py`)에 대해 다음 패턴을 검사함:

- `TODO / FIXME / XXX / HACK / PLACEHOLDER` — **없음**
- `NotImplementedError` / `raise NotImplementedError` — **없음** (모든 stub이 실제 구현으로 교체됨)
- `return null / return {} / return []` — **없음**
- Props/인자 하드코딩 빈 값 — **없음**

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `server/bus/message_bus.py` | 56 | `datetime.utcnow()` deprecated (Python 3.12 경고) | INFO | 기능 동작에 영향 없음. `datetime.now(UTC)` 로 마이그레이션 권장 (non-blocking) |

---

### Human Verification Required

#### 1. Ollama 실제 연결 테스트

**Test:** Ollama 서비스가 실행 중인 환경에서 `OllamaRunner().start()` 후 `generate("테스트")` 호출
**Expected:** gemma4:26b 모델에서 실제 응답 반환, HTTP 타임아웃(120초) 내 완료
**Why human:** 실제 Ollama 서비스 및 gemma4:26b 모델 설치 환경이 필요. 자동화 검사에서는 httpx mock 사용.

#### 2. Claude CLI 실제 subprocess 실행

**Test:** Claude CLI가 설치된 환경에서 `run_claude_isolated("Hello")` 호출
**Expected:** JSON-lines 스트림에서 텍스트 응답 추출 성공, `--bare` 플래그로 CLAUDE.md 미주입 확인
**Why human:** 실제 Claude CLI 설치 및 인증 환경이 필요. 자동화 검사에서는 AsyncMock 사용.

#### 3. FastAPI WebSocket 실시간 브로드캐스트 E2E

**Test:** `uvicorn server.main:app` 실행 후 WebSocket 클라이언트로 `/ws/logs` 연결, 이후 서버에서 `event_bus.publish(LogEvent(...))` 호출
**Expected:** 연결된 WebSocket 클라이언트에 JSON 이벤트가 즉시 수신됨
**Why human:** 실제 서버 프로세스 기동 및 WebSocket 클라이언트(wscat 등) 필요. lifespan startup에서 OllamaRunner.start() 호출로 Ollama 연결 불필요 시 대체 가능.

---

### Gaps Summary

갭 없음. 모든 5개 Success Criteria, 7개 Requirements, 14개 아티팩트가 검증됨.

전체 35개 테스트 PASSED. NotImplementedError/stub 코드 없음. 모든 key link 연결 확인.

주목할 사항:
- `datetime.utcnow()` 사용이 Python 3.12에서 deprecated 경고를 발생시키나 기능 동작에는 영향 없음. `event_bus.py`는 이미 `datetime.now(UTC)`로 수정됨. `message_bus.py`의 `ack()` 메서드만 미수정 상태 (info-level).
- 실제 Ollama/Claude CLI 실행은 로컬 서비스 의존으로 human verification 필요.

---

_Verified: 2026-04-03_
_Verifier: Claude (gsd-verifier)_
