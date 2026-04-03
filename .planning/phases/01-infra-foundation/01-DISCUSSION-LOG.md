# Phase 1: Infra Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 01-infra-foundation
**Areas discussed:** 서버 언어 선택, 메시지 스키마, 프로젝트 구조, Claude CLI 연동

---

## 서버 언어 선택

| Option | Description | Selected |
|--------|-------------|----------|
| Python (추천) | FastAPI — Ollama SDK, CrewAI 생태계와 직결, AI 에이전트 관리에 강점 | ✓ |
| Node.js | TypeScript — 프론트/백엔드 언어 통일, WebSocket 네이티브 | |
| 맡길게요 | Claude가 적절히 판단 | |

**User's choice:** Python (FastAPI)
**Notes:** 없음

---

## 메시지 스키마

| Option | Description | Selected |
|--------|-------------|----------|
| 최소한 (추천) | type, from, to, payload, reply_to — 필수 필드만, 확장은 나중에 | |
| 풍부하게 | priority, tags, metadata, ack 등 전체 필드 초기부터 정의 | ✓ |
| 맡길게요 | Claude가 적절히 판단 | |

**User's choice:** 풍부하게
**Notes:** 없음

---

## 프로젝트 구조

| Option | Description | Selected |
|--------|-------------|----------|
| 기능별 분리 (추천) | server/, dashboard/, agents/, shared/ | ✓ |
| 레이어별 분리 | backend/, frontend/, common/ — 전통적 3계층 | |
| 맡길게요 | Claude가 적절히 판단 | |

**User's choice:** 기능별 분리
**Notes:** 없음

---

## Claude CLI 연동

| Option | Description | Selected |
|--------|-------------|----------|
| subprocess 직접 (추천) | Python subprocess로 claude CLI 실행, stdin/stdout JSON-lines로 통신 | ✓ |
| Claude Agent SDK | Anthropic의 claude-agent-sdk 사용 — 내부적으로 subprocess이지만 추상화 제공 | |
| 맡길게요 | Claude가 적절히 판단 | |

**User's choice:** subprocess 직접
**Notes:** 없음

---

## Claude's Discretion

- SQLite 테이블 스키마 상세 설계
- 로그 버스 구현 방식
- Ollama HTTP 클라이언트 구현 세부사항
- atomic write 패턴 구현 방식

## Deferred Ideas

없음
