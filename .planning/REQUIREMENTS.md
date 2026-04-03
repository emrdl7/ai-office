# Requirements: AI Office

**Defined:** 2026-04-03
**Core Value:** 사용자의 지시 하나로 AI 구성원들이 자율적으로 협업하여 실제 결과물(파일)을 만들어내는 것

## v1 Requirements

### Orchestration (오케스트레이션)

- [ ] **ORCH-01**: Claude CLI가 사용자의 프로젝트 지시를 분석하고 기획자에게 진행방향과 함께 전달할 수 있다
- [ ] **ORCH-02**: 기획자, 디자이너, 개발자, QA 4개 에이전트가 각각 독립된 역할과 시스템 프롬프트를 가진다
- [ ] **ORCH-03**: 에이전트 간 통신은 JSON 구조화 메시지 스키마(task_request, task_result, status_update)를 따른다
- [ ] **ORCH-04**: Claude가 최종 산출물을 검증하고, 불합격 시 구체적 보완 사항과 함께 재지시할 수 있다
- [ ] **ORCH-05**: Gemma4 에이전트는 순차적으로 실행되며, 로컬 하드웨어 부하를 고려한 실행 정책(큐 기반 순차 처리)을 따른다

### Workflow (워크플로우)

- [ ] **WKFL-01**: 기획자가 PM으로서 전체 태스크 상태(대기/진행/완료/차단)를 추적하고 관리한다
- [ ] **WKFL-02**: QA 에이전트가 각 작업 단계 완료 시 원본 요구사항 대비 검수를 수행한다
- [ ] **WKFL-03**: 구성원이 다른 구성원에게 자유롭게 작업을 요청할 수 있다 (개발자→디자이너 등)
- [ ] **WKFL-04**: 기획자가 모든 에이전트 간 요청과 결과를 추적하여 전체 흐름을 파악한다
- [ ] **WKFL-05**: 워크플로우가 DAG 형태로 시각화되어 태스크 의존성과 진행상태를 보여준다

### Agent Memory (에이전트 기억/학습)

- [ ] **AMEM-01**: 각 에이전트가 자신의 역할에 맞는 경험(성공/실패 패턴, 피드백)을 프로젝트 단위로 저장한다
- [ ] **AMEM-02**: 에이전트가 이전 작업 경험을 참조하여 동일한 실수를 반복하지 않고 품질을 개선한다
- [ ] **AMEM-03**: Claude의 보완 지시와 QA 검수 피드백이 해당 에이전트의 경험 기록에 자동 반영된다

### Infra (인프라)

- [x] **INFR-01**: SQLite(WAL 모드) 기반 메시지 큐로 에이전트 간 태스크 전달 및 상태 공유를 처리한다
- [x] **INFR-02**: Claude CLI는 subprocess로 실행되며, 토큰 격리(최소 컨텍스트 주입)를 적용한다
- [x] **INFR-03**: Gemma4는 Ollama 로컬 인스턴스에서 실행되며, 단일 요청 큐로 순차 처리한다
- [x] **INFR-04**: 모든 에이전트 이벤트를 수집하는 로그 버스가 존재하며, 대시보드에 실시간 전달된다
- [x] **INFR-05**: Gemma4의 구조화 출력(JSON)에 대한 파싱+복구 전략이 적용된다

### Artifact (산출물)

- [x] **ARTF-01**: 모든 에이전트 산출물은 프로젝트 폴더에 실제 파일로 즉시 저장된다
- [x] **ARTF-02**: 산출물은 코드, 디자인 명세, 문서 등 다양한 형식을 지원한다

### Dashboard (웹 대시보드)

- [ ] **DASH-01**: 웹 대시보드에서 프로젝트 작업 지시를 입력하고 Claude 팀장에게 전달할 수 있다
- [ ] **DASH-02**: 에이전트별 상태(작업중/대기/완료/에러)를 실시간 상태 보드로 확인할 수 있다
- [ ] **DASH-03**: 모든 에이전트의 작업 로그를 실시간 스트리밍으로 확인할 수 있다 (WebSocket)
- [ ] **DASH-04**: 생성된 산출물을 대시보드에서 확인할 수 있다 (코드 구문 강조, 마크다운 렌더링)
- [ ] **DASH-05**: 작업 지시 내역을 확인할 수 있다

## v2 Requirements

### Enhanced Dashboard

- **DASH-06**: 에이전트별 로그 필터링
- **DASH-07**: CLI + 대시보드 이중 진입점
- **DASH-08**: 산출물 버전 diff 뷰

### Enhanced Workflow

- **WKFL-06**: 에이전트 간 자율 요청 시 자동 갭 감지 (에이전트가 스스로 부족한 점을 인식)

### Performance

- **PERF-01**: Ollama 병렬 처리 최적화 (하드웨어 여유 시)

## Out of Scope

| Feature | Reason |
|---------|--------|
| 자동 배포 | 배포는 사용자의 추가 지시로 별도 처리 — 자동화 시 복구 불가능한 에러 위험 |
| 외부 API/클라우드 연동 | 전체 로컬 실행 제약 조건 — v2+ 고려 |
| 프로젝트 간 에이전트 메모리 공유 | 컨텍스트 오염 및 디버깅 어려움 |
| 5개 이상 에이전트 역할 | 연구(MAST 2025)에 따르면 4개 이상에서 조율 이득 감소 |
| 무한 자율 루프 | 에러 누적 위험 — 사용자 승인 기반 단계 전환 |
| 에이전트 간 동시 파일 쓰기 | 레이스 컨디션 위험 — 에이전트별 산출물 파일 독점 소유 |
| 모바일 앱 | 웹 대시보드만 v1 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFR-01 | Phase 1 | Complete |
| INFR-02 | Phase 1 | Complete |
| INFR-03 | Phase 1 | Complete |
| INFR-04 | Phase 1 | Complete |
| INFR-05 | Phase 1 | Complete |
| ARTF-01 | Phase 1 | Complete |
| ARTF-02 | Phase 1 | Complete |
| ORCH-01 | Phase 2 | Pending |
| ORCH-02 | Phase 2 | Pending |
| ORCH-03 | Phase 2 | Pending |
| ORCH-04 | Phase 2 | Pending |
| ORCH-05 | Phase 2 | Pending |
| WKFL-01 | Phase 2 | Pending |
| WKFL-02 | Phase 2 | Pending |
| WKFL-03 | Phase 2 | Pending |
| WKFL-04 | Phase 2 | Pending |
| AMEM-01 | Phase 3 | Pending |
| AMEM-02 | Phase 3 | Pending |
| AMEM-03 | Phase 3 | Pending |
| DASH-01 | Phase 4 | Pending |
| DASH-02 | Phase 4 | Pending |
| DASH-03 | Phase 4 | Pending |
| DASH-04 | Phase 4 | Pending |
| DASH-05 | Phase 4 | Pending |
| WKFL-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-04-03*
*Last updated: 2026-04-03 after roadmap creation*
