---
phase: 1
slug: infra-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | server/pyproject.toml (Wave 0 creates) |
| **Quick run command** | `cd server && uv run pytest -x -q` |
| **Full suite command** | `cd server && uv run pytest --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest -x -q`
- **After every plan wave:** Run `cd server && uv run pytest --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | INFR-01 | unit | `uv run pytest tests/test_message_bus.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | INFR-02 | integration | `uv run pytest tests/test_claude_runner.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | INFR-03 | integration | `uv run pytest tests/test_ollama_runner.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | INFR-04 | unit | `uv run pytest tests/test_log_bus.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | INFR-05 | unit | `uv run pytest tests/test_json_parser.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ARTF-01 | unit | `uv run pytest tests/test_workspace.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ARTF-02 | unit | `uv run pytest tests/test_workspace.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/conftest.py` — shared fixtures (SQLite in-memory DB, temp workspace dirs)
- [ ] `server/tests/test_message_bus.py` — stubs for INFR-01
- [ ] `server/tests/test_claude_runner.py` — stubs for INFR-02
- [ ] `server/tests/test_ollama_runner.py` — stubs for INFR-03
- [ ] `server/tests/test_log_bus.py` — stubs for INFR-04
- [ ] `server/tests/test_json_parser.py` — stubs for INFR-05
- [ ] `server/tests/test_workspace.py` — stubs for ARTF-01, ARTF-02
- [ ] `pytest`, `pytest-asyncio` — install via uv

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Ollama/Gemma4 응답 | INFR-03 | 로컬 Ollama 인스턴스 필요 | `ollama run gemma4` 후 HTTP 요청 전송 확인 |
| Claude CLI subprocess | INFR-02 | 로컬 Claude CLI 설치 필요 | `echo 'test' \| claude --bare --print` 실행 확인 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
