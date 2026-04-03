---
phase: 01-infra-foundation
plan: 05
subsystem: infra
tags: [asyncio, queue, ollama, httpx, gemma4, single-worker]

# Dependency graph
requires:
  - phase: 01-01
    provides: server/ Python 프로젝트 구조 + pytest-asyncio 설정
  - phase: 01-03
    provides: parse_json() 함수 (json_parser.py)
provides:
  - OllamaRunner 클래스 — asyncio.Queue 단일 워커 Ollama 클라이언트
  - generate() / generate_json() API
  - OllamaRunnerError 예외 클래스
affects:
  - 02-agents
  - 03-api

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.Queue 단일 워커 패턴으로 동시 Ollama 요청 직렬화
    - httpx.AsyncClient + base_url 패턴으로 Ollama REST API 호출
    - Future + Queue 패턴으로 비동기 요청-응답 연결

key-files:
  created: []
  modified:
    - server/runners/ollama_runner.py
    - server/tests/test_ollama_runner.py

key-decisions:
  - "asyncio.Queue 단일 워커로 동시 Ollama 요청을 직렬화 — gemma4:26b 메모리 스래싱 방지"
  - "generate_json()을 OllamaRunner에 포함 — parse_json() 파이프라인 통합 제공"

patterns-established:
  - "OllamaRunner.start()/stop() 생명주기를 FastAPI lifespan에 연동"
  - "httpx mock으로 실제 Ollama 의존 없이 단위 테스트"

requirements-completed:
  - INFR-03

# Metrics
duration: 5min
completed: 2026-04-03
---

# Phase 01 Plan 05: OllamaRunner asyncio.Queue 단일 워커 Summary

**asyncio.Queue 기반 단일 워커 Ollama HTTP 클라이언트 구현 — format:json 파라미터로 gemma4:26b 구조화 출력 요청, 동시 요청을 직렬화하여 메모리 스래싱 방지**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-03T05:20:00Z
- **Completed:** 2026-04-03T05:25:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- asyncio.Queue + 단일 _worker coroutine으로 동시 Ollama 요청 직렬화 구현
- httpx.AsyncClient로 Ollama /api/generate에 format:json 파라미터 전달
- generate_json() 메서드로 parse_json() 2-pass 파싱 파이프라인 통합
- 4개 단위 테스트 모두 PASSED (httpx mock 활용, 실제 Ollama 의존 없음)

## Task Commits

각 태스크는 원자적으로 커밋됨:

1. **Task 1: OllamaRunner asyncio.Queue 단일 워커 구현** - `0ff195e` (feat)

**Plan 메타데이터:** (docs 커밋 예정)

_참고: TDD 태스크 — 테스트 파일(RED) 작성 후 구현(GREEN) 순서로 진행_

## Files Created/Modified

- `server/runners/ollama_runner.py` - OllamaRunner 클래스 전체 구현 (asyncio.Queue, _worker, _call_ollama, generate, generate_json)
- `server/tests/test_ollama_runner.py` - INFR-03 검증 4개 테스트 (순차 처리, format:json, generate_json 파싱)

## Decisions Made

- asyncio.Queue 단일 워커 패턴 선택 — 여러 에이전트가 동시에 Ollama를 호출할 때 메모리 스래싱 방지 목적
- generate_json()을 OllamaRunner에 포함 — 호출자마다 parse_json을 직접 호출하는 반복 코드 방지

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. (실제 Ollama 호출은 httpx mock으로 대체하여 테스트)

## Next Phase Readiness

- OllamaRunner가 완성되어 에이전트 구현(02-agents)에서 즉시 사용 가능
- FastAPI lifespan 연동 패턴(start/stop)이 정의됨
- 실제 Ollama(localhost:11434) 연결은 런타임 환경에서 gemma4:26b 모델 준비 필요

---
*Phase: 01-infra-foundation*
*Completed: 2026-04-03*
