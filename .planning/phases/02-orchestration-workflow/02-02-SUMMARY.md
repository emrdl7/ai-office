---
phase: 02-orchestration-workflow
plan: 02
subsystem: orchestration
tags: [dag, task-graph, message-router, pydantic, sqlite, asyncio, broadcast]

# Dependency graph
requires:
  - phase: 02-orchestration-workflow
    plan: 01
    provides: TaskRequestPayload, TaskResultPayload, StatusUpdatePayload, xfail stub 테스트 파일들
  - phase: 01-infra-foundation
    provides: MessageBus (SQLite WAL), AgentMessage 스키마, EventBus, LogEvent
provides:
  - TaskGraph 클래스 — 인메모리 DAG + 상태 관리 (server/orchestration/task_graph.py)
  - TaskNode 데이터클래스 — 태스크 노드 (task_id, description, requirements, assigned_to, depends_on, status)
  - TaskStatus enum — PENDING/PROCESSING/DONE/FAILED/BLOCKED
  - MessageRouter 클래스 — 메시지 라우팅 + 기획자 broadcast 복사 (server/orchestration/router.py)
affects:
  - 02-03 (OrchestrationLoop — TaskGraph + MessageRouter import하여 사용)
  - 02-04 (RevisionLoop — TaskGraph 상태 조회 필요)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TaskGraph 인메모리 DAG: dict[str, TaskNode]로 O(1) 조회, ready_tasks()가 의존성 DAG를 매번 순회"
    - "MessageRouter async route(): bus.publish() 동기 + event_bus.publish() 비동기 혼용"
    - "Pydantic v2 model_copy(update=...) 패턴 — field name 기준(alias 아닌 Python 이름) 키 사용"
    - "broadcast 복사 metadata: is_broadcast_copy: True로 기획자가 복사본과 원본을 구분 가능"

key-files:
  created:
    - server/orchestration/__init__.py
    - server/orchestration/task_graph.py
    - server/orchestration/router.py
  modified:
    - server/tests/test_task_graph.py
    - server/tests/test_message_routing.py
    - server/tests/test_planner_tracking.py
    - server/tests/test_free_request.py

key-decisions:
  - "TaskNode.requirements 필드 보존 — TaskRequestPayload에서 그대로 복사하여 QA 독립 참조(D-08) DAG 레벨에서도 유지"
  - "ready_tasks()는 PENDING 노드만 반환 — PROCESSING/FAILED/DONE 상태는 재실행 대상 아님"
  - "route()에서 to_agent == 'broadcast'도 복사 생략 — 이미 broadcast이면 기획자 중복 없음"

patterns-established:
  - "TaskGraph 사용 패턴: graph.add_task(payload) → graph.ready_tasks() 루프 → graph.update_status()"
  - "MessageRouter 사용 패턴: await router.route(msg) — 원본 발행 + 기획자 복사 + 이벤트 버스 로그 자동 처리"
  - "from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus — 후속 플랜 import 패턴"
  - "from orchestration.router import MessageRouter — 후속 플랜 import 패턴"

requirements-completed: [ORCH-05, WKFL-01, WKFL-03, WKFL-04]

# Metrics
duration: 2min
completed: 2026-04-03
---

# Phase 2 Plan 02: TaskGraph + MessageRouter Summary

**인메모리 DAG TaskGraph(add_task/ready_tasks/update_status/all_done)와 기획자 broadcast 복사가 자동 발행되는 MessageRouter를 구현하여 오케스트레이션 루프(Plan 03)의 핵심 의존성 완성**

## Performance

- **Duration:** 2분
- **Started:** 2026-04-03T08:07:11Z
- **Completed:** 2026-04-03T08:09:00Z
- **Tasks:** 2
- **Files modified:** 7 (3 신규 생성 + 4 수정)

## Accomplishments

- `server/orchestration/task_graph.py` — TaskStatus(5개 상태), TaskNode(requirements 포함), TaskGraph(add_task/get_task/update_status/ready_tasks/all_done/to_state_dict) 구현
- `server/orchestration/router.py` — MessageRouter async route(): 원본 발행 + 기획자 자동 broadcast 복사(is_broadcast_copy 메타데이터) + EventBus 로그 발행
- 7개 xfail stub 테스트를 실제 구현 테스트로 전환, 전체 suite 46 passed, 9 xfailed (regression 없음)

## Task Commits

각 태스크는 원자적으로 커밋됨:

1. **Task 1: TaskGraph — 인메모리 DAG 태스크 상태 관리자** - `a178241` (feat)
2. **Task 2: MessageRouter — 메시지 라우팅 + 기획자 broadcast 복사** - `aaa7299` (feat)

## Files Created/Modified

- `server/orchestration/__init__.py` — 오케스트레이션 모듈 패키지 진입점
- `server/orchestration/task_graph.py` — TaskStatus enum, TaskNode 데이터클래스, TaskGraph 클래스
- `server/orchestration/router.py` — MessageRouter 클래스 (async route 메서드)
- `server/tests/test_task_graph.py` — xfail stub → 4개 실제 테스트 (PASSED)
- `server/tests/test_message_routing.py` — xfail stub → 3개 payload 스키마 테스트 (PASSED)
- `server/tests/test_planner_tracking.py` — xfail stub → 2개 broadcast 복사 테스트 (PASSED)
- `server/tests/test_free_request.py` — xfail stub → 2개 자유 요청 테스트 (PASSED)

## Decisions Made

- `TaskNode.requirements` 필드를 TaskRequestPayload에서 그대로 복사 — QA 독립 참조(D-08)를 DAG 레벨에서도 보장
- `ready_tasks()`는 PENDING 노드만 반환 — 이미 PROCESSING/DONE/FAILED 상태 노드 재실행 방지
- `route()`에서 `to_agent == 'broadcast'`도 복사 생략 처리 — 이미 broadcast인 메시지에 중복 복사 방지

## Deviations from Plan

없음 — 플랜이 정확히 명시한 대로 실행됨

## Issues Encountered

- 플랜이 `/Users/johyeonchang/ai-office/server`에서 테스트를 실행하도록 명시했으나, 실행 환경이 worktree(`.claude/worktrees/agent-ad2e7ccc/server`)이므로 해당 경로에서 실행. 동일한 코드베이스이므로 결과 동일함.

## User Setup Required

없음 — 외부 서비스 설정 불필요

## Next Phase Readiness

- `from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus` import 즉시 사용 가능 (02-03 OrchestrationLoop 준비 완료)
- `from orchestration.router import MessageRouter` import 즉시 사용 가능
- 전체 테스트 suite: 46 passed, 9 xfailed (stub 포함) — Phase 1 regression 없음
- 남은 xfail stub: test_orchestration.py(2), test_agents.py(2), test_qa_gate.py(2), test_revision_loop.py(3) — 후속 플랜에서 전환 예정

## Self-Check: PASSED

- FOUND: server/orchestration/__init__.py
- FOUND: server/orchestration/task_graph.py
- FOUND: server/orchestration/router.py
- FOUND: commit a178241 (Task 1)
- FOUND: commit aaa7299 (Task 2)
- pytest (worktree): 46 passed, 9 xfailed (regression 없음)

---
*Phase: 02-orchestration-workflow*
*Completed: 2026-04-03*
