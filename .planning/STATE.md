---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: v1.0 milestone complete
stopped_at: Phase 4 context gathered
last_updated: "2026-04-03T12:08:49.241Z"
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 15
  completed_plans: 20
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-03)

**Core value:** 사용자의 지시 하나로 AI 구성원들이 자율적으로 협업하여 실제 결과물(파일)을 만들어내는 것
**Current focus:** Phase 03 — agent-memory

## Current Position

Phase: 04
Plan: Not started

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01-infra-foundation P01 | 2 | 2 tasks | 30 files |
| Phase 01-infra-foundation P02 | 2 | 2 tasks | 3 files |
| Phase 01-infra-foundation P03 | 3 | 2 tasks | 4 files |
| Phase 01-infra-foundation P04 | 7 | 1 tasks | 2 files |
| Phase 01-infra-foundation P05 | 525580 | 1 tasks | 2 files |
| Phase 01-infra-foundation P06 | 12 | 2 tasks | 3 files |
| Phase 02-orchestration-workflow P01 | 8min | 3 tasks | 13 files |
| Phase 02-orchestration-workflow P02 | 2 | 2 tasks | 7 files |
| Phase 02-orchestration-workflow P03 | 4m | 1 tasks | 9 files |
| Phase 02-orchestration-workflow P04 | 8 | 2 tasks | 2 files |
| Phase 02-orchestration-workflow P05 | 1 | 2 tasks | 4 files |
| Phase 03-agent-memory P01 | 9min | 2 tasks | 3 files |
| Phase 03-agent-memory P02 | 3min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Init: Claude = CLI subprocess (판단·검증 전용), Gemma4 = Ollama 로컬 (실무 에이전트)
- Init: 기획자가 PM 겸임 — 에이전트 간 자유 요청을 허용하되 전체 흐름 추적
- Init: SQLite WAL 모드가 메시지 버스 + 상태 저장소 모두 담당
- Init: Hub-Spoke Orchestration 패턴 — 에이전트 간 직접 통신 금지, 서버 경유 필수
- [Phase 01-infra-foundation]: uv init으로 server/를 독립 Python 서브프로젝트로 초기화 — pyproject.toml 기반 의존성 관리
- [Phase 01-infra-foundation]: AgentMessage에 Pydantic alias 사용 (from_agent/to_agent) — Python 예약어 from/to 충돌 우회
- [Phase 01-infra-foundation]: xfail(strict=False) 패턴으로 stub 테스트 선언 — Wave 0 Nyquist 원칙
- [Phase 01-infra-foundation]: 절대 임포트 사용: server/는 __init__.py 없는 네임스페이스라 상대 임포트 금지, from db.client import로 통일
- [Phase 01-infra-foundation]: WAL 모드는 파일 기반 DB 전용: :memory: DB는 WAL 미지원이므로 테스트는 tmp_path 기반 파일 DB 사용
- [Phase 01-infra-foundation]: workspace_root 파라미터로 테스트 격리 — WorkspaceManager 생성자에 주입 가능
- [Phase 01-infra-foundation]: safe_path에서 resolve()+startswith() 조합 — 심볼릭 링크 우회 방지
- [Phase 01-infra-foundation]: 2-pass JSON 파서에서 rfind 사용 — 중첩 JSON의 마지막 닫는 괄호 정확히 선택
- [Phase 01-infra-foundation]: asyncio.Queue 단일 워커로 동시 Ollama 요청을 직렬화 — gemma4:26b 메모리 스래싱 방지
- [Phase 01-infra-foundation]: generate_json()을 OllamaRunner에 포함 — parse_json() 파이프라인 통합 제공
- [Phase 01-infra-foundation]: asyncio.Queue 기반 in-process 이벤트 버스: 폴링 없이 즉시 WebSocket 팬아웃, SQLite 브릿지 불필요
- [Phase 01-infra-foundation]: QueueFull 예외 무시: 느린 클라이언트 드롭으로 버스 블록 방지
- [Phase 02-orchestration-workflow]: 에이전트 시스템 프롬프트를 agents/*.md 파일로 관리 — OllamaRunner system 파라미터로 주입
- [Phase 02-orchestration-workflow]: TaskRequestPayload.requirements 필드로 원본 요구사항 전문 포함 — QA 독립 참조(D-08) 구조적 보장
- [Phase 02-orchestration-workflow]: TaskResultPayload.failure_reason Optional[str] — QA 불합격 시 구체적 사유 전달(D-09)
- [Phase 02-orchestration-workflow]: TaskNode.requirements 필드를 TaskRequestPayload에서 그대로 복사 — QA 독립 참조(D-08)를 DAG 레벨에서도 보장
- [Phase 02-orchestration-workflow]: MessageRouter route()에서 to_agent=planner/broadcast이면 복사 생략 — 기획자 중복 메시지 방지
- [Phase 02-orchestration-workflow]: mock patch 대상을 orchestration.loop.run_claude_isolated로 변경 — 직접 임포트된 함수는 임포트된 모듈 네임스페이스에서 패치해야 함
- [Phase 02-orchestration-workflow]: agents/ 디렉토리에 .md 파일로 시스템 프롬프트 관리 (D-01, D-03) — planner/developer/designer/qa.md 4개 파일
- [Phase 02-orchestration-workflow]: asyncio.create_task 사용: OrchestrationLoop.run()이 async라서 FastAPI BackgroundTasks 대신 asyncio.create_task 선택
- [Phase 02-orchestration-workflow]: WorkspaceManager(task_id='', workspace_root='workspace'): task_id='' 로 workspace 루트 전체를 loop가 sub-path로 사용
- [Phase 02-orchestration-workflow]: loop.py AGENTS_DIR을 루트 agents/(4섹션 완비)로 통일 — 이중 관리 문제 근본 해소
- [Phase 02-orchestration-workflow]: server/agents/에도 협업 규칙 추가 — 디렉토리 자체가 올바른 문서로 유지
- [Phase 03-agent-memory]: memory_root 파라미터로 AgentMemory 테스트 격리 — WorkspaceManager의 workspace_root 패턴 답습
- [Phase 03-agent-memory]: WorkspaceManager 재사용하지 않음 — task_id 기반 경로 로직이 에이전트 메모리 단일 파일 패턴과 미적합
- [Phase 03-agent-memory]: MAX_DETAIL_COUNT=20, keep_count=10(절반) — D-07 재량값; 규칙 기반 요약(성공/실패 건수+상위 태그)
- [Phase 03-agent-memory]: AgentMemory를 memory_root 주입으로 테스트 격리 — OrchestrationLoop 생성자에 memory_root 파라미터 추가
- [Phase 03-agent-memory]: patch 대상: 'orchestration.loop.AgentMemory' — 직접 임포트된 네임스페이스에서 패치해야 mock 동작

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2 진입 전: Orchestration Server 언어 선택(Python/FastAPI vs. Node.js/TypeScript) 확정 필요
- Phase 2 초반: Gemma4 e4b의 `format: json` 파싱 실패율 실제 벤치마크 필요
- Phase 1: OLLAMA_NUM_PARALLEL 로컬 하드웨어 한계 측정 후 Phase 2 에이전트 큐 설계 확정

## Session Continuity

Last session: 2026-04-03T09:43:18.084Z
Stopped at: Phase 4 context gathered
Resume file: .planning/phases/04-web-dashboard/04-CONTEXT.md
