# Phase 2: Orchestration & Workflow - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

사용자의 프로젝트 지시 하나로 Claude(팀장)가 기획자에게 방향을 제시하고, 기획자가 태스크 그래프를 구성하여 디자이너/개발자/QA에게 작업을 분배하며, QA가 단계별 검수를, Claude가 최종 검증과 보완 루프를 수행하여 실제 산출물이 만들어진다.

</domain>

<decisions>
## Implementation Decisions

### 에이전트 시스템 프롬프트
- **D-01:** 시스템 프롬프트 관리 방식은 Claude 재량 (파일 기반 또는 DB 등 적절한 방식)
- **D-02:** 각 에이전트(기획자, 디자이너, 개발자, QA) 프롬프트에 반드시 포함: 역할 정의, JSON 출력 형식 스키마, 다른 에이전트에게 요청하는 방법(협업 규칙), 금지 사항(역할 외 작업 등)
- **D-03:** 4개 에이전트 각각 독립된 시스템 프롬프트를 가지며, Ollama 호출 시 system 필드로 주입

### 오케스트레이션 흐름
- **D-04:** 사용자 지시 → Claude(팀장) 분석 → 항상 기획자에게 진행방향과 함께 전달. Claude는 작업자에게 직접 지시하지 않고 반드시 기획자를 경유한다.
- **D-05:** 기획자가 태스크 그래프(DAG)를 구성하여 의존성 기반으로 병렬/순차 작업을 자동 결정. 단, Gemma4 순차 실행 정책(Phase 1 INFR-03)에 따라 실제 실행은 큐를 통해 순차적.
- **D-06:** 구성원 간 자유 작업 요청 가능 — 개발자가 디자이너에게 직접 요청할 수 있지만, 모든 요청은 메시지 버스를 통하며 기획자가 전체 흐름을 추적한다.

### QA 검수 정책
- **D-07:** QA는 각 작업자의 작업 완료 시점에 검수를 수행한다 (디자이너 완료 → QA → 개발자 완료 → QA → 최종검증).
- **D-08:** QA는 원본 요구사항(기획자가 전달한 task_request의 요구사항)을 독립적으로 참조하여 검수. 작업 결과물만 보지 않고 요구사항 대비 검증.
- **D-09:** QA 불합격 시 구체적 문제점과 함께 해당 작업자에게 직접 반려(task_result로 fail + 이유 전달).

### 보완 루프
- **D-10:** Claude 최종 검증 후 불합격 시 보완 지시는 기획자를 경유하여 전달. 기획자가 판단하여 적절한 작업자에게 재배분.
- **D-11:** 최대 보완 반복 횟수는 Claude 재량으로 결정 (리서치에서 적절한 값 제안).
- **D-12:** 최대 반복 횟수 초과 시 사용자에게 에스컬레이션하여 결정을 요청.

### Claude's Discretion
- 시스템 프롬프트 저장 형태 (파일 vs DB)
- 태스크 그래프 구현 방식 (인메모리 vs SQLite)
- 최대 보완 반복 횟수 결정
- 에이전트 간 메시지 라우팅 구현 세부사항

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 구현체 (이 위에 구축)
- `server/bus/message_bus.py` — MessageBus (publish/consume/ack) — 에이전트 간 통신 기반
- `server/bus/schemas.py` — AgentMessage Pydantic 모델 — 메시지 스키마 정의
- `server/runners/claude_runner.py` — `run_claude_isolated()` — Claude CLI subprocess 호출
- `server/runners/ollama_runner.py` — OllamaRunner — Gemma4 순차 큐 러너
- `server/runners/json_parser.py` — 2-pass JSON 파서 — Gemma4 출력 복구
- `server/log_bus/event_bus.py` — EventBus — 실시간 이벤트 브로드캐스트
- `server/workspace/manager.py` — WorkspaceManager — 산출물 파일 저장

### Research
- `.planning/research/ARCHITECTURE.md` — Hub-Spoke 패턴, 에이전트 통신 구조
- `.planning/research/FEATURES.md` — 오케스트레이션 기능 요구사항, 자유 요청 패턴
- `.planning/research/PITFALLS.md` — QA 확증편향 방지, 에이전트 루프 방지

### Project
- `.planning/PROJECT.md` — 프로젝트 비전, 핵심 가치
- `.planning/REQUIREMENTS.md` — ORCH-01~05, WKFL-01~04 요구사항

### Prior Phase Context
- `.planning/phases/01-infra-foundation/01-CONTEXT.md` — Phase 1 결정사항 (서버 언어, 메시지 스키마, CLI 연동 등)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `MessageBus` — 에이전트 간 메시지 전달에 직접 사용
- `AgentMessage` — 기존 스키마에 오케스트레이션 필드 확장 가능
- `run_claude_isolated()` — Claude 팀장 호출에 직접 사용
- `OllamaRunner` — 기획자/디자이너/개발자/QA 호출에 사용
- `EventBus` — 오케스트레이션 이벤트를 대시보드에 전달
- `WorkspaceManager` — 에이전트 산출물 저장

### Established Patterns
- Pydantic 모델 기반 메시지 스키마
- asyncio.Queue 기반 순차 처리
- subprocess 기반 외부 프로세스 호출

### Integration Points
- `message_bus.publish()` / `consume()` — 에이전트 간 작업 요청/결과 전달
- `event_bus.publish()` — 오케스트레이션 상태 변경 이벤트 발행
- `workspace.write_artifact()` — 에이전트 산출물 저장

</code_context>

<specifics>
## Specific Ideas

- 기획자가 PM 역할 겸임 — 모든 에이전트 간 요청/결과를 추적하여 전체 워크플로우 상태를 유지
- QA는 작업 결과물만 보지 않고 원본 요구사항을 독립적으로 참조 (QA 확증편향 방지 — PITFALLS.md 참조)
- Gemma4 순차 실행 제약 하에서 태스크 그래프의 실행 순서 최적화

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-orchestration-workflow*
*Context gathered: 2026-04-03*
