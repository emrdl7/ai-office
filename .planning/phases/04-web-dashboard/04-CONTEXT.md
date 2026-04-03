# Phase 4: Web Dashboard - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

사용자가 브라우저에서 작업을 지시하고, 에이전트 진행 상황을 실시간으로 모니터링하며, 최종 산출물을 확인하고, 태스크 의존성을 DAG로 시각화할 수 있는 웹 대시보드를 구축한다.

</domain>

<decisions>
## Implementation Decisions

### 프론트엔드 스택
- **D-01:** React 19 + Vite로 프론트엔드를 구축한다. dashboard/ 디렉토리에 위치.
- **D-02:** Tailwind CSS를 스타일링에 사용한다.
- **D-03:** React Flow 라이브러리로 DAG 워크플로우를 시각화한다.

### 디자인
- **D-04:** 다크 모드와 라이트 모드를 둘 다 지원한다 (토글).
- **D-05:** 대시보드 레이아웃 구성은 Claude 재량.

### 대시보드 기능 (REQUIREMENTS에서 도출)
- **D-06:** 작업 지시 입력 UI — `POST /api/tasks`로 전달, 지시 내역 목록 표시
- **D-07:** 에이전트 상태 보드 — 작업중/대기/완료/에러 실시간 표시
- **D-08:** 실시간 로그 스트림 — WebSocket `/ws/logs` 연결, 새로고침 후 복구
- **D-09:** 산출물 뷰어 — 파일 트리 + 코드 구문 강조 + 마크다운 렌더링
- **D-10:** DAG 시각화 — React Flow로 태스크 의존성과 진행 상태 표시

### Claude's Discretion
- 대시보드 레이아웃 구성 (단일 페이지 vs 탭 vs 사이드바)
- 코드 구문 강조 라이브러리 선택
- 마크다운 렌더링 라이브러리 선택
- 로그 복구 메커니즘 (REST API vs WebSocket 히스토리)
- 상태 보드 폴링 vs WebSocket 방식

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backend API (Phase 2에서 구현)
- `server/main.py` — FastAPI 앱, POST /api/tasks, GET /api/tasks/{id}, WebSocket /ws/logs
- `server/orchestration/loop.py` — OrchestrationLoop 상태 머신, WorkflowState enum
- `server/orchestration/task_graph.py` — TaskGraph, TaskNode, TaskStatus — DAG 시각화 데이터 소스
- `server/log_bus/event_bus.py` — EventBus, LogEvent — 실시간 로그 데이터 모델
- `server/bus/schemas.py` — AgentMessage — 에이전트 상태 정보
- `server/bus/payloads.py` — TaskRequestPayload, TaskResultPayload — 태스크 데이터

### Project
- `.planning/PROJECT.md` — 프로젝트 비전
- `.planning/REQUIREMENTS.md` — DASH-01~05, WKFL-05 요구사항

### Research
- `.planning/research/STACK.md` — React/Vite 프론트엔드 스택 추천

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `POST /api/tasks` — 작업 지시 제출 API 이미 구현
- `GET /api/tasks/{task_id}` — 태스크 상태 조회 API 이미 구현
- `WebSocket /ws/logs` — 실시간 로그 스트림 이미 구현
- `TaskGraph.to_state_dict()` — DAG 상태를 딕셔너리로 직렬화 (프론트엔드용)
- `WorkflowState` enum — 상태 보드 표시용 상태 값

### Established Patterns
- FastAPI + WebSocket 패턴 (Phase 1에서 확립)
- Pydantic 모델 기반 JSON 직렬화

### Integration Points
- `GET /api/tasks/{id}` → 상태 보드 데이터
- `WebSocket /ws/logs` → 실시간 로그 스트림
- `TaskGraph.to_state_dict()` → DAG 시각화 데이터
- 산출물 파일은 `workspace/<task-id>/`에 위치 → 파일 트리 API 필요

</code_context>

<specifics>
## Specific Ideas

- 백엔드 API가 대부분 구현되어 있으므로 프론트엔드 중심 구현
- 산출물 파일 접근을 위한 REST API 추가 필요 (파일 목록 + 파일 내용)
- DAG 시각화는 TaskGraph.to_state_dict()의 노드/엣지 데이터를 React Flow 형식으로 변환
- 로그 복구: 새로고침 시 최근 로그를 REST API로 가져온 후 WebSocket 재연결

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-web-dashboard*
*Context gathered: 2026-04-03*
