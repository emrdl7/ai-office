---
phase: 01-infra-foundation
plan: "03"
subsystem: infra
tags: [workspace, atomic-write, json-parser, gemma4, path-traversal, security]

requires:
  - phase: 01-infra-foundation
    plan: "01"
    provides: Python 서버 uv 프로젝트 scaffold, conftest.py의 tmp_workspace fixture

provides:
  - WorkspaceManager 클래스 — write_artifact, safe_path, artifact_type, list_artifacts
  - tmp+rename atomic write 패턴으로 부분 파일 방지
  - 경로 순회 공격 차단 (safe_path)
  - parse_json() 2-pass 파싱 전략 (strict → fence/extract/trailing-comma repair)
  - ARTF-01, ARTF-02, INFR-05 요구사항 충족

affects:
  - 에이전트 산출물 저장 로직 모든 플랜
  - Gemma4 JSON 응답 파싱 로직 모든 플랜
  - OrchestratorServer — WorkspaceManager 사용

tech-stack:
  added: []
  patterns:
    - "tmp+rename atomic write — os.rename으로 원자적 파일 교체, 실패 시 .tmp 정리"
    - "safe_path() — resolve()로 실제 경로 확인 후 prefix 검사로 경로 순회 차단"
    - "2-pass JSON 파싱 — strict 실패 시 fence/extract/trailing-comma repair 순서 시도"
    - "SUPPORTED_EXTENSIONS 레지스트리 — 확장자 타입 분류 역방향 조회"

key-files:
  created:
    - server/runners/json_parser.py
  modified:
    - server/workspace/manager.py
    - server/tests/test_workspace.py
    - server/tests/test_json_parser.py

key-decisions:
  - "workspace_root 파라미터를 생성자에 추가 — 테스트 격리를 위해 tmp_path 주입 가능하도록"
  - "safe_path에서 resolve() + startswith() 조합 사용 — 심볼릭 링크 우회 방지"
  - "2-pass JSON 파서에서 객체/배열 추출 시 rfind로 마지막 닫는 괄호 사용 — 중첩 JSON 대응"

patterns-established:
  - "TDD: 테스트 먼저 작성(RED) → 구현(GREEN) 순서 준수"
  - "atomic write: tmp+rename 패턴을 모든 파일 쓰기에 적용"
  - "security: 외부 입력 경로는 반드시 safe_path()를 통해 검증"

requirements-completed:
  - ARTF-01
  - ARTF-02
  - INFR-05

duration: 3min
completed: "2026-04-03"
---

# Phase 01 Plan 03: WorkspaceManager + JSON Parser Summary

**WorkspaceManager로 태스크별 격리 atomic write 구현, Gemma4 JSON 불안정 대응 2-pass 파서 추가 — 15개 테스트 전부 PASSED**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-03T05:18:44Z
- **Completed:** 2026-04-03T05:21:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- WorkspaceManager: tmp+rename atomic write + safe_path 경로 순회 차단 + 다중 파일 형식 지원
- parse_json(): 2-pass 전략으로 Gemma4 비정형 JSON 출력 복구 (마크다운 펜스, 후행 쉼표, 전/후치 텍스트)
- 7 + 8 = 15개 테스트 전부 PASSED, xfail 마커 없음

## Task Commits

각 태스크를 원자적으로 커밋:

1. **Task 1: WorkspaceManager atomic write + 경로 검증** - `a517602` (feat)
2. **Task 2: Gemma4 JSON 2-pass 파싱+복구 전략** - `c8f61c1` (feat)

## Files Created/Modified

- `server/workspace/manager.py` - WorkspaceManager 클래스 (atomic write, 경로 검증, 타입 분류)
- `server/tests/test_workspace.py` - ARTF-01/02 검증 테스트 7개
- `server/runners/json_parser.py` - parse_json() 2-pass 파싱 전략 (신규 생성)
- `server/tests/test_json_parser.py` - INFR-05 검증 테스트 8개

## Decisions Made

- `workspace_root` 파라미터를 생성자에 추가: 테스트에서 `tmp_path` 주입으로 격리 보장
- `safe_path`에서 `resolve() + startswith()` 조합: 심볼릭 링크 우회 공격도 방지
- JSON 추출 시 `rfind` 사용: 중첩 JSON 구조에서 마지막 닫는 괄호를 올바르게 선택

## Deviations from Plan

None - 플랜에 명시된 코드를 정확히 구현했으며 추가 수정 없음.

## Issues Encountered

- 최초 파일 쓰기 시 worktree 경로가 아닌 메인 레포 경로에 파일을 작성한 오류 발생. worktree 절대 경로(`/Users/johyeonchang/ai-office/.claude/worktrees/agent-a82d25b2/server/`)로 재작성하여 해결.

## Known Stubs

없음 — 모든 구현이 실제 동작하며 테스트로 검증됨.

## Next Phase Readiness

- WorkspaceManager는 에이전트 산출물 저장 로직에 즉시 사용 가능
- parse_json()은 Gemma4 응답 처리 로직에 즉시 사용 가능
- 두 모듈 모두 독립적으로 import 가능하며 외부 의존성 없음

---
*Phase: 01-infra-foundation*
*Completed: 2026-04-03*
