---
phase: 03-agent-memory
plan: '02'
subsystem: orchestration
tags: [agent-memory, system-prompt, experience-injection, tdd, pytest]

# Dependency graph
requires:
  - phase: 03-01
    provides: AgentMemory, MemoryRecord 클래스 (server/memory/agent_memory.py)
  - phase: 02-orchestration-workflow
    provides: OrchestrationLoop 상태 머신 (server/orchestration/loop.py)
provides:
  - OrchestrationLoop에 AgentMemory 완전 통합 — 경험 주입 + 자동 기록
  - _run_agent()에서 이전 경험을 시스템 프롬프트에 주입 (AMEM-02)
  - QA 불합격 시 즉시 실패 경험 기록 (AMEM-03)
  - Claude 최종검증 FAIL 시 완료 노드 에이전트에 보완 지시 기록 (AMEM-03)
  - 작업 성공 시 성공 경험 기록 (AMEM-01)
  - 통합 테스트 5개 GREEN
affects:
  - 04-dashboard (OrchestrationLoop 의존 시)
  - future phases using AgentMemory

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AgentMemory를 OrchestrationLoop에 memory_root 주입으로 격리 — 테스트 시 tmp_path 사용"
    - "TDD RED-GREEN: 실패 테스트 먼저 작성 후 최소 구현으로 통과"
    - "patch('orchestration.loop.AgentMemory') — 직접 임포트 네임스페이스에서 패치"

key-files:
  created: []
  modified:
    - server/orchestration/loop.py
    - server/tests/test_orchestration.py

key-decisions:
  - "AgentMemory를 memory_root 주입으로 테스트 격리 — tmp_path로 파일 시스템 격리"
  - "_run_agent() 직접 테스트 시 loop._task_graph = TaskGraph() 초기화 필요 — run() 없이 메서드 단독 호출 패턴"
  - "patch 대상: 'orchestration.loop.AgentMemory' — 직접 임포트된 네임스페이스에서 패치해야 mock 동작"

patterns-established:
  - "OrchestrationLoop 직접 메서드 테스트: _task_graph를 수동 초기화하고 TaskGraph.add_task()로 노드 등록"
  - "AgentMemory 통합점 3개: _run_agent(로드+성공기록), _run_qa_gate(실패기록), _claude_final_verify(보완기록)"

requirements-completed:
  - AMEM-02
  - AMEM-03

# Metrics
duration: 3min
completed: 2026-04-03
---

# Phase 03 Plan 02: OrchestrationLoop + AgentMemory 통합 Summary

**AgentMemory를 OrchestrationLoop 세 지점(_run_agent/QA/Claude검증)에 통합하여 에이전트 경험 자동 주입·기록 완성**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-03T08:51:49Z
- **Completed:** 2026-04-03T08:54:51Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- _run_agent() 실행 전 AgentMemory.load_relevant()로 이전 경험 조회, 시스템 프롬프트에 "## 이전 경험" 섹션 append
- _run_qa_gate() QA 불합격 시 즉시 AgentMemory.record(success=False, tags=['qa_fail']) 호출
- _run_agent() 성공 시 AgentMemory.record(success=True, tags=['success']) 호출 (AMEM-01)
- _claude_final_verify() FAIL 시 DONE 상태 노드 각 에이전트에 record(tags=['claude_revision']) 호출
- OrchestrationLoop.__init__에 memory_root 파라미터 추가 (테스트 격리 가능)
- 5개 테스트 모두 GREEN (기존 2개 + 신규 3개)

## Task Commits

각 태스크를 원자적으로 커밋:

1. **Task 1 + Task 2: _run_agent() 경험 주입 + QA/Claude 실패 기록 통합** - `48ae6ab` (feat)

**Plan metadata:** (작성 중)

## Files Created/Modified

- `server/orchestration/loop.py` — AgentMemory import 추가, memory_root 파라미터, 세 지점 통합
- `server/tests/test_orchestration.py` — loop_setup fixture에 memory_root 추가, 신규 테스트 3개 추가

## Decisions Made

- AgentMemory memory_root를 OrchestrationLoop 생성자에 주입받아 테스트 격리 보장
- _run_agent() 단독 테스트 시 loop._task_graph를 수동 초기화 필요 (run() 없이 직접 호출)
- patch 대상을 'orchestration.loop.AgentMemory'로 설정 — 직접 임포트 네임스페이스 패치 원칙

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _run_agent() 직접 호출 시 _task_graph = None 오류**
- **Found during:** Task 1 (GREEN 단계 테스트 실행)
- **Issue:** 테스트에서 _run_agent()를 loop.run() 없이 직접 호출하면 self._task_graph가 None이어서 AttributeError 발생
- **Fix:** 테스트 코드에서 loop._task_graph = TaskGraph()를 수동 초기화하고 add_task()로 노드 등록
- **Files modified:** server/tests/test_orchestration.py
- **Verification:** 5개 테스트 모두 PASS
- **Committed in:** 48ae6ab (Task 1+2 통합 커밋)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** 테스트 격리 패턴 개선, 기능 동작에는 영향 없음.

## Issues Encountered

- worktree 경로와 원본 server/ 경로 혼동으로 pytest 실행 경로 확인 필요 — 항상 worktree 내 server/ 디렉토리에서 실행

## Next Phase Readiness

- AgentMemory가 OrchestrationLoop에 완전 통합됨 — Phase 3 메모리 기능 완료
- 실제 에이전트 실행 시 경험이 자동으로 축적되고 다음 실행에 반영됨
- Phase 4(Dashboard)가 진행될 경우 OrchestrationLoop 상태는 이 구현 위에 구축 가능

---
*Phase: 03-agent-memory*
*Completed: 2026-04-03*
