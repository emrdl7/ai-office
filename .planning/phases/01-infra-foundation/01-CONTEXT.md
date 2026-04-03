# Phase 1: Infra Foundation - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

모든 에이전트와 서버가 의존하는 로컬 인프라를 구축한다: SQLite WAL 메시지 버스, 상태 저장소, Claude CLI subprocess 러너, Ollama/Gemma4 러너, 로그 버스(WebSocket 브로드캐스트), 산출물 파일 시스템(태스크별 격리 디렉토리).

</domain>

<decisions>
## Implementation Decisions

### 서버 언어
- **D-01:** Python (FastAPI)을 오케스트레이션 서버 언어로 사용한다. Ollama Python SDK, CrewAI 생태계와 직접 연결되며 AI 에이전트 관리에 강점이 있다.

### 메시지 스키마
- **D-02:** 에이전트 간 메시지 스키마를 풍부하게 설계한다. 필수 필드(type, from, to, payload, reply_to) 외에 priority, tags, metadata, ack_at, created_at, status 등을 초기부터 정의한다.
- **D-03:** 메시지 타입은 최소 task_request, task_result, status_update 3가지를 지원하며, 확장 가능하도록 type 필드 기반 디스패치 구조를 사용한다.

### 프로젝트 구조
- **D-04:** 기능별 디렉토리 분리 — server/ (FastAPI 오케스트레이션), dashboard/ (React 프론트엔드), agents/ (Gemma4 역할별 시스템 프롬프트 및 러너), shared/ (메시지 스키마, 유틸리티).

### Claude CLI 연동
- **D-05:** Python subprocess로 Claude CLI를 직접 호출한다. stdin/stdout JSON-lines 프로토콜로 통신하며, SDK 추상화 없이 출력 파싱을 직접 구현한다.
- **D-06:** 토큰 격리를 위해 Claude CLI 호출 시 최소한의 컨텍스트만 주입한다. 불필요한 글로벌 설정 상속을 방지한다.

### Claude's Discretion
- SQLite 테이블 스키마 상세 설계
- 로그 버스 구현 방식 (in-process event emitter vs SQLite 기반)
- Ollama HTTP 클라이언트 구현 세부사항
- atomic write 패턴 구현 방식

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Research
- `.planning/research/STACK.md` — 기술 스택 추천 (CrewAI, FastAPI, SQLite WAL, Ollama 설정)
- `.planning/research/ARCHITECTURE.md` — Hub-Spoke 아키텍처 패턴, 컴포넌트 경계, 데이터 플로우
- `.planning/research/PITFALLS.md` — Claude CLI 토큰 폭발, Ollama 직렬화, Gemma4 구조화 출력 불안정 등 주의사항

### Project
- `.planning/PROJECT.md` — 프로젝트 비전, 제약조건 (로컬 전용, Claude CLI only)
- `.planning/REQUIREMENTS.md` — INFR-01~05, ARTF-01~02 요구사항

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- 없음 (그린필드 프로젝트)

### Established Patterns
- 없음 (첫 번째 페이즈)

### Integration Points
- Phase 2에서 오케스트레이션 로직이 이 인프라 위에 구축됨
- Phase 4에서 대시보드가 로그 버스 WebSocket과 상태 API에 연결됨

</code_context>

<specifics>
## Specific Ideas

- Gemma4 로컬 실행 시 하드웨어 부하 우려 — 단일 순차 큐로 요청 처리 (OLLAMA_NUM_PARALLEL=1 또는 애플리케이션 레벨 큐)
- 리서치에서 제안된 SQLite WAL + atomic write(tmp+rename) 패턴 채택

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-infra-foundation*
*Context gathered: 2026-04-03*
