# Phase 2: Orchestration & Workflow - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 02-orchestration-workflow
**Areas discussed:** 에이전트 시스템 프롬프트, 오케스트레이션 흐름, QA 검수 정책, 보완 루프 설계

---

## 에이전트 시스템 프롬프트

| Option | Description | Selected |
|--------|-------------|----------|
| 파일 기반 (추천) | agents/ 폴더에 역할별 .md 파일로 관리 | |
| DB 저장 | SQLite에 시스템 프롬프트 저장 | |
| 맡길게요 | Claude가 적절히 판단 | ✓ |

**User's choice:** Claude 재량
**Notes:** 프롬프트 포함 내용은 명시 — 역할 정의, 출력 형식, 협업 규칙, 금지 사항

---

## 오케스트레이션 흐름

| Option | Description | Selected |
|--------|-------------|----------|
| 항상 기획자 경유 (추천) | Claude → 기획자 → 작업자 | ✓ |
| 직접 분배 가능 | Claude가 간단한 작업은 직접 지시 | |

**User's choice:** 항상 기획자 경유

| Option | Description | Selected |
|--------|-------------|----------|
| 단계별 순차 | 디자인 → 개발 → QA 순서로 | |
| 태스크 그래프 | 의존성 기반 병렬/순차 자동 결정 | ✓ |

**User's choice:** 태스크 그래프

---

## QA 검수 정책

| Option | Description | Selected |
|--------|-------------|----------|
| 각 작업자 완료 시 (추천) | 디자이너 완료 → QA → 개발자 완료 → QA | ✓ |
| 전체 완료 후 | 모든 작업자 완료 후 한번에 검수 | |

**User's choice:** 각 작업자 완료 시

| Option | Description | Selected |
|--------|-------------|----------|
| 해당 작업자에게 반려 (추천) | 구체적 문제점과 함께 작업자에게 재작업 요청 | ✓ |
| 기획자에게 보고 | 기획자가 판단해서 재배분 | |

**User's choice:** 해당 작업자에게 반려

---

## 보완 루프 설계

| Option | Description | Selected |
|--------|-------------|----------|
| 3회 (추천) | 3회 보완 후 사용자에게 에스컬레이션 | |
| 5회 | 더 많이 시도 | |
| 무제한 | 성공할 때까지 | |
| 맡길게요 | Claude가 적절히 판단 | ✓ |

**User's choice:** Claude 재량

| Option | Description | Selected |
|--------|-------------|----------|
| 기획자 경유 (추천) | Claude → 기획자 → 적절한 작업자 | ✓ |
| 작업자 직접 | Claude가 해당 작업자에게 직접 보완 지시 | |

**User's choice:** 기획자 경유

---

## Claude's Discretion

- 시스템 프롬프트 저장 형태
- 태스크 그래프 구현 방식
- 최대 보완 반복 횟수
- 에이전트 간 메시지 라우팅 구현 세부사항

## Deferred Ideas

없음
