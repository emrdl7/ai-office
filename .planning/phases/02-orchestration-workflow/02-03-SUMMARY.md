---
phase: 02-orchestration-workflow
plan: 03
subsystem: orchestration
tags: [state-machine, workflow, orchestration, qa-gate, revision-loop]
dependency_graph:
  requires:
    - 02-02 (TaskGraph, MessageRouter)
    - 01-infra (OllamaRunner, run_claude_isolated, MessageBus, EventBus, WorkspaceManager)
  provides:
    - OrchestrationLoop (server/orchestration/loop.py)
    - WorkflowState enum
  affects:
    - server/runners/ollama_runner.py (system 파라미터 추가)
tech_stack:
  added: []
  patterns:
    - 상태 머신 패턴 (WorkflowState enum + OrchestrationLoop)
    - TDD (RED → GREEN 2-commit 사이클)
    - mock patch 경로: orchestration.loop.run_claude_isolated (직접 임포트된 함수 패치)
key_files:
  created:
    - server/orchestration/loop.py
    - server/agents/planner.md
    - server/agents/developer.md
    - server/agents/designer.md
    - server/agents/qa.md
  modified:
    - server/runners/ollama_runner.py (system 파라미터 추가)
    - server/tests/test_orchestration.py (stub → 실제 구현 테스트)
    - server/tests/test_revision_loop.py (stub → 실제 구현 테스트)
    - server/tests/test_qa_gate.py (stub → 실제 구현 테스트)
decisions:
  - "mock patch 대상을 orchestration.loop.run_claude_isolated로 변경 — 직접 임포트된 이름은 모듈 네임스페이스에서 패치해야 함"
  - "WorkspaceManager는 task_id 기반 인스턴스이므로 loop에서 task별 경로를 prefix로 사용"
  - "agents/ 디렉토리에 .md 파일로 시스템 프롬프트 관리 (D-01, D-03)"
metrics:
  duration: 4m
  completed_date: "2026-04-03T08:15:25Z"
  tasks_completed: 1
  files_changed: 9
---

# Phase 2 Plan 3: OrchestrationLoop 상태 머신 구현 Summary

## One-liner

WorkflowState enum 기반 OrchestrationLoop: IDLE→CLAUDE_ANALYZING→PLANNER_PLANNING→WORKER_EXECUTING→QA_REVIEWING→CLAUDE_FINAL_VERIFYING→COMPLETED/ESCALATED 전이, MAX_REVISION_ROUNDS=3 보완 루프 포함

## What Was Built

### server/orchestration/loop.py

`OrchestrationLoop` 클래스와 `WorkflowState` enum을 구현했다.

- **WorkflowState enum**: IDLE, CLAUDE_ANALYZING, PLANNER_PLANNING, WORKER_EXECUTING, QA_REVIEWING, CLAUDE_FINAL_VERIFYING, REVISION_LOOPING, COMPLETED, ESCALATED
- **MAX_REVISION_ROUNDS = 3**: 최대 보완 반복 횟수 상수 (D-11, D-12)
- **analyze_instruction()**: Claude CLI로 사용자 지시 분석 → 반드시 planner에게만 전달 (D-04)
- **_run_qa_gate()**: 원본 요구사항(node.requirements) 포함 프롬프트로 QA 검수 (D-08, Pattern 4)
- **_claude_final_verify()**: PASS/FAIL 응답 파싱 → revision_count 증가 → ESCALATED 전환

### server/runners/ollama_runner.py (수정)

`generate()`, `generate_json()`, `_call_ollama()`, `_worker()`에 `system: str = ''` 파라미터 추가.
asyncio.Queue 튜플을 `(prompt, future)` → `(prompt, system, future)`로 변경.

### server/agents/*.md (신규)

4개 에이전트(planner, developer, designer, qa) 시스템 프롬프트 파일 작성.

## Tests

7개 테스트 전체 GREEN:

- `test_orchestration.py`: analyze_instruction → planner 라우팅 검증
- `test_revision_loop.py`: PASS/FAIL/ESCALATED 상태 전이 검증
- `test_qa_gate.py`: 원본 요구사항 포함 여부 + failure_reason 전달 검증

전체 suite: 53 passed, 2 xfailed (기존 stubs 유지)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] mock patch 경로 수정**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** 테스트가 `runners.claude_runner.run_claude_isolated`를 패치했으나, `loop.py`가 `from runners.claude_runner import run_claude_isolated`로 직접 임포트하므로 패치 대상은 `orchestration.loop.run_claude_isolated`여야 함
- **Fix:** 3개 테스트 파일의 patch() 경로를 `orchestration.loop.run_claude_isolated`로 수정
- **Files modified:** server/tests/test_orchestration.py, server/tests/test_revision_loop.py
- **Commit:** 70af674

**2. [Rule 2 - Missing functionality] agents/ 디렉토리 신규 생성**
- **Found during:** Task 1 (loop.py 구현)
- **Issue:** loop.py의 `_load_agent_prompt()`가 `server/agents/{name}.md`를 읽어야 하는데 해당 디렉토리와 파일이 존재하지 않음
- **Fix:** server/agents/ 디렉토리 생성 + planner/developer/designer/qa.md 4개 파일 작성
- **Files modified:** server/agents/planner.md, developer.md, designer.md, qa.md
- **Commit:** 70af674

## Known Stubs

없음 — loop.py의 모든 핵심 메서드가 실제 로직으로 구현됨.

## Self-Check: PASSED

- server/orchestration/loop.py: FOUND
- server/agents/planner.md: FOUND
- server/agents/developer.md: FOUND
- server/agents/designer.md: FOUND
- server/agents/qa.md: FOUND
- .planning/phases/02-orchestration-workflow/02-03-SUMMARY.md: FOUND
- 커밋 b1d1c2a (RED): FOUND
- 커밋 70af674 (GREEN): FOUND
- 7 tests PASSED, 0 failures
