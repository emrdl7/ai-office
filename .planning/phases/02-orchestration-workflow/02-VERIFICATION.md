---
phase: 02-orchestration-workflow
verified: 2026-04-03T08:45:00Z
status: human_needed
score: 5/5 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 4/5
  gaps_closed:
    - "기획자, 디자이너, 개발자, QA 4개 에이전트가 각각 독립된 시스템 프롬프트로 실행된다 — loop.py AGENTS_DIR이 루트 agents/(4섹션 완비)를 가리키도록 수정되고, server/agents/에도 협업 규칙 섹션이 추가됨"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "uv run uvicorn main:app --reload 서버 기동 후 curl -X POST /api/tasks -H 'Content-Type: application/json' -d '{\"instruction\": \"간단한 홈페이지 만들어줘\"}' 실행"
    expected: "{\"task_id\": \"...\", \"status\": \"accepted\"} 202 응답 반환"
    why_human: "실제 Ollama + gemma4 모델 + Claude CLI 환경이 필요한 E2E 흐름은 자동화로 검증 불가"
  - test: "OrchestrationLoop.run() 전체 흐름 — IDLE → CLAUDE_ANALYZING → PLANNER_PLANNING → WORKER_EXECUTING → QA_REVIEWING → CLAUDE_FINAL_VERIFYING → COMPLETED 상태 순서 확인"
    expected: "각 상태 전이 시 event_bus에 status_change 이벤트가 순서대로 발행되어 /ws/logs WebSocket으로 수신됨"
    why_human: "실제 AI 응답 품질 및 상태 전이 순서는 mock 테스트로 검증 불가"
---

# Phase 2: Orchestration & Workflow 검증 보고서

**Phase Goal:** 사용자의 프로젝트 지시 하나로 4개 에이전트가 순차 실행되어 실제 산출물을 만들고 Claude가 최종 검증까지 완료할 수 있다
**Verified:** 2026-04-03T08:45:00Z
**Status:** human_needed
**Re-verification:** Yes — 갭 클로저 플랜 02-05 적용 후 재검증

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria 기준)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | Claude CLI가 사용자 지시를 분석하여 기획자에게 구조화된 지시(task_request)를 전달하고, 기획자가 PM으로서 전체 태스크 상태를 추적한다 | ✓ VERIFIED | loop.py analyze_instruction()이 run_claude_isolated() 호출 후 to_agent='planner' AgentMessage 발행; test_orchestration.py 2개 PASSED |
| 2   | 4개 에이전트가 각각 독립된 시스템 프롬프트로 실행되며, 에이전트 간 모든 통신이 JSON 메시지 스키마를 따른다 | ✓ VERIFIED | loop.py AGENTS_DIR이 루트 agents/(4섹션 완비)를 가리키도록 수정됨. 런타임·테스트 경로 일치 확인. 57개 전체 테스트 통과 |
| 3   | 구성원이 다른 구성원에게 작업 요청 가능하며, 기획자가 모든 요청/결과를 추적한다 | ✓ VERIFIED | MessageRouter.route()가 is_broadcast_copy: True 메타데이터로 planner에게 broadcast 복사 자동 발행; test_free_request.py, test_planner_tracking.py PASSED |
| 4   | QA 에이전트가 원본 요구사항 대비 검수를 수행하고 합격/불합격 결과를 기록한다 | ✓ VERIFIED | _run_qa_gate()가 [원본 요구사항]{node.requirements} 프롬프트 패턴으로 node.failure_reason 기록; test_qa_gate.py 2개 PASSED |
| 5   | Claude가 최종 산출물을 검증하여 합격 또는 구체적 보완 사항과 함께 재지시하며, Gemma4 에이전트는 순차 큐로만 실행된다 | ✓ VERIFIED | _claude_final_verify() PASS/FAIL 분기, MAX_REVISION_ROUNDS=3, ESCALATED 상태; OllamaRunner asyncio.Queue 단일 워커 확인 |

**Score:** 5/5 success criteria verified

---

## Re-verification: Gap Closure Confirmation

### Gap Closed: AGENTS_DIR 경로 불일치 (ORCH-02)

**이전 상태 (초기 검증):**
- `loop.py` line 19: `AGENTS_DIR = Path(__file__).parent.parent / 'agents'` → `server/agents/` (불완전)
- `test_agents.py` line 5: `AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'` → `agents/` (루트, 완비)
- `server/agents/designer.md`, `developer.md`에 `## 협업 규칙` 섹션 누락

**수정 후 상태 (02-05 적용):**
- `loop.py` line 19: `AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'` → `agents/` (루트, 4섹션 완비)
- 두 경로가 `/Users/johyeonchang/ai-office/agents`로 동일하게 해석됨 (python3으로 직접 확인)
- `server/agents/designer.md`, `developer.md`, `qa.md` 모두 `## 협업 규칙` 섹션 추가됨

**검증 증거:**
- `grep -n 'AGENTS_DIR' server/orchestration/loop.py` → `AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'`
- `grep -n '협업 규칙' server/agents/designer.md server/agents/developer.md server/agents/qa.md` → 3개 파일 모두 매칭
- `grep -n 'task_request' server/agents/designer.md` → 메시지 버스 규칙 포함 확인 (line 22, 24)
- `grep -n 'WKFL-03' server/agents/developer.md` → line 24에서 확인
- 전체 테스트: `57 passed, 17 warnings in 0.19s`

---

## Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/bus/payloads.py` | TaskRequestPayload, TaskResultPayload, StatusUpdatePayload Pydantic 모델 | ✓ VERIFIED | 3개 모델 정의, requirements/failure_reason 필드 포함 |
| `agents/planner.md` | 기획자 시스템 프롬프트 — 역할정의, JSON출력, 협업규칙, 금지사항 4섹션 | ✓ VERIFIED | 루트 agents/에 4섹션 완비 |
| `agents/designer.md` | 디자이너 시스템 프롬프트 — 4섹션 | ✓ VERIFIED | 루트 agents/에 4섹션 완비, loop.py 런타임이 이 파일 로드 |
| `agents/developer.md` | 개발자 시스템 프롬프트 — 4섹션 | ✓ VERIFIED | 루트 agents/에 4섹션 완비, loop.py 런타임이 이 파일 로드 |
| `agents/qa.md` | QA 시스템 프롬프트 — 원본 요구사항 독립 참조 규칙 포함 | ✓ VERIFIED | 루트 agents/에 '원본 요구사항', '확증편향' 키워드 포함 |
| `server/agents/designer.md` | 런타임 백업 파일 (server/agents/ 디렉토리 정합성 유지) | ✓ VERIFIED | 협업 규칙 섹션 추가 완료 (line 21) |
| `server/agents/developer.md` | 런타임 백업 파일 (server/agents/ 디렉토리 정합성 유지) | ✓ VERIFIED | 협업 규칙 섹션 추가 완료 (line 21) |
| `server/orchestration/__init__.py` | 모듈 진입점 | ✓ VERIFIED | 파일 존재 |
| `server/orchestration/task_graph.py` | TaskGraph, TaskNode, TaskStatus 클래스 | ✓ VERIFIED | add_task, update_status, ready_tasks, all_done, to_state_dict 구현; test_task_graph.py 4개 PASSED |
| `server/orchestration/router.py` | MessageRouter 클래스 — 라우팅 + broadcast 복사 | ✓ VERIFIED | route() 원본 + planner 복사 발행, is_broadcast_copy 메타데이터 포함 |
| `server/orchestration/loop.py` | OrchestrationLoop + WorkflowState — 상태 머신, AGENTS_DIR 루트 경로 | ✓ VERIFIED | AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents' (루트), 9개 WorkflowState, MAX_REVISION_ROUNDS=3 |
| `server/main.py` | POST /api/tasks + GET /api/tasks/{task_id} 엔드포인트 | ✓ VERIFIED | /health, /api/tasks, /api/tasks/{task_id}, /ws/logs 라우트 확인 |

---

## Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `server/orchestration/loop.py` | `agents/*.md` (루트) | `AGENTS_DIR / f"{agent}.md"` 파일 읽기 | ✓ WIRED | AGENTS_DIR이 루트 agents/를 가리킴, 경로 해석 python3으로 직접 확인 |
| `server/orchestration/task_graph.py` | `server/bus/payloads.py` | `from bus.payloads import` | ✓ WIRED | line 6 확인 |
| `server/orchestration/router.py` | `server/bus/message_bus.py` | `bus.publish()` 호출 | ✓ WIRED | line 37, 46 — 원본 + 복사 각각 publish() |
| `server/orchestration/loop.py` | `server/runners/claude_runner.py` | `run_claude_isolated()` 호출 | ✓ WIRED | line 316, 354 — analyze_instruction, _claude_final_verify에서 호출 |
| `server/orchestration/loop.py` | `server/runners/ollama_runner.py` | `generate_json()` 호출 | ✓ WIRED | line 171, 201, 275 — _run_planner, _run_agent, _run_qa_gate에서 호출 |
| `server/orchestration/loop.py` | `server/orchestration/router.py` | `router.route()` 호출 | ✓ WIRED | line 363 — analyze_instruction에서 호출 |
| `server/orchestration/loop.py` | `server/orchestration/task_graph.py` | `task_graph.` 상태 업데이트 | ✓ WIRED | line 115, 119, 129, 135, 138, 182 등 |
| `server/main.py` | `server/orchestration/loop.py` | OrchestrationLoop 싱글턴 + asyncio.create_task | ✓ WIRED | line 40 OrchestrationLoop 생성, line 86 asyncio.create_task |
| `server/main.py` | `server/bus/message_bus.py` | MessageBus 인스턴스 lifespan 생성 | ✓ WIRED | line 26 `MessageBus(db_path='data/bus.db')` |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `loop.py::analyze_instruction` | AgentMessage payload | `run_claude_isolated(prompt)` 반환값 | Claude CLI subprocess 실행 — 실제 AI 응답 반환 | ✓ FLOWING (mock 테스트 기준) |
| `loop.py::_run_qa_gate` | node.requirements | TaskRequestPayload.requirements 필드 | task_graph.add_task(payload)에서 원본 requirements 보존 | ✓ FLOWING |
| `loop.py::_run_agent` | system_prompt | `_load_agent_prompt(node.assigned_to)` | 루트 agents/{agent}.md 파일 read — 4섹션 완비 파일 로드 | ✓ FLOWING |
| `main.py::create_task` | task_id 상태 | `loop.run()` 반환 WorkflowState | asyncio.create_task로 백그라운드 실행 후 active_tasks 업데이트 | ✓ FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| main.py 임포트 및 라우트 확인 | `uv run python -c "from main import app; ..."` | /health, /api/tasks, /api/tasks/{task_id}, /ws/logs 확인 | ✓ PASS |
| Payloads Pydantic 모델 import + 인스턴스 생성 | `uv run python -c "from bus.payloads import TaskRequestPayload; ..."` | UUID 출력 확인 | ✓ PASS |
| loop.py AGENTS_DIR 경로 수정 확인 | `grep 'AGENTS_DIR' server/orchestration/loop.py` | `parent.parent.parent / 'agents'` (루트 경로) | ✓ PASS |
| 런타임 경로 == 테스트 경로 확인 | python3 경로 해석 직접 실행 | 둘 다 `/Users/johyeonchang/ai-office/agents` | ✓ PASS |
| server/agents/ 협업 규칙 섹션 | `grep '협업 규칙' server/agents/designer.md developer.md qa.md` | 3개 파일 모두 매칭 | ✓ PASS |
| task_request 메시지 버스 규칙 | `grep 'task_request' server/agents/designer.md` | line 22, 24 확인 | ✓ PASS |
| WKFL-03 자유 요청 규칙 | `grep 'WKFL-03' server/agents/developer.md` | line 24 확인 | ✓ PASS |
| Phase 2 테스트 전체 | `cd server && uv run pytest -q` | 57 passed, 17 warnings | ✓ PASS |
| E2E curl POST /api/tasks | 실제 서버 기동 필요 | 실행 불가 (Ollama 미가동) | ? SKIP (human needed) |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| ORCH-01 | 02-03, 02-04 | Claude CLI가 사용자 지시를 분석하고 기획자에게 전달 | ✓ SATISFIED | analyze_instruction() → to_agent='planner'; test_orchestration.py PASSED |
| ORCH-02 | 02-01, 02-04, 02-05 | 4개 에이전트 각각 독립 역할 + 시스템 프롬프트 | ✓ SATISFIED | loop.py AGENTS_DIR이 루트 agents/(4섹션 완비)를 가리킴; server/agents/에도 협업 규칙 추가; 57 passed |
| ORCH-03 | 02-01, 02-02 | 에이전트 간 통신 JSON 스키마(task_request, task_result, status_update) | ✓ SATISFIED | payloads.py 3개 Pydantic 모델; test_message_routing.py PASSED |
| ORCH-04 | 02-03 | Claude 최종 검증 + 불합격 시 보완 재지시 | ✓ SATISFIED | _claude_final_verify() PASS/FAIL 분기, REVISION_LOOPING → PLANNER_PLANNING 재진입; test_revision_loop.py PASSED |
| ORCH-05 | 02-02 | Gemma4 에이전트 순차 실행 + 큐 기반 정책 | ✓ SATISFIED | OllamaRunner asyncio.Queue 단일 워커 확인; TaskGraph ready_tasks() 순차 처리 |
| WKFL-01 | 02-02 | 기획자 PM으로 전체 태스크 상태 추적 | ✓ SATISFIED | TaskGraph(PENDING/PROCESSING/DONE/FAILED/BLOCKED); test_task_graph.py 4개 PASSED |
| WKFL-02 | 02-03 | QA 에이전트 원본 요구사항 대비 검수 | ✓ SATISFIED | _run_qa_gate() [원본 요구사항] 프롬프트 패턴; test_qa_gate.py PASSED |
| WKFL-03 | 02-02 | 구성원 간 자유 요청 가능 | ✓ SATISFIED | MessageRouter developer→designer 라우팅 지원; test_free_request.py PASSED |
| WKFL-04 | 02-02 | 기획자 모든 요청/결과 추적 | ✓ SATISFIED | MessageRouter broadcast 복사 planner에게 자동 발행; test_planner_tracking.py PASSED |

**Note:** WKFL-05는 Phase 4 범위로 Phase 2에 미해당.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/orchestration/loop.py` | 235–236 | workspace 저장 실패 시 `pass` — 산출물 저장 오류 무음 처리 | ℹ Info | 기능 차단은 아니지만 산출물 저장 오류를 무시하여 디버깅 어려움 |
| `server/tests/test_planner_tracking.py` | — | `test_planner_tracks_all_task_states` 테스트 미구현 (2개만 존재) | ℹ Info | WKFL-04 커버리지 부분 누락이지만 핵심 동작은 test_planner_receives_broadcast_copy로 검증됨 |

*이전 검증에서 지적된 AGENTS_DIR 경로 불일치 경고(⚠) 및 server/agents/ 협업 규칙 누락 경고(⚠)는 02-05 갭 클로저로 해소됨.*

---

## Human Verification Required

### 1. E2E 오케스트레이션 실행

**Test:** `uvicorn main:app --reload` 기동 후 `curl -X POST http://localhost:8000/api/tasks -H 'Content-Type: application/json' -d '{"instruction": "간단한 홈페이지 만들어줘"}'`
**Expected:** `{"task_id": "...", "status": "accepted"}` 202 응답, /ws/logs WebSocket에서 상태 전이 이벤트 순서 확인 (CLAUDE_ANALYZING → PLANNER_PLANNING → WORKER_EXECUTING → QA_REVIEWING → CLAUDE_FINAL_VERIFYING → COMPLETED)
**Why human:** Ollama + gemma4 모델 + Claude CLI 실제 환경이 필요하며 AI 응답 품질은 자동화 불가

### 2. Claude 최종 검증 보완 루프 실제 동작

**Test:** Claude가 FAIL 응답을 반환하는 시나리오에서 revision_count 증가 및 PLANNER_PLANNING 재진입 확인
**Expected:** revision_count가 3에 도달하면 WorkflowState.ESCALATED로 전환되어 루프 종료
**Why human:** mock 테스트에서는 검증되었으나 실제 Claude 응답 패턴("PASS"/"FAIL" 포함 여부)에 따라 동작이 달라질 수 있음

---

## Gaps Summary

갭이 해소되었다. 02-05 플랜이 두 가지 수정을 완료했다.

1. **loop.py AGENTS_DIR 경로 수정** — `parent.parent / 'agents'`(server/agents/, 불완전)에서 `parent.parent.parent / 'agents'`(루트 agents/, 4섹션 완비)로 변경. 런타임과 테스트가 동일한 경로를 참조하여 "테스트 통과 = 런타임 품질 보장" 원칙이 성립한다.

2. **server/agents/ 협업 규칙 섹션 추가** — designer.md, developer.md, qa.md에 `## 협업 규칙` 섹션 삽입. 디렉토리 자체도 올바른 문서로 유지된다.

57개 전체 테스트가 수정 후에도 통과(회귀 없음)하며, 9개 요건(ORCH-01~05, WKFL-01~04) 모두 SATISFIED 상태다. 잔여 human_needed 항목 2건은 실제 Ollama + Claude CLI 환경이 필요한 E2E 시나리오로, 자동화 검증 범위 밖이다.

---

_Verified: 2026-04-03T08:45:00Z_
_Verifier: Claude (gsd-verifier)_
