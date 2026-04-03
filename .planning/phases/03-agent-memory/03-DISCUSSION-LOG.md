# Phase 3: Agent Memory - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.

**Date:** 2026-04-03
**Phase:** 03-agent-memory
**Areas discussed:** 경험 저장 형식, 경험 참조 방식, 피드백 반영, 경험 압축

---

## 경험 저장 형식

| Option | Description | Selected |
|--------|-------------|----------|
| JSON 파일 (추천) | 에이전트별 JSON 파일 | ✓ |
| SQLite 테이블 | DB에 저장, 검색/필터링 용이 | |

**User's choice:** JSON 파일

---

## 경험 참조 방식

| Option | Description | Selected |
|--------|-------------|----------|
| 프롬프트 주입 (추천) | 시스템 프롬프트에 관련 경험 추가 | ✓ |
| 별도 컨텍스트 | 경험을 별도 메시지로 전달 | |

**User's choice:** 프롬프트 주입

---

## 피드백 반영

| Option | Description | Selected |
|--------|-------------|----------|
| 즉시 반영 (추천) | QA/Claude 피드백 시점에 즉시 저장 | ✓ |
| 작업 종료 후 | 워크플로우 종료 후 한번에 반영 | |

**User's choice:** 즉시 반영

---

## 경험 압축 (사용자 제안)

| Option | Description | Selected |
|--------|-------------|----------|
| 건수 기반 (추천) | 최근 N건 상세 유지, 나머지 요약 압축 | ✓ |
| 주기적 요약 | 일정 주기마다 전체 요약 | |

**User's choice:** 건수 기반
**Notes:** 사용자가 직접 "쌓이면 무거워지니 압축 필요" 제안

---

## Claude's Discretion

- 경험 JSON 스키마 상세
- 관련 경험 선별 알고리즘
- 압축 유지 건수 N값
- 요약 방식

## Deferred Ideas

없음
