---
phase: 01-infra-foundation
plan: 04
subsystem: runner
tags: [claude-cli, subprocess, token-isolation, tdd]
dependency_graph:
  requires: [01-01]
  provides: [run_claude_isolated, ClaudeRunnerError]
  affects: [orchestrator]
tech_stack:
  added: []
  patterns: [asyncio-subprocess, json-lines-parsing, isolated-cwd]
key_files:
  created: []
  modified:
    - server/runners/claude_runner.py
    - server/tests/test_claude_runner.py
decisions:
  - '--bare 플래그로 CLAUDE.md 자동 로드, MCP, 훅, 플러그인 비활성화 — 토큰 격리 달성'
  - '격리 디렉토리(/tmp/ai-office-claude-isolated)를 cwd로 사용하여 CLAUDE.md 자동 탐색 차단'
  - 'JSON-lines 스트림에서 type=assistant 이벤트만 추출, 파싱 불가 라인은 무시'
metrics:
  duration_minutes: 7
  completed_date: "2026-04-03T05:24:30Z"
  tasks_completed: 1
  files_modified: 2
requirements_satisfied: [INFR-02]
---

# Phase 01 Plan 04: Claude CLI Subprocess 격리 러너 Summary

**One-liner:** `--bare` + 격리 cwd 조합으로 CLAUDE.md/MCP 주입 없는 Claude CLI subprocess 러너를 asyncio 기반으로 구현

## What Was Built

`run_claude_isolated()` 비동기 함수를 구현했다. Claude CLI를 `asyncio.create_subprocess_exec`로 실행하며, `--bare`, `--print`, `--output-format stream-json`, `--no-session-persistence` 플래그로 토큰 격리를 달성한다. subprocess는 `/tmp/ai-office-claude-isolated` 격리 디렉토리에서 실행되어 프로젝트 루트의 CLAUDE.md가 자동으로 로드되는 것을 차단한다.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Claude CLI subprocess 러너 구현 (TDD) | 577541f | server/runners/claude_runner.py, server/tests/test_claude_runner.py |

## Test Results

```
tests/test_claude_runner.py::test_run_claude_returns_text PASSED
tests/test_claude_runner.py::test_bare_flag_in_subprocess_command PASSED
tests/test_claude_runner.py::test_isolation_dir_used_as_cwd PASSED
tests/test_claude_runner.py::test_failure_raises_claude_runner_error PASSED
tests/test_claude_runner.py::test_invalid_json_lines_ignored PASSED

5 passed in 0.01s
```

## Decisions Made

1. **토큰 격리 전략:** `--bare` 플래그 단독으로는 cwd의 CLAUDE.md를 차단할 수 없기 때문에, `/tmp/ai-office-claude-isolated` 격리 디렉토리를 cwd로 사용하여 이중 차단
2. **JSON-lines 파싱:** `type=assistant` 이벤트의 `message.content[]` 배열에서 `type=text` 블록만 추출. 파싱 불가 라인(스트림 메타데이터 등)은 `except json.JSONDecodeError: pass`로 무시
3. **에러 처리:** `returncode != 0`이면 stderr를 포함한 `ClaudeRunnerError`를 발생시켜 상위 오케스트레이터에서 처리 가능하게 설계

## Deviations from Plan

None — 계획서의 코드 스펙 그대로 구현됨.

## Known Stubs

None — `run_claude_isolated()`는 실제 구현 완료. 단, 실제 Claude CLI 호출은 로컬 환경 의존이므로 테스트에서 mock 사용.

## Self-Check: PASSED

- server/runners/claude_runner.py: FOUND, `--bare` 포함 확인
- server/tests/test_claude_runner.py: FOUND, 5개 테스트 PASSED 확인
- commit 577541f: FOUND
