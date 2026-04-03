---
phase: 03-agent-memory
plan: '01'
subsystem: agent-memory
tags: [python, dataclass, json, atomic-write, lazy-compaction, tdd]

requires:
  - phase: 01-infra-foundation
    provides: atomic write 패턴 (WorkspaceManager.write_artifact), JSON 파서
  - phase: 02-orchestration-workflow
    provides: OrchestrationLoop QA/Claude 검증 결과 — 경험 저장 트리거

provides:
  - AgentMemory 클래스: record()/load_relevant()/_maybe_compact() 단일 진입점
  - MemoryRecord 데이터클래스: 경험 레코드 스키마
  - data/memory/{agent}_memory.json atomic write 저장 구조
  - lazy compaction: MAX_DETAIL_COUNT=20 초과 시 오래된 항목 규칙 기반 요약

affects:
  - 03-agent-memory (향후 plan: OrchestrationLoop 통합, 경험 프롬프트 주입)

tech-stack:
  added: []
  patterns:
    - "AgentMemory 생성자에 memory_root 파라미터 주입으로 테스트 격리"
    - "tmp+os.rename atomic write 패턴 (WorkspaceManager 패턴 재적용)"
    - "lazy compaction: load_relevant() 호출 시 _maybe_compact() 자동 실행"
    - "규칙 기반 요약: 성공/실패 건수 + 상위 3개 태그"

key-files:
  created:
    - server/memory/__init__.py
    - server/memory/agent_memory.py
    - server/tests/test_agent_memory.py
  modified: []

key-decisions:
  - "memory_root 파라미터로 AgentMemory 테스트 격리 — WorkspaceManager의 workspace_root 패턴 답습"
  - "MAX_DETAIL_COUNT=20, keep_count=10 (절반 유지) — D-07 재량 값"
  - "WorkspaceManager 재사용하지 않음 — task_id 기반 경로 로직이 에이전트 메모리 파일과 미적합"
  - "dataclass 선택 (TypedDict 대신) — asdict()로 직렬화, 타입 힌트와 기본값 관리 용이"
  - "규칙 기반 요약 — 외부 LLM 호출 없이 성공/실패 건수 + 주요 태그 집계"

patterns-established:
  - "AgentMemory: record() → _atomic_write(), load_relevant() → _maybe_compact() → _atomic_write()"
  - "TDD: test 파일 먼저 커밋(RED), 구현 후 PASS 확인(GREEN)"

requirements-completed:
  - AMEM-01
  - AMEM-02
  - AMEM-03

duration: 9min
completed: 2026-04-03
---

# Phase 3 Plan 01: Agent Memory 핵심 모듈 Summary

**에이전트별 JSON 파일 기반 경험 메모리 모듈(AgentMemory + MemoryRecord) — atomic write + lazy compaction으로 data/memory/{agent}_memory.json 저장 및 관리**

## Performance

- **Duration:** 9 min
- **Started:** 2026-04-03T08:40:44Z
- **Completed:** 2026-04-03T08:49:42Z
- **Tasks:** 2 (Task 1: 구현, Task 2: 테스트)
- **Files modified:** 3

## Accomplishments

- MemoryRecord 데이터클래스로 task_id/task_type/success/feedback/tags/timestamp 스키마 정의
- AgentMemory.record()가 tmp+os.rename atomic write로 경험 레코드를 에이전트별 JSON에 저장
- AgentMemory.load_relevant()가 task_type 필터 + timestamp 내림차순 정렬 + lazy compaction을 단일 호출로 처리
- 6개 단위 테스트 전부 PASS — tmp_path 격리로 실제 data/ 미오염

## Task Commits

각 TDD 단계를 원자적으로 커밋:

1. **Test RED: AgentMemory 단위 테스트** - `53548c0` (test)
2. **Implementation GREEN: AgentMemory + MemoryRecord** - `ec975ad` (feat)

## Files Created/Modified

- `server/memory/__init__.py` — memory 패키지 네임스페이스
- `server/memory/agent_memory.py` — AgentMemory 클래스 (record/load_relevant/_maybe_compact/_atomic_write/_load_raw), MemoryRecord 데이터클래스
- `server/tests/test_agent_memory.py` — 6개 단위 테스트 (파일 생성, 누적, 필터, 빈 파일, lazy compaction, atomic write 실패 복구)

## Decisions Made

- **WorkspaceManager 재사용하지 않음**: safe_path가 task_id 기반 디렉토리 격리 로직을 포함하고 있어 에이전트 메모리 단일 파일 패턴과 부적합. os.rename 패턴만 참조하여 AgentMemory에서 직접 구현.
- **dataclass 선택**: TypedDict 대신 dataclass를 선택하여 `asdict()`로 직렬화, 타입 안정성 확보.
- **MAX_DETAIL_COUNT=20**: D-07 재량값. keep_count=10(절반)으로 오래된 항목 압축.
- **규칙 기반 요약**: 외부 LLM 없이 성공/실패 건수 + Counter로 상위 3개 태그 집계.

## Deviations from Plan

없음 — 계획대로 정확히 실행됨.

## Issues Encountered

없음

## User Setup Required

없음 — 외부 서비스 설정 불필요.

## Next Phase Readiness

- AgentMemory가 단일 진입점으로 완성됨 — OrchestrationLoop에서 직접 import 가능
- `_run_qa_gate()`, `_claude_final_verify()`, `_dispatch_to_worker()`에 record()/load_relevant() 호출을 추가하면 경험 주입 완료
- data/memory/ 디렉토리는 AgentMemory가 자동 생성하므로 사전 설정 불필요

## Self-Check: PASSED

- FOUND: server/memory/__init__.py
- FOUND: server/memory/agent_memory.py
- FOUND: server/tests/test_agent_memory.py
- FOUND: commit 53548c0 (test RED)
- FOUND: commit ec975ad (feat GREEN)
- 6 tests PASSED

---
*Phase: 03-agent-memory*
*Completed: 2026-04-03*
