# AI Office

## What This Is

AI 구성원들이 역할을 나눠 유기적으로 협업하는 범용 작업 시스템. 사용자가 프로젝트를 지시하면 Claude(팀장)가 진행방향을 제시하고 Gemma4 기반 구성원들(기획자, 디자이너, 개발자, QA)이 실무를 수행하며, 전 과정을 웹 대시보드에서 모니터링할 수 있다.

## Core Value

사용자의 지시 하나로 AI 구성원들이 자율적으로 협업하여 실제 결과물(파일)을 만들어내는 것.

## Requirements

### Validated

- ✓ SQLite WAL 메시지 버스로 에이전트 간 통신 — Phase 1
- ✓ Claude CLI subprocess 격리 러너 (--bare 토큰 격리) — Phase 1
- ✓ Ollama/Gemma4 순차 큐 러너 — Phase 1
- ✓ EventBus + WebSocket 실시간 로그 브로드캐스트 — Phase 1
- ✓ 산출물 atomic write 파일 시스템 — Phase 1
- ✓ Gemma4 JSON 2-pass 파싱+복구 — Phase 1
- ✓ 4개 에이전트 역할 정의 (기획자/디자이너/개발자/QA) — Phase 2
- ✓ OrchestrationLoop 상태 머신 (Claude→기획자→작업자→QA→검증) — Phase 2
- ✓ TaskGraph DAG 기반 작업 관리 — Phase 2
- ✓ MessageRouter 에이전트 간 메시지 라우팅 + 기획자 broadcast — Phase 2
- ✓ QA 원본 요구사항 독립 참조 검수 — Phase 2
- ✓ Claude 최종 검증 + 보완 루프 (MAX_REVISION_ROUNDS=3) — Phase 2
- ✓ 에이전트별 JSON 경험 저장 + lazy compaction — Phase 3
- ✓ 작업 시작 시 시스템 프롬프트에 경험 주입 — Phase 3
- ✓ QA/Claude 피드백 즉시 경험 기록 — Phase 3
- ✓ 웹 대시보드 — 작업지시 UI + 에이전트 상태 보드 — Phase 4
- ✓ 실시간 로그 스트림 (WebSocket + 히스토리 복구) — Phase 4
- ✓ 산출물 뷰어 (Monaco Editor + react-markdown) — Phase 4
- ✓ DAG 워크플로우 시각화 (React Flow) — Phase 4
- ✓ 다크/라이트 모드 토글 — Phase 4

### Active

- [ ] Claude CLI가 팀장으로서 작업을 분석하고 기획자에게 진행방향과 함께 지시
- [ ] Gemma4 기반 구성원(기획자, 디자이너, 개발자, QA) 각각 독립 실행
- [ ] 구성원 간 자유로운 작업 요청 (개발자→디자이너 등)
- [ ] 기획자가 PM 역할 겸임 — 전체 작업 흐름 추적
- [ ] QA 구성원이 중간 단계별 검수 수행
- [ ] Claude가 최종 산출물 검증, 보완 필요 시 재지시
- [ ] 실제 파일 생성 (코드, 디자인, 문서 등)
- [ ] 웹 대시보드 — 작업지시, 작업 흐름, 실시간 로그, 산출물 뷰어, 상태 보드
- [ ] 대시보드 또는 CLI 양쪽에서 작업 지시 가능

### Out of Scope

- 자동 배포 — 배포는 사용자의 추가 지시로 별도 처리
- 외부 API 연동 (Claude는 CLI만 사용, Gemma4는 Ollama 로컬)
- 모바일 앱 — 웹 대시보드만 v1

## Context

- Claude는 API 없이 CLI(Claude Code 등)로 동작
- Gemma4는 로컬 Ollama로 실행 — 각 구성원마다 별도 프로세스 또는 세션
- 구성원 간 통신은 로컬 메시지 시스템 필요 (파일 기반 또는 큐 기반)
- 구성원들이 생성하는 산출물은 프로젝트 폴더에 실제 파일로 저장
- 대시보드는 작업 과정을 실시간으로 보여줘야 하므로 WebSocket 등 실시간 통신 필요

## Constraints

- **AI 런타임**: Claude = CLI (API 없음), Gemma4 = Ollama 로컬
- **인프라**: 모두 로컬 머신에서 실행 (macOS)
- **통신**: 구성원 간 통신은 로컬에서 해결 (외부 서비스 없음)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Claude를 팀장으로 배치 | 고품질 판단력으로 방향 설정과 최종 검증에 적합 | — Pending |
| Gemma4로 실무 구성원 통일 | 로컬 실행 가능, 여러 인스턴스로 역할 분리 가능 | — Pending |
| 기획자에게 PM 역할 겸임 | 자유로운 구성원 간 요청을 허용하되 흐름 추적 필요 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-03 after Phase 4 completion — v1.0 milestone complete*
