---
phase: 01-infra-foundation
plan: '06'
subsystem: infra
tags: [asyncio, websocket, fastapi, event-bus, pub-sub, real-time]

# 의존성 그래프
requires:
  - phase: 01-02
    provides: FastAPI 앱 기반 (main.py 구조)
  - phase: 01-04
    provides: OllamaRunner 싱글턴 (lifespan 연동 대상)
  - phase: 01-05
    provides: OllamaRunner.start()/stop() 메서드

provides:
  - asyncio.Queue 기반 EventBus (subscribe/publish/unsubscribe)
  - LogEvent 데이터클래스 (id/timestamp 자동 생성, to_dict())
  - FastAPI /ws/logs WebSocket 엔드포인트
  - event_bus 싱글턴 (server/log_bus/event_bus.py)

affects:
  - phase-04-dashboard (WebSocket ws://localhost:8000/ws/logs 소비자)

# 기술 추적
tech-stack:
  added: []
  patterns:
    - asyncio.Queue pub/sub 패턴 (subscribe → consume → unsubscribe)
    - finally 블록 unsubscribe로 메모리 누수 방지 (Pitfall 4)
    - QueueFull 무시로 느린 구독자가 버스를 블록하지 않는 패턴
    - WebSocket 연결 생명주기와 이벤트 버스 구독 생명주기 동기화

key-files:
  created: []
  modified:
    - server/log_bus/event_bus.py
    - server/main.py
    - server/tests/test_log_bus.py

key-decisions:
  - 'asyncio.Queue 기반 in-process 이벤트 버스: 폴링 없이 즉시 WebSocket 팬아웃, SQLite 브릿지 불필요'
  - 'QueueFull 예외 무시: 느린 클라이언트 드롭으로 버스 블록 방지, 느린 구독자는 일부 이벤트 손실 허용'
  - 'datetime.utcnow() 대신 datetime.now(UTC) 사용: Python 3.12 deprecation 경고 해소'

patterns-established:
  - 'Event Bus Pattern: subscribe() → await q.get() 루프 → unsubscribe() in finally'
  - 'WebSocket Handler: accept() → subscribe() → send_json(asdict(event)) → unsubscribe() in finally'

requirements-completed: [INFR-04]

# 지표
duration: 12min
completed: '2026-04-03'
---

# Phase 01 Plan 06: EventBus + WebSocket 로그 스트림 Summary

**asyncio.Queue 기반 in-process EventBus와 FastAPI /ws/logs WebSocket 엔드포인트로 에이전트 이벤트를 폴링 없이 대시보드에 실시간 브로드캐스트하는 인프라 완성**

## Performance

- **Duration:** 12 min
- **Started:** 2026-04-03T05:25:00Z
- **Completed:** 2026-04-03T05:37:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- asyncio.Queue 기반 EventBus 구현: subscribe/unsubscribe/publish + subscriber_count 프로퍼티
- LogEvent 데이터클래스: id(uuid), timestamp(UTC ISO), agent_id, event_type, message, data 자동 생성
- FastAPI /ws/logs WebSocket 엔드포인트: 연결 시 구독, 이벤트 수신 시 JSON 전송, 연결 종료 시 finally에서 구독 해제
- test_log_bus.py 6개 테스트 모두 PASSED (35/35 전체 테스트 스위트 통과)

## Task Commits

1. **Task 1: EventBus subscribe/publish/unsubscribe 구현 (TDD)** - `bcf791e` (feat)
2. **Task 2: FastAPI /ws/logs WebSocket 엔드포인트 + lifespan 연동** - `6fc4b2e` (feat)

**Plan metadata:** (docs commit 예정)

## Files Created/Modified

- `server/log_bus/event_bus.py` - EventBus 클래스, LogEvent 데이터클래스, event_bus 싱글턴
- `server/main.py` - FastAPI 앱에 /ws/logs WebSocket 엔드포인트 + lifespan OllamaRunner 연동
- `server/tests/test_log_bus.py` - INFR-04 검증 테스트 6개 (xfail stub에서 실제 테스트로 교체)

## Decisions Made

- asyncio.Queue 기반 in-process 이벤트 버스 선택: 외부 브로커(Redis 등) 없이 FastAPI와 동일 프로세스에서 즉시 WebSocket 팬아웃 가능
- QueueFull 예외 무시 패턴: 느린 대시보드 클라이언트가 버스 전체를 블록하지 않도록 이벤트 손실 허용

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] datetime.utcnow() deprecation 경고 수정**
- **Found during:** Task 1 (EventBus 구현 후 테스트 실행)
- **Issue:** Python 3.12에서 `datetime.utcnow()`는 deprecated. 6개 테스트 모두 deprecation 경고 발생
- **Fix:** `from datetime import UTC, datetime` 임포트 후 `datetime.now(UTC).isoformat()` 으로 변경
- **Files modified:** server/log_bus/event_bus.py
- **Verification:** 6개 테스트 경고 없이 PASSED
- **Committed in:** bcf791e (Task 1 commit에 포함)

---

**Total deviations:** 1 auto-fixed (1 bug/deprecation)
**Impact on plan:** Python 3.12 호환성 개선. 동작에 영향 없음.

## Issues Encountered

None - 계획대로 실행됨.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- INFR-04 완료: Phase 4 대시보드가 ws://localhost:8000/ws/logs WebSocket에 연결하여 실시간 에이전트 로그 수신 가능
- 에이전트가 `from log_bus.event_bus import event_bus`로 싱글턴 임포트 후 `await event_bus.publish(LogEvent(...))` 호출로 이벤트 발행 가능
- Phase 1 인프라 파운데이션 전체 완료: DB, 메시지 버스, 워크스페이스, JSON 파서, Claude/Ollama 러너, 이벤트 버스

---
*Phase: 01-infra-foundation*
*Completed: 2026-04-03*

## Self-Check: PASSED

- FOUND: server/log_bus/event_bus.py
- FOUND: server/main.py
- FOUND: server/tests/test_log_bus.py
- FOUND: .planning/phases/01-infra-foundation/01-06-SUMMARY.md
- FOUND commit: bcf791e (Task 1)
- FOUND commit: 6fc4b2e (Task 2)
- FOUND commit: 9261b1e (docs metadata)
