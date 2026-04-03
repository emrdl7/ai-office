---
phase: 2
slug: orchestration-workflow
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | server/pyproject.toml |
| **Quick run command** | `cd server && uv run pytest -x -q` |
| **Full suite command** | `cd server && uv run pytest --tb=short` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest -x -q`
- **After every plan wave:** Run `cd server && uv run pytest --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | ORCH-01 | integration | `uv run pytest tests/test_orchestration.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ORCH-02 | unit | `uv run pytest tests/test_agents.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ORCH-03 | unit | `uv run pytest tests/test_message_routing.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ORCH-04 | integration | `uv run pytest tests/test_revision_loop.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ORCH-05 | unit | `uv run pytest tests/test_sequential_queue.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | WKFL-01 | unit | `uv run pytest tests/test_task_graph.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | WKFL-02 | integration | `uv run pytest tests/test_qa_gate.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | WKFL-03 | unit | `uv run pytest tests/test_free_request.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | WKFL-04 | unit | `uv run pytest tests/test_planner_tracking.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_orchestration.py` — stubs for ORCH-01
- [ ] `server/tests/test_agents.py` — stubs for ORCH-02
- [ ] `server/tests/test_message_routing.py` — stubs for ORCH-03
- [ ] `server/tests/test_revision_loop.py` — stubs for ORCH-04
- [ ] `server/tests/test_task_graph.py` — stubs for WKFL-01
- [ ] `server/tests/test_qa_gate.py` — stubs for WKFL-02
- [ ] `server/tests/test_free_request.py` — stubs for WKFL-03
- [ ] `server/tests/test_planner_tracking.py` — stubs for WKFL-04

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Gemma4 시스템 프롬프트 준수 | ORCH-02 | 로컬 Ollama 필요 | 각 역할별 프롬프트로 Gemma4 호출, 출력 형식 확인 |
| Claude CLI 최종 검증 | ORCH-04 | 로컬 Claude CLI 필요 | 산출물 전달 후 pass/fail 응답 확인 |
| 전체 E2E 워크플로우 | All | 전체 시스템 연동 필요 | 사용자 지시 → 산출물 생성 완료까지 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
