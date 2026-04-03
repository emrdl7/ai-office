---
phase: 02-orchestration-workflow
plan: 05
subsystem: orchestration
tags: [gap-closure, agent-prompts, runtime-path, orch-02]
dependency_graph:
  requires: [02-01, 02-02, 02-03, 02-04]
  provides: [runtime-agent-prompts-complete, test-runtime-path-aligned]
  affects: [server/orchestration/loop.py, server/agents/]
tech_stack:
  added: []
  patterns: [agents-dir-single-source, test-runtime-path-alignment]
key_files:
  created: []
  modified:
    - server/agents/designer.md
    - server/agents/developer.md
    - server/agents/qa.md
    - server/orchestration/loop.py
decisions:
  - "loop.py AGENTS_DIR을 루트 agents/(4섹션 완비)로 통일 — 이중 관리 문제 근본 해소"
  - "server/agents/에도 협업 규칙 추가 — 디렉토리 자체가 올바른 문서로 유지"
metrics:
  duration: "1 minutes"
  completed_date: "2026-04-03T08:31:54Z"
  tasks_completed: 2
  files_modified: 4
requirements_fulfilled: [ORCH-02]
---

# Phase 2 Plan 5: Gap Closure — 런타임 경로 통합 및 협업 규칙 추가 Summary

런타임에서 로드하는 에이전트 프롬프트 경로(`server/agents/`)와 테스트가 검증하는 경로(루트 `agents/`)의 불일치를 해소하고, `server/agents/` 파일에 누락된 협업 규칙 섹션을 추가하여 ORCH-02 요건을 완전히 충족.

## Objective

VERIFICATION.md에서 발견된 구조적 갭 두 가지를 수정:
1. `server/agents/designer.md`, `developer.md`, `qa.md`에 `## 협업 규칙` 섹션 누락
2. `loop.py` AGENTS_DIR이 `server/agents/`(불완전)를 가리켜 테스트 경로(`agents/` 루트)와 불일치

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | server/agents/ 파일에 협업 규칙 섹션 추가 | c4003cf | server/agents/designer.md, developer.md, qa.md |
| 2 | loop.py AGENTS_DIR을 루트 agents/로 수정 | f8792bb | server/orchestration/loop.py |

## Changes Made

### Task 1: server/agents/ 협업 규칙 섹션 추가

**server/agents/designer.md** — `## 금지 사항` 앞에 삽입:
- 기획자로부터 `task_request` 메시지를 받아 작업 시작
- `task_result` 메시지로 결과 반환
- 메시지 버스를 통해 `task_request` 타입으로 개발자에게 명세 전달
- workspace 내 산출물 저장 + `artifact_paths` 명시
- `status_update`로 진행 상황 보고

**server/agents/developer.md** — `## 금지 사항` 앞에 삽입:
- 기획자 또는 디자이너로부터 `task_request` 메시지 수신
- `task_result` 메시지로 결과 반환
- WKFL-03 자유 요청 규칙 포함
- workspace 내 코드 저장 + `artifact_paths` 명시
- `status_update`로 진행 상황 보고

**server/agents/qa.md** — `## 금지 사항` 앞에 삽입:
- 기획자로부터 `task_request` 메시지(assigned_to: qa) 수신
- `task_result` 메시지로 검수 결과 반환
- 불합격 시 failure_reason에 구체적 사유 명시
- `status_update`로 진행 상황 보고

### Task 2: loop.py AGENTS_DIR 경로 수정

변경 전:
```python
# 에이전트 시스템 프롬프트 파일 디렉토리
AGENTS_DIR = Path(__file__).parent.parent / 'agents'  # → server/agents/
```

변경 후:
```python
# 에이전트 시스템 프롬프트 파일 디렉토리 (프로젝트 루트 agents/)
AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'  # → agents/ (루트)
```

이 변경으로:
- 런타임(loop.py)과 테스트(test_agents.py)가 동일한 경로(`agents/` 루트)를 참조
- 테스트 통과 = 런타임 품질 보장이라는 Nyquist 원칙 달성
- `agents/` 루트 파일은 이미 4섹션 완비 (역할 정의, JSON 출력, 협업 규칙, 금지사항)

## Verification Results

```
grep '## 협업 규칙' server/agents/designer.md server/agents/developer.md server/agents/qa.md
→ 3개 파일 모두 매칭

grep 'AGENTS_DIR' server/orchestration/loop.py
→ AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'

cd server && uv run pytest --tb=short -q
→ 57 passed, 17 warnings in 0.27s
```

## Deviations from Plan

None — 계획 그대로 실행.

## Known Stubs

없음. 모든 협업 규칙 섹션이 실제 메시지 버스 규칙으로 채워짐.

## Self-Check: PASSED

- [x] server/agents/designer.md 수정 확인
- [x] server/agents/developer.md 수정 확인
- [x] server/agents/qa.md 수정 확인
- [x] server/orchestration/loop.py 수정 확인
- [x] 커밋 c4003cf 존재 확인
- [x] 커밋 f8792bb 존재 확인
- [x] 57개 전체 테스트 통과 확인
- [x] ORCH-02 요건 충족 확인
