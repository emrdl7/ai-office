---
phase: 02-orchestration-workflow
plan: 01
subsystem: testing
tags: [pydantic, pytest, agents, orchestration, xfail]

# Dependency graph
requires:
  - phase: 01-infra-foundation
    provides: AgentMessage 스키마, MessageBus, xfail 테스트 패턴
provides:
  - TaskRequestPayload, TaskResultPayload, StatusUpdatePayload Pydantic 모델 (server/bus/payloads.py)
  - 4개 에이전트 시스템 프롬프트 파일 (agents/*.md)
  - Wave 0 테스트 stub 8개 (server/tests/test_*.py)
affects:
  - 02-02 (router 구현 — TaskRequestPayload import)
  - 02-03 (task graph 구현 — xfail test_task_graph.py)
  - 02-04 (revision loop — xfail test_revision_loop.py)
  - OllamaRunner system 파라미터 주입 (agents/*.md)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "xfail(strict=False) Wave 0 stub 패턴 — Phase 1에서 확립, Phase 2에서 계속 사용"
    - "Pydantic BaseModel 상속 payload 스키마 — 에이전트 간 타입 계약"
    - "에이전트 시스템 프롬프트 .md 파일 기반 관리 (D-01 결정)"

key-files:
  created:
    - server/bus/payloads.py
    - agents/planner.md
    - agents/designer.md
    - agents/developer.md
    - agents/qa.md
    - server/tests/test_orchestration.py
    - server/tests/test_agents.py
    - server/tests/test_message_routing.py
    - server/tests/test_revision_loop.py
    - server/tests/test_task_graph.py
    - server/tests/test_qa_gate.py
    - server/tests/test_free_request.py
    - server/tests/test_planner_tracking.py
  modified: []

key-decisions:
  - "에이전트 시스템 프롬프트를 agents/*.md 파일로 관리 — D-01 결정, OllamaRunner system 파라미터로 주입"
  - "TaskRequestPayload.requirements 필드에 원본 요구사항 전문 포함 — QA 독립 참조(D-08) 구조적 보장"
  - "TaskResultPayload.failure_reason Optional[str] — QA 불합격 시 구체적 사유 전달(D-09)"

patterns-established:
  - "payload 스키마 패턴: from bus.payloads import TaskRequestPayload — 후속 플랜에서 동일 import 사용"
  - "QA 입력 형식: [원본 요구사항]{requirements}[작업 결과물 경로]{artifact_paths} — 확증편향 방지 구조"
  - "xfail stub 파일 구조: 파일 상단 요구사항 ID 주석, 한국어 docstring, 2 spaces 들여쓰기"

requirements-completed: [ORCH-02, ORCH-03]

# Metrics
duration: 8min
completed: 2026-04-03
---

# Phase 2 Plan 01: Wave 0 인터페이스 계약 Summary

**TaskRequestPayload/TaskResultPayload/StatusUpdatePayload Pydantic 스키마 + 4개 에이전트 시스템 프롬프트 파일 + 19개 xfail 테스트 stub으로 Phase 2 구현 계약 완성**

## Performance

- **Duration:** 8분
- **Started:** 2026-04-03T08:00:00Z
- **Completed:** 2026-04-03T08:04:47Z
- **Tasks:** 3
- **Files modified:** 13 (신규 생성)

## Accomplishments

- `server/bus/payloads.py` — TaskRequestPayload(requirements 독립 참조용), TaskResultPayload(failure_reason 선택적), StatusUpdatePayload 3개 Pydantic 모델 정의
- `agents/` 디렉토리에 planner/designer/developer/qa 시스템 프롬프트 4개 파일 생성 — 각각 역할정의/JSON출력/협업규칙/금지사항 4섹션 완비
- 19개 xfail stub 테스트 파일 8개 생성 — 전체 pytest 35 passed, 19 xfailed (regression 없음)

## Task Commits

각 태스크는 원자적으로 커밋됨:

1. **Task 1: Payload 스키마 Pydantic 모델 정의** - `f7a0a1e` (feat)
2. **Task 2: 에이전트 시스템 프롬프트 파일 4개 작성** - `d649636` (feat)
3. **Task 3: Wave 0 테스트 stub 8개 생성** - `c037c57` (test)

## Files Created/Modified

- `server/bus/payloads.py` — TaskRequestPayload, TaskResultPayload, StatusUpdatePayload Pydantic 모델
- `agents/planner.md` — 기획자+PM 겸임 시스템 프롬프트 (역할정의, JSON출력, 협업규칙, 금지사항)
- `agents/designer.md` — 디자이너 시스템 프롬프트 (UI/UX 명세 생성, TaskResultPayload 출력)
- `agents/developer.md` — 개발자 시스템 프롬프트 (코드 파일 생성, artifact_paths 필수, QA 검수 의무)
- `agents/qa.md` — QA 시스템 프롬프트 (원본 요구사항 독립 참조, 확증편향 방지, failure_reason 구체적 기술)
- `server/tests/test_orchestration.py` — ORCH-01 stub 2개
- `server/tests/test_agents.py` — ORCH-02 stub 2개
- `server/tests/test_message_routing.py` — ORCH-03 stub 3개
- `server/tests/test_revision_loop.py` — ORCH-04 stub 3개
- `server/tests/test_task_graph.py` — WKFL-01 stub 3개
- `server/tests/test_qa_gate.py` — WKFL-02 stub 2개
- `server/tests/test_free_request.py` — WKFL-03 stub 2개
- `server/tests/test_planner_tracking.py` — WKFL-04 stub 2개

## Decisions Made

- `agents/*.md` 파일 기반 시스템 프롬프트 관리 선택 (D-01 결정) — 버전 관리 용이, OllamaRunner system 파라미터로 파일 내용을 읽어 주입하는 패턴 확립
- `TaskRequestPayload.requirements` 필드에 원본 요구사항 전문 포함 — QA가 독립적으로 참조할 수 있는 구조적 보장 (D-08)
- `TaskResultPayload.failure_reason` Optional[str] 타입 — QA 불합격 시 구체적 사유 전달 구조 확립 (D-09)

## Deviations from Plan

없음 — 플랜이 정확히 명시한 대로 실행됨

## Issues Encountered

없음

## User Setup Required

없음 — 외부 서비스 설정 불필요

## Next Phase Readiness

- `from bus.payloads import TaskRequestPayload` import 즉시 사용 가능 (02-02 router 구현 준비 완료)
- agents/*.md 파일 존재 — OllamaRunner system 파라미터 주입 가능
- 19개 xfail stub — 후속 플랜(02-02~04) 구현 시 실제 테스트로 전환 예정
- 기존 Phase 1 테스트 suite 35개 모두 통과 (regression 없음)

## Self-Check: PASSED

- FOUND: server/bus/payloads.py
- FOUND: agents/planner.md, designer.md, developer.md, qa.md
- FOUND: 8개 테스트 stub 파일 모두 존재
- FOUND: commit f7a0a1e (Task 1), d649636 (Task 2), c037c57 (Task 3)
- pytest: 35 passed, 19 xfailed (regression 없음)

---
*Phase: 02-orchestration-workflow*
*Completed: 2026-04-03*
