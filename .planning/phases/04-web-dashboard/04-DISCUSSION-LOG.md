# Phase 4: Web Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.

**Date:** 2026-04-03
**Phase:** 04-web-dashboard
**Areas discussed:** 대시보드 레이아웃, 프론트엔드 스택, DAG 시각화, 디자인 스타일

---

## 대시보드 레이아웃

| Option | Description | Selected |
|--------|-------------|----------|
| 단일 페이지 (추천) | 좌측 상태보드 + 우측 로그/산출물 탭 | |
| 탭 기반 | 상단 탭으로 상태/로그/산출물/DAG 분리 | |
| 맡길게요 | Claude가 적절히 판단 | ✓ |

**User's choice:** Claude 재량

---

## 프론트엔드 스택

| Option | Description | Selected |
|--------|-------------|----------|
| React + Vite (추천) | React 19 + Vite | ✓ |
| Next.js | SSR 포함 풀스택 | |

**User's choice:** React + Vite

| Option | Description | Selected |
|--------|-------------|----------|
| Tailwind CSS (추천) | 유틸리티 퍼스트 | ✓ |
| SCSS + BEM | CLAUDE.md 규칙 준수 | |

**User's choice:** Tailwind CSS

---

## DAG 시각화

| Option | Description | Selected |
|--------|-------------|----------|
| React Flow (추천) | 노드 기반 다이어그램 라이브러리 | ✓ |
| D3.js | 저수준 그래프 — 완전 커스텀 | |

**User's choice:** React Flow

---

## 디자인 스타일

| Option | Description | Selected |
|--------|-------------|----------|
| 다크 모드 (추천) | 어두운 배경 — 개발자 대시보드 스타일 | |
| 라이트 모드 | 밝은 배경 | |
| 둘 다 지원 | 다크/라이트 토글 | ✓ |

**User's choice:** 둘 다 지원

---

## Claude's Discretion

- 대시보드 레이아웃 구성
- 코드 구문 강조/마크다운 렌더링 라이브러리
- 로그 복구 메커니즘
- 상태 보드 업데이트 방식

## Deferred Ideas

없음
