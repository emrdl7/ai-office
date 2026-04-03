# Phase 3: Agent Memory - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

에이전트별 프로젝트 단위 경험을 저장하고, 다음 작업 시 시스템 프롬프트에 주입하여 품질을 점진적으로 개선한다. Claude 보완 지시와 QA 피드백이 즉시 경험 기록에 반영된다. 경험이 쌓이면 건수 기반 압축으로 프롬프트 크기를 관리한다.

</domain>

<decisions>
## Implementation Decisions

### 경험 저장 형식
- **D-01:** 에이전트별 JSON 파일로 경험을 저장한다 (예: `data/memory/planner_memory.json`, `designer_memory.json` 등). 프로젝트 단위로 관리.
- **D-02:** 경험 레코드는 구조화된 JSON 객체 — 태스크 ID, 성공/실패 여부, 피드백 내용, 패턴 태그, 타임스탬프 등을 포함.

### 경험 참조 방식
- **D-03:** 작업 시작 시 해당 에이전트의 경험 파일을 읽어 관련 경험을 시스템 프롬프트에 주입한다. Ollama 호출의 system 필드에 기본 프롬프트 + 경험 요약을 결합.
- **D-04:** 프롬프트 크기 제한을 위해 가장 관련성 높은 경험만 선별하여 주입 (태스크 유형 매칭 등).

### 피드백 반영
- **D-05:** QA 불합격 또는 Claude 보완 지시가 발생하는 시점에 즉시 해당 에이전트의 경험 파일에 추가한다. 워크플로우 종료까지 기다리지 않음.
- **D-06:** OrchestrationLoop의 QA 검수 결과와 Claude 최종 검증 결과를 경험 기록 트리거로 연결.

### 경험 압축
- **D-07:** 건수 기반 압축 정책 — 최근 N건의 상세 경험만 유지하고, 나머지는 요약본으로 압축. N값과 요약 방식은 Claude 재량.
- **D-08:** 압축은 경험 파일 읽기 시점에 자동 실행 (lazy compaction).

### Claude's Discretion
- 경험 레코드의 정확한 JSON 스키마
- 관련 경험 선별 알고리즘 (태스크 유형 매칭, 최근성 등)
- 압축 시 유지할 최근 N건의 구체적 값
- 요약 방식 (LLM 요약 vs 규칙 기반)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 2 구현체 (이 위에 구축)
- `server/orchestration/loop.py` — OrchestrationLoop: QA 검수 결과, Claude 최종 검증 결과가 경험 저장 트리거
- `server/runners/ollama_runner.py` — OllamaRunner.generate_json(system=) — 경험을 프롬프트에 주입하는 진입점
- `agents/*.md` — 에이전트 시스템 프롬프트 — 경험이 여기에 추가됨

### Phase 1 구현체
- `server/workspace/manager.py` — WorkspaceManager atomic write — 경험 파일 저장에 활용 가능
- `server/runners/json_parser.py` — JSON 파싱 — 경험 파일 읽기에 활용

### Project
- `.planning/PROJECT.md` — 프로젝트 비전
- `.planning/REQUIREMENTS.md` — AMEM-01~03 요구사항

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `WorkspaceManager.write_artifact()` — atomic write 패턴을 경험 파일 저장에 재사용 가능
- `OllamaRunner.generate_json(system=)` — 시스템 프롬프트에 경험 주입하는 인터페이스 이미 존재
- `json_parser.parse_json()` — 경험 파일 파싱에 활용

### Established Patterns
- `agents/*.md` 파일 기반 시스템 프롬프트 관리
- `data/` 디렉토리가 이미 존재 (Phase 1에서 생성)

### Integration Points
- `OrchestrationLoop._run_qa_gate()` — QA 결과를 경험으로 기록
- `OrchestrationLoop._claude_final_verify()` — Claude 검증 결과를 경험으로 기록
- `OrchestrationLoop._dispatch_to_worker()` — 작업 시작 시 경험 로드 + 프롬프트 주입

</code_context>

<specifics>
## Specific Ideas

- 경험 파일은 `data/memory/` 디렉토리에 에이전트별로 저장
- 압축은 파일 로드 시 lazy하게 수행 — 별도 배치 프로세스 불필요
- 성공 패턴과 실패 패턴을 구분하여 저장 — "이렇게 하면 성공", "이건 피해야 함"

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-agent-memory*
*Context gathered: 2026-04-03*
