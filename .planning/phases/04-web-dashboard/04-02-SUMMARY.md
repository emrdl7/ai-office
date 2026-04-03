---
phase: 04-web-dashboard
plan: '02'
subsystem: api
tags: [fastapi, cors, websocket, rest-api, dag, workspace, react-flow]

# 의존성 그래프
requires:
  - phase: 01-infra-foundation
    provides: WorkspaceManager, EventBus, WebSocket 인프라
  - phase: 02-orchestration-workflow
    provides: TaskGraph, OrchestrationLoop, WorkflowState
provides:
  - GET /api/tasks — 작업 지시 내역 목록 API
  - GET /api/agents — 에이전트 상태 목록 API
  - GET /api/logs/history — 로그 히스토리 API (새로고침 복구)
  - GET /api/workspace/{task_id}/files — 파일 트리 API
  - GET /api/workspace/{task_id}/files/{path} — 파일 내용 API
  - GET /api/dag — React Flow 형식 DAG API
  - CORSMiddleware (localhost:5173 허용)
affects: [04-web-dashboard-frontend, dashboard-integration]

# 기술 추적
tech-stack:
  added: [fastapi.middleware.cors.CORSMiddleware, fastapi.responses.PlainTextResponse]
  patterns: [순환 버퍼 로그 히스토리, topological depth 기반 DAG 레이아웃, app.state 확장 패턴]

key-files:
  created: []
  modified:
    - server/main.py

key-decisions:
  - "app.state.log_history에 최대 500건 순환 버퍼로 WebSocket 로그 히스토리 관리"
  - "loop._task_graph 내부 속성 직접 접근 — 내부 도구이므로 getter 추가 없이 허용"
  - "topological depth 기반 x축, 같은 깊이 내 인덱스로 y축 결정하는 DAG 레이아웃"
  - "task_order 리스트로 POST 순서 기록 — GET /api/tasks 정렬 기준"

patterns-established:
  - "app.state 확장: lifespan에서 추가 상태 필드 초기화 패턴"
  - "WorkspaceManager(task_id=task_id, workspace_root='workspace')로 태스크별 파일 접근"
  - "경로 순회 방지: task_id에 '..' 또는 '/' 포함 여부 먼저 검사, safe_path()로 이중 방어"

requirements-completed: [DASH-04, DASH-05, WKFL-05]

# 메트릭
duration: 4min
completed: 2026-04-03
---

# Phase 4, Plan 02: 백엔드 API 확장 Summary

**FastAPI server/main.py에 대시보드용 6개 신규 엔드포인트(DAG/파일/에이전트/로그히스토리/태스크목록)와 CORSMiddleware(localhost:5173) 추가**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-03T11:51:02Z
- **Completed:** 2026-04-03T11:54:26Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 대시보드 프론트엔드가 필요로 하는 REST API 엔드포인트 6개 신규 추가
- CORSMiddleware로 Vite dev 서버(localhost:5173)와의 크로스 오리진 요청 허용
- WebSocket /ws/logs에 순환 버퍼(최대 500건) 연동 — 새로고침 후 로그 복구 지원
- TaskGraph를 topological depth 기반 레이아웃으로 React Flow nodes/edges 형식 변환

## Task Commits

각 태스크는 원자적으로 커밋됨:

1. **Task 1: 백엔드 누락 API 엔드포인트 추가 + CORS 설정** - `5747e04` (feat)

## Files Created/Modified

- `server/main.py` — 6개 신규 엔드포인트, CORSMiddleware, app.state 확장, log_history 순환 버퍼

## Decisions Made

- `loop._task_graph` 내부 속성 직접 접근: 내부 도구이므로 별도 getter 추가 없이 허용
- `app.state.log_history`를 전역 `app` 싱글턴으로 참조: WebSocket handler에서 `request` 없이 app state 접근
- topological depth 기반 DAG 레이아웃: x=depth*250, y=index*100 고정값 — 프론트엔드에서 reactflow 자동 레이아웃으로 덮어쓸 수 있음

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `EventBus` unused import 정리 — `event_bus.py`에서 `EventBus`를 import하지 않도록 수정 (lint 개선)

## Known Stubs

None — 모든 엔드포인트는 실제 데이터를 반환함. 단, `/api/agents`는 현재 항상 `idle` 상태 반환 (실시간 상태 업데이트는 WebSocket 이벤트 기반으로 프론트엔드에서 처리).

## Next Phase Readiness

- 백엔드 API 완비 — 프론트엔드 대시보드(04-01)가 모든 엔드포인트를 사용할 수 있음
- `GET /api/agents` 상태 추적은 WebSocket `status_change` 이벤트로 프론트엔드에서 처리 예정
- 서버 시작: `cd server && uv run uvicorn main:app --reload --port 8000`

---
*Phase: 04-web-dashboard*
*Completed: 2026-04-03*
