# Roadmap: AI Office

## Overview

인프라 기반(메시지 버스·에이전트 러너)을 먼저 안정화한 후, 그 위에 오케스트레이션 로직과 워크플로우를 쌓고, 에이전트 경험 학습을 추가하며, 마지막으로 웹 대시보드로 전체를 시각화하는 bottom-up 빌드 순서를 따른다. 각 페이즈가 완료될 때마다 독립적으로 검증 가능한 능력을 제공한다.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infra Foundation** - 메시지 버스, 상태 저장소, Claude CLI 러너, Ollama 러너, 워크스페이스 파일 시스템 구축 (completed 2026-04-03)
- [ ] **Phase 2: Orchestration & Workflow** - 에이전트 역할 정의, 오케스트레이션 서버, 메시지 라우팅, QA 게이트, Claude 최종 검증 루프
- [ ] **Phase 3: Agent Memory** - 에이전트별 프로젝트 단위 경험 저장·참조·자동 반영
- [ ] **Phase 4: Web Dashboard** - 작업지시 UI, 실시간 로그 스트림, 에이전트 상태 보드, 산출물 뷰어, DAG 시각화

## Phase Details

### Phase 1: Infra Foundation
**Goal**: 모든 에이전트와 서버가 의존하는 로컬 인프라가 가동되고 검증된다
**Depends on**: Nothing (first phase)
**Requirements**: INFR-01, INFR-02, INFR-03, INFR-04, INFR-05, ARTF-01, ARTF-02
**Success Criteria** (what must be TRUE):
  1. SQLite WAL 모드 메시지 버스에 메시지를 쓰고 읽는 왕복이 성공하며, atomic write(tmp+rename) 패턴이 적용된다
  2. Claude CLI가 subprocess로 실행되어 JSON-lines 응답을 반환하고, 불필요한 컨텍스트 주입 없이 최소 토큰으로 동작한다
  3. Ollama/Gemma4가 HTTP REST 호출을 받아 응답하며, 단일 요청 큐로 순차 처리됨이 확인된다
  4. 에이전트 이벤트가 로그 버스에 기록되고 WebSocket 채널로 브로드캐스트된다
  5. 에이전트가 생성한 파일이 태스크별 격리 디렉토리(`workspace/<task-id>/`)에 즉시 저장되며, 코드·문서·디자인 명세 등 다양한 형식으로 저장된다
**Plans**: 6 plans

Plans:
- [x] 01-01-PLAN.md — uv 환경 초기화 + 전체 파일 scaffold + 테스트 stub
- [x] 01-02-PLAN.md — SQLite WAL 메시지 버스 (INFR-01)
- [x] 01-03-PLAN.md — WorkspaceManager atomic write + Gemma4 JSON 파서 (ARTF-01, ARTF-02, INFR-05)
- [x] 01-04-PLAN.md — Claude CLI subprocess 러너 (INFR-02)
- [x] 01-05-PLAN.md — Ollama asyncio.Queue 단일 워커 (INFR-03)
- [x] 01-06-PLAN.md — EventBus + FastAPI WebSocket /ws/logs (INFR-04)

### Phase 2: Orchestration & Workflow
**Goal**: 사용자의 프로젝트 지시 하나로 4개 에이전트가 순차 실행되어 실제 산출물을 만들고 Claude가 최종 검증까지 완료할 수 있다
**Depends on**: Phase 1
**Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05, WKFL-01, WKFL-02, WKFL-03, WKFL-04
**Success Criteria** (what must be TRUE):
  1. Claude CLI가 사용자 지시를 분석하여 기획자 에이전트에게 구조화된 지시(task_request)를 전달하고, 기획자가 PM으로서 전체 태스크 상태를 추적한다
  2. 기획자·디자이너·개발자·QA 4개 에이전트가 각각 독립된 시스템 프롬프트로 실행되며, 에이전트 간 모든 통신이 JSON 메시지 스키마(task_request, task_result, status_update)를 따른다
  3. 구성원이 다른 구성원에게 작업을 요청할 수 있으며, 기획자가 그 모든 요청과 결과를 추적하여 전체 흐름을 파악한다
  4. QA 에이전트가 각 단계 완료 시 원본 요구사항 대비 검수를 수행하고 합격/불합격 결과를 기록한다
  5. Claude가 최종 산출물을 검증하여 합격 또는 구체적 보완 사항과 함께 재지시하며, Gemma4 에이전트는 순차 큐로만 실행된다
**Plans**: TBD

### Phase 3: Agent Memory
**Goal**: 에이전트가 이전 프로젝트 경험을 참조하여 동일한 실수를 반복하지 않고 품질을 점진적으로 개선할 수 있다
**Depends on**: Phase 2
**Requirements**: AMEM-01, AMEM-02, AMEM-03
**Success Criteria** (what must be TRUE):
  1. 각 에이전트가 성공·실패 패턴과 피드백을 프로젝트 단위 파일로 저장하며, 다음 작업 시작 시 해당 경험을 컨텍스트에 포함한다
  2. Claude의 보완 지시와 QA 검수 피드백이 해당 에이전트의 경험 기록에 자동 반영되어, 이후 동일 유형의 실수가 감소한다
**Plans**: TBD

### Phase 4: Web Dashboard
**Goal**: 사용자가 브라우저에서 작업을 지시하고, 에이전트 진행 상황을 실시간으로 모니터링하며, 최종 산출물을 확인할 수 있다
**Depends on**: Phase 2
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, WKFL-05
**Success Criteria** (what must be TRUE):
  1. 대시보드에서 프로젝트 지시를 입력하면 Claude 팀장에게 전달되고, 작업 지시 내역을 목록으로 확인할 수 있다
  2. 에이전트별 현재 상태(작업중/대기/완료/에러)를 실시간 상태 보드에서 확인할 수 있다
  3. 모든 에이전트의 작업 로그가 WebSocket으로 실시간 스트리밍되며, 페이지 새로고침 후에도 이전 로그가 복구된다
  4. 생성된 산출물을 파일 트리와 구문 강조(코드) 및 마크다운 렌더링으로 대시보드에서 확인할 수 있다
  5. 태스크 의존성과 진행 상태가 DAG 형태로 시각화되어 전체 워크플로우 흐름을 한눈에 파악할 수 있다
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infra Foundation | 6/6 | Complete   | 2026-04-03 |
| 2. Orchestration & Workflow | 0/? | Not started | - |
| 3. Agent Memory | 0/? | Not started | - |
| 4. Web Dashboard | 0/? | Not started | - |
