---
phase: 04-web-dashboard
plan: '01'
subsystem: web-dashboard
tags: [react, vite, fastapi, websocket, dag, monaco-editor, tailwindcss]
dependency_graph:
  requires:
    - server/main.py (Phase 1/2 구현)
    - server/orchestration/task_graph.py (TaskGraph.to_state_dict())
    - server/workspace/manager.py (WorkspaceManager.list_artifacts())
    - server/log_bus/event_bus.py (EventBus)
  provides:
    - GET /api/dag — React Flow nodes/edges
    - GET /api/files/{task_id} — 파일 목록
    - GET /api/files/{task_id}/{path} — 파일 내용
    - GET /api/agents — 에이전트 상태
    - GET /api/tasks — 작업 지시 내역
    - GET /api/logs/history — 로그 히스토리 복구
    - dashboard/ React 앱 (빌드 가능)
  affects:
    - DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, WKFL-05
tech_stack:
  added:
    - React 19 + Vite 6 (dashboard/)
    - Tailwind CSS 4 + @tailwindcss/vite
    - @xyflow/react (React Flow DAG)
    - react-use-websocket 4
    - zustand 5 (전역 상태)
    - @tanstack/react-query 5 (서버 상태)
    - @monaco-editor/react (코드 뷰어)
    - react-markdown (마크다운 렌더링)
    - CORSMiddleware (FastAPI)
  patterns:
    - Zustand 스토어 — 단일 진입점 전역 상태
    - React Query — REST API 폴링 (2~5초 간격)
    - useWebSocket — 자동 재연결 WebSocket
    - 다크/라이트 테마 — html.dark 클래스 토글
key_files:
  created:
    - dashboard/src/types.ts
    - dashboard/src/store.ts
    - dashboard/src/App.tsx
    - dashboard/src/components/TaskInput.tsx
    - dashboard/src/components/AgentBoard.tsx
    - dashboard/src/components/LogStream.tsx
    - dashboard/src/components/ArtifactViewer.tsx
    - dashboard/src/components/DagView.tsx
    - dashboard/vite.config.ts
    - dashboard/tsconfig.app.json
    - .planning/phases/04-web-dashboard/04-01-PLAN.md
  modified:
    - server/main.py (엔드포인트 6개 추가, CORS, 로그 히스토리)
decisions:
  - "다크/라이트 토글은 html.dark 클래스 방식으로 구현 — Tailwind CSS 4 다크 모드와 호환"
  - "로그 히스토리는 app.state.log_history 순환 버퍼(500건)로 관리 — EventBus 수정 최소화"
  - "에이전트 상태 API는 active_tasks에서 추론 — 별도 에이전트 상태 DB 불필요"
  - "DAG 노드 위치는 depends_on depth 기반 BFS 계산 — 레이아웃 라이브러리 없이 단순 구현"
  - "ArtifactViewer: .md는 react-markdown, 나머지는 Monaco Editor — 파일 타입별 최적 뷰어"
metrics:
  duration: 7min
  completed_date: "2026-04-03T11:57:38Z"
  tasks_completed: 4
  files_changed: 16
---

# Phase 4 Plan 1: 웹 대시보드 구축 Summary

React 19 + Vite + Tailwind CSS 4 대시보드를 구축하고, FastAPI에 DAG/파일/에이전트/로그 히스토리 엔드포인트 6개를 추가했다.

## What Was Built

### 백엔드 API 확장 (Task 1)

`server/main.py`에 6개 엔드포인트 추가:

| 엔드포인트 | 역할 | 요구사항 |
|-----------|------|---------|
| `GET /api/dag` | TaskGraph → React Flow nodes/edges 변환 | WKFL-05 |
| `GET /api/files/{task_id}` | 산출물 파일 목록 (타입, 크기 포함) | DASH-04 |
| `GET /api/files/{task_id}/{path}` | 파일 내용 반환 (경로 순회 방지) | DASH-04 |
| `GET /api/agents` | 에이전트 상태 목록 | DASH-02 |
| `GET /api/tasks` | 작업 지시 내역 목록 (순서 보존) | DASH-05 |
| `GET /api/logs/history` | 최근 로그 복구용 히스토리 | DASH-03 |

CORSMiddleware 추가 (localhost:5173), log_history 순환 버퍼(500건), task_order 추적.

### 프론트엔드 스캐폴딩 (Task 2)

React 19 + Vite 6 + TypeScript + Tailwind CSS 4 앱 초기화. 의존성:
- `@xyflow/react`, `react-use-websocket`, `zustand`, `@tanstack/react-query`
- `@monaco-editor/react`, `react-markdown`

vite.config.ts에 `/api`→localhost:8000, `/ws`→ws://localhost:8000 프록시 설정.

### 핵심 컴포넌트 (Task 3)

- **types.ts**: 공유 타입 (Agent, Task, LogEntry, DagNode, DagEdge, FileEntry)
- **store.ts**: Zustand 스토어 (에이전트/태스크/로그/DAG/테마)
- **App.tsx**: 헤더(다크/라이트 토글) + 좌측 패널(TaskInput+AgentBoard) + 우측 탭(로그|산출물|DAG)
- **TaskInput.tsx**: 지시 입력(Cmd+Enter 전송) + React Query 폴링(3초) + 지시 내역
- **AgentBoard.tsx**: 5개 에이전트 상태 카드(2초 폴링) + 상태별 색상 배지
- **LogStream.tsx**: useWebSocket 자동 재연결 + 마운트 시 히스토리 복구 + 자동 스크롤

### 산출물 뷰어 + DAG (Task 4)

- **ArtifactViewer.tsx**: 태스크 선택 드롭다운 → 파일 트리 → Monaco Editor(코드)/react-markdown(md) 뷰어
- **DagView.tsx**: React Flow DAG — 상태별 색상 노드(pending/processing/done/failed/blocked), 미니맵, 컨트롤, 범례

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Task 1: 백엔드 API 확장 | e819872 | server/main.py |
| Task 2: Vite 스캐폴딩 | 4718468 | dashboard/ (19 files) |
| Task 3: 핵심 컴포넌트 | ebf53f8 | src/types.ts, store.ts, App.tsx, 4 components |
| Task 4: ArtifactViewer + DagView | 59e0f73 | ArtifactViewer.tsx, DagView.tsx |

## Deviations from Plan

### Auto-fixed Issues

None.

### Plan Adjustments

**1. [Plan Design] 04-01-PLAN.md를 실행 전에 생성**
- **Found during:** 초기화 단계
- **Issue:** 계획 파일이 존재하지 않아 실행 불가
- **Fix:** CONTEXT.md, REQUIREMENTS.md, 기존 PLAN.md 구조를 참고하여 04-01-PLAN.md 생성
- **Files modified:** `.planning/phases/04-web-dashboard/04-01-PLAN.md`

**2. [Rule 2 - Missing] Task 3에서 ArtifactViewer/DagView 스텁 선생성**
- **Found during:** Task 3 빌드 검증
- **Issue:** App.tsx에서 ArtifactViewer, DagView를 임포트하므로 Task 4 전에 스텁 필요
- **Fix:** 빌드 통과를 위한 최소 스텁 컴포넌트 생성 후 Task 4에서 완전 구현

## Known Stubs

없음 — 모든 컴포넌트가 실제 API와 연동되어 구현됨. TaskInput, AgentBoard는 빈 배열 기본값을 사용하나, 이는 서버 응답 전 UI 안정성을 위한 의도된 초기값이며 API 응답 시 즉시 대체됨.

## Self-Check: PASSED

파일 존재 확인:
- dashboard/src/App.tsx: FOUND
- dashboard/src/store.ts: FOUND
- dashboard/src/types.ts: FOUND
- dashboard/src/components/TaskInput.tsx: FOUND
- dashboard/src/components/AgentBoard.tsx: FOUND
- dashboard/src/components/LogStream.tsx: FOUND
- dashboard/src/components/ArtifactViewer.tsx: FOUND
- dashboard/src/components/DagView.tsx: FOUND
- server/main.py: FOUND (6 new endpoints)

커밋 존재 확인:
- e819872: FOUND (feat(04-01): 백엔드 API 확장)
- 4718468: FOUND (chore(04-01): Vite 스캐폴딩)
- ebf53f8: FOUND (feat(04-01): 핵심 컴포넌트)
- 59e0f73: FOUND (feat(04-01): ArtifactViewer + DagView)

빌드 검증: npm run build — SUCCESS (0 type errors)
