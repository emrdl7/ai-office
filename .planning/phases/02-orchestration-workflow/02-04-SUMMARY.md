---
phase: 02-orchestration-workflow
plan: "04"
subsystem: api
tags: [fastapi, orchestration, pydantic, asyncio, pytest]

# Dependency graph
requires:
  - phase: 02-orchestration-workflow/02-03
    provides: OrchestrationLoop 상태 머신 구현체
  - phase: 02-orchestration-workflow/02-02
    provides: MessageRouter, TaskGraph
  - phase: 02-orchestration-workflow/02-01
    provides: 에이전트 시스템 프롬프트 파일 4개 (agents/*.md)
provides:
  - POST /api/tasks 엔드포인트 (202 Accepted): 사용자 지시를 asyncio.create_task로 백그라운드 실행
  - GET /api/tasks/{task_id} 엔드포인트: 태스크 상태 조회
  - lifespan에서 MessageBus, WorkspaceManager, MessageRouter, OrchestrationLoop 싱글턴 초기화
  - test_agents.py GREEN: 에이전트 시스템 프롬프트 4개 파일 존재 및 섹션 완비 확인
affects: [03-dashboard, 04-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.create_task 패턴으로 FastAPI에서 비동기 백그라운드 실행 (BackgroundTasks 대신)"
    - "app.state 딕셔너리로 lifespan에서 생성한 싱글턴 및 태스크 상태 공유"
    - "WorkspaceManager(task_id='', workspace_root='workspace')로 전체 workspace 루트 공유"

key-files:
  created:
    - server/tests/test_agents.py
  modified:
    - server/main.py

key-decisions:
  - "asyncio.create_task 사용: OrchestrationLoop.run()이 async라서 FastAPI BackgroundTasks(동기 기반) 대신 asyncio.create_task 선택"
  - "WorkspaceManager(task_id='', workspace_root='workspace'): task_id='' 로 workspace 루트 전체를 loop가 sub-path로 사용"
  - "data/ 디렉토리 자동 생성: MessageBus SQLite 파일을 위해 main.py 모듈 로드 시점에 mkdir"

patterns-established:
  - "Pattern: FastAPI lifespan에서 asyncio.Queue 기반 싱글턴들을 app.state에 주입"
  - "Pattern: 에이전트 파일 경로는 Path(__file__).parent.parent.parent / 'agents' 절대 경로로 계산"

requirements-completed: [ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05, WKFL-01, WKFL-02, WKFL-03, WKFL-04]

# Metrics
duration: 8min
completed: 2026-04-03
---

# Phase 2 Plan 04: FastAPI 진입점 통합 Summary

**POST /api/tasks 엔드포인트와 OrchestrationLoop 싱글턴을 FastAPI lifespan에 연결, 에이전트 프롬프트 테스트 57개 전부 GREEN**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-03T08:57:57Z
- **Completed:** 2026-04-03T09:05:45Z
- **Tasks:** 2 (+ 1 checkpoint)
- **Files modified:** 2

## Accomplishments
- POST /api/tasks (202 Accepted): 사용자 지시를 asyncio.create_task로 오케스트레이션 백그라운드 실행
- GET /api/tasks/{task_id}: active_tasks 딕셔너리에서 실시간 상태 조회
- lifespan에서 MessageBus → WorkspaceManager → MessageRouter → OrchestrationLoop 의존성 체인 초기화
- test_agents.py 4개 테스트 xfail stub → PASSED 전환 (에이전트 파일 존재 + 섹션 완비 검증)
- 전체 Phase 2 테스트 suite 57개 모두 PASSED (0 failures)

## Task Commits

각 태스크별 단독 커밋:

1. **Task 1: main.py OrchestrationLoop 통합 + POST /api/tasks** - `d9c4995` (feat)
2. **Task 2: test_agents.py stub → GREEN 전환** - `dddd566` (test)

## Files Created/Modified
- `server/main.py` - POST /api/tasks, GET /api/tasks/{task_id} 추가, lifespan에 OrchestrationLoop 통합
- `server/tests/test_agents.py` - xfail stub 4개를 실제 구현 테스트로 전환

## Decisions Made
- `asyncio.create_task` 사용: OrchestrationLoop.run()이 async coroutine이라 FastAPI `BackgroundTasks`(동기 함수 기반)와 부적합, asyncio.create_task로 대체
- `WorkspaceManager(task_id='', workspace_root='workspace')`: 플랜에서는 task_id 없이 생성하도록 명시했으나 실제 생성자에 task_id 파라미터가 필수. task_id=''를 사용하면 workspace_root 전체가 루트가 되어 loop.py의 `{node.task_id}/result.json` 경로 패턴과 호환됨
- `Path('data').mkdir(exist_ok=True)` 모듈 레벨 실행: lifespan 내부가 아닌 모듈 로드 시점에 생성하여 MessageBus 싱글턴 초기화 직전 디렉토리 보장

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] WorkspaceManager 생성자 시그니처 불일치 수정**
- **Found during:** Task 1 (main.py 수정)
- **Issue:** 플랜에서 `WorkspaceManager(workspace_root='workspace')`로 생성하도록 명시했으나, 실제 workspace/manager.py의 생성자는 `__init__(self, task_id: str, workspace_root='workspace')`로 task_id가 필수 위치 인자임
- **Fix:** `WorkspaceManager(task_id='', workspace_root='workspace')` 사용. task_id=''이면 task_dir = workspace_root/''/. = workspace_root/ 가 되어 loop.py의 f'{node.task_id}/result.json' 경로 패턴과 호환됨
- **Files modified:** server/main.py
- **Verification:** `from main import app` import 성공, 구문 오류 없음
- **Committed in:** d9c4995 (Task 1 커밋에 포함)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** 생성자 시그니처 불일치 수정으로 import 오류 방지. 기능 범위 변경 없음.

## Issues Encountered
없음 — 모든 테스트 즉시 PASSED

## User Setup Required
없음 — 외부 서비스 설정 불필요

## Checkpoint Result

**Checkpoint: Phase 2 전체 통합 검증** — 자동 승인

전체 테스트 suite 실행 결과:
```
57 passed, 17 warnings in 0.26s
```
- 모든 XFAIL stub 없음 (test_agents.py 4개 모두 PASSED)
- 57개 테스트 전체 PASSED
- /api/tasks 엔드포인트 routes 확인 완료

## Next Phase Readiness
- Phase 2 오케스트레이션 워크플로우 전체 완료
- POST /api/tasks로 실제 워크플로우 실행 가능 (Ollama/Claude CLI 환경 필요)
- Phase 3 (대시보드 또는 CLI) 진입 준비 완료
- 주의: 실제 엔드투엔드 실행은 Ollama + gemma4 모델, Claude CLI 설치 필요

---
*Phase: 02-orchestration-workflow*
*Completed: 2026-04-03*
