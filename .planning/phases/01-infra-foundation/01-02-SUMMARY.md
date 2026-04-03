---
phase: 01-infra-foundation
plan: 02
subsystem: database
tags: [sqlite, wal, message-bus, pydantic, pytest]

requires:
  - phase: 01-infra-foundation plan 01
    provides: AgentMessage Pydantic 스키마, conftest.py 테스트 픽스처, server/ uv 서브프로젝트

provides:
  - SQLite WAL 모드 연결 관리자 (get_connection, init_schema)
  - MessageBus 클래스 (publish/consume/ack)
  - 5개 통과 테스트로 검증된 INFR-01 구현

affects:
  - 오케스트레이션 서버 (Phase 2): MessageBus를 에이전트 태스크 전달에 직접 사용
  - 모든 에이전트 러너: publish/consume/ack 인터페이스로 통신

tech-stack:
  added: []
  patterns:
    - "SQLite WAL 모드: journal_mode=WAL + synchronous=NORMAL + busy_timeout=5000"
    - "절대 임포트 패턴: server/ 내 패키지 간 from db.client import (상대 임포트 금지)"
    - "MessageBus 픽스처: tmp_path 기반 격리 DB로 테스트 간 상태 오염 방지"

key-files:
  created:
    - server/db/client.py
    - server/tests/test_message_bus.py
  modified:
    - server/bus/message_bus.py

key-decisions:
  - "절대 임포트 사용: server/는 __init__.py 없는 네임스페이스라 상대 임포트(..db.client)가 최상위 패키지 외부 참조 에러를 유발함. from db.client import로 통일"
  - "WAL 모드는 파일 기반 DB 전용: :memory: DB는 WAL 미지원이므로 테스트 픽스처에서 tmp_path 기반 파일 DB 사용"

patterns-established:
  - "MessageBus 테스트: tmp_path fixture로 격리 DB 파일 생성, yield 후 close()"
  - "payload JSON 직렬화: json.dumps/loads로 Any 타입 페이로드 저장 및 복원"

requirements-completed:
  - INFR-01

duration: 2min
completed: 2026-04-03
---

# Phase 01 Plan 02: SQLite WAL 메시지 버스 Summary

**SQLite WAL 모드 기반 MessageBus(publish/consume/ack)와 get_connection/init_schema 구현 — 5개 pytest 모두 PASSED**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-03T05:18:39Z
- **Completed:** 2026-04-03T05:20:25Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- SQLite WAL 연결 관리자 구현: PRAGMA journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON, busy_timeout=5000, row_factory=sqlite3.Row
- MessageBus 클래스 완성: publish(AgentMessage→DB), consume(to_agent, limit), ack(message_id→done)
- test_message_bus.py 5개 테스트 전부 PASSED (왕복·ACK·수신자 필터·limit·atomic write)

## Task Commits

각 태스크를 원자적으로 커밋:

1. **Task 1: SQLite WAL 연결 관리자 구현** - `252e854` (feat)
2. **Task 2: MessageBus publish/consume/ack 구현 및 테스트 완성** - `b1d1aca` (feat)

**플랜 메타데이터:** (docs 커밋 — 아래 참조)

## Files Created/Modified

- `server/db/client.py` - SQLite WAL 연결 반환 및 messages 테이블 초기화
- `server/bus/message_bus.py` - MessageBus 클래스 (publish/consume/ack/_row_to_message/close)
- `server/tests/test_message_bus.py` - INFR-01 검증 5개 테스트 (xfail 제거, 실제 검증 로직)

## Decisions Made

- 절대 임포트 사용: `server/`는 `__init__.py`가 없어 네임스페이스 패키지이므로, `from ..db.client`와 같은 상대 임포트는 최상위 패키지 외부 참조 에러(ImportError: attempted relative import beyond top-level package)를 발생시킴. `from db.client import`로 통일
- WAL 모드는 파일 기반 DB 전용: SQLite `:memory:` DB는 WAL을 지원하지 않으므로, 테스트 픽스처를 `tmp_path` 기반 파일 DB로 구성

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 상대 임포트를 절대 임포트로 수정**
- **Found during:** Task 2 (MessageBus 구현 후 pytest 실행)
- **Issue:** `from ..db.client import get_connection, init_schema`가 `ImportError: attempted relative import beyond top-level package` 발생 — `server/`에 `__init__.py`가 없어 `bus`가 최상위 패키지로 인식됨
- **Fix:** `from db.client import get_connection, init_schema`로 절대 임포트 변경
- **Files modified:** `server/bus/message_bus.py`
- **Verification:** `uv run pytest tests/test_message_bus.py -v` 5개 모두 PASSED
- **Committed in:** `b1d1aca` (Task 2 커밋에 포함)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 필수 수정. 패키지 구조 이해 기반의 임포트 경로 수정으로 범위 이탈 없음.

## Issues Encountered

- 계획의 검증 명령 `get_connection(':memory:')` → `PRAGMA journal_mode` = `wal` 기대는 SQLite 제약상 달성 불가 (인메모리 DB는 WAL 미지원). 파일 기반 DB로 동등한 검증 수행하고 테스트는 `tmp_path` 픽스처로 구성.

## Next Phase Readiness

- MessageBus가 완전히 동작하며 Phase 2 오케스트레이션 서버에서 즉시 import 가능
- `from bus.message_bus import MessageBus` + `MessageBus(db_path='data/bus.db')` 패턴으로 사용
- 절대 임포트 패턴이 확립되어 후속 패키지도 동일 방식 적용 필요

---
*Phase: 01-infra-foundation*
*Completed: 2026-04-03*
