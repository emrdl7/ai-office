# Project Research Summary

**Project:** AI Office — Local Multi-Agent Collaboration System
**Domain:** AI 다중 에이전트 오케스트레이션 시스템 (로컬 실행, 웹 대시보드)
**Researched:** 2026-04-03
**Confidence:** MEDIUM-HIGH

## Executive Summary

AI Office는 Claude CLI를 팀장(판단/검증 역할)으로, Gemma4/Ollama를 작업자 에이전트(기획·개발·디자인·QA)로 분리하여 로컬 macOS 환경에서 완전 자율적으로 동작하는 다중 에이전트 협업 시스템이다. 연구 결과, 이 유형의 시스템에서 가장 중요한 설계 원칙은 두 가지다: (1) Claude CLI와 Ollama 에이전트의 역할을 명확히 분리하고, (2) 에이전트 간 모든 통신을 중앙 메시지 버스를 경유하도록 강제하는 것이다. 역할 기반 팀 구조에는 LangGraph보다 CrewAI가 더 자연스럽게 맞아 떨어지며, SQLite WAL 모드가 로컬 단일 머신에서 메시지 큐와 상태 저장 모두를 담당할 수 있다.

권장 접근 방식은 Hub-Spoke Orchestration 패턴을 핵심으로 삼는다. Orchestration Server(Node.js/TypeScript)가 허브로서 전체 에이전트 생명주기를 관리하고, Claude CLI subprocess와 Ollama API 호출을 분리된 러너로 추상화한다. 이 허브는 WebSocket을 통해 React 대시보드와 실시간으로 연결되며, 모든 에이전트 상태와 산출물은 파일시스템과 SQLite에 영구 저장된다. 에이전트들이 서로를 직접 호출하거나 상태를 자체적으로 유지하는 방식은 명시적으로 금지해야 한다.

주요 리스크는 세 가지다. 첫째, Claude CLI subprocess를 잘못 구성하면 매 턴마다 ~50,000 토큰을 낭비하며 레이턴시가 폭증한다. 둘째, Ollama의 기본 단일 병렬 처리 설정은 4개 에이전트가 동시에 요청할 때 심각한 직렬화를 유발한다. 셋째, Gemma4의 구조화 출력 불안정성은 에이전트 간 메시지 파싱 실패로 이어진다. 이 세 가지 모두 Phase 1 인프라 단계에서 해결하지 않으면 상위 레이어 개발 전체가 불안정한 기반 위에 세워지게 된다.

## Key Findings

### Recommended Stack

핵심 런타임은 Python 3.12 + FastAPI 0.135.x 또는 Node.js + TypeScript 기반 Orchestration Server로 구성한다. 아키텍처 연구에서는 Node.js/TypeScript 기반 서버를 권장했으나, 스택 연구에서는 Python/FastAPI를 제안했다. 두 접근법 모두 기술적으로 유효하며, 핵심은 언어 선택보다 역할 분리(Claude CLI 판단 레이어 vs. 프로세스 관리 레이어)를 명확히 하는 것이다. 에이전트 프레임워크로는 CrewAI 1.13.0이 이 프로젝트의 역할 기반 팀 구조와 가장 자연스럽게 일치한다. Ollama Python SDK 0.6.1을 통해 LiteLLM 경유로 Gemma4 모델을 연결하며, SQLite(WAL 모드)가 메시지 버스와 상태 저장소 역할을 모두 수행한다.

**Core technologies:**
- Python 3.12 + FastAPI 0.135.x: 오케스트레이션 서버 및 WebSocket 허브 — 비동기 네이티브, Pydantic 내장으로 메시지 스키마 검증 통합
- CrewAI 1.13.0: 에이전트 역할 정의 및 오케스트레이션 — Ollama 로컬 모델 네이티브 지원, 역할/목표 추상화가 이 프로젝트 구조와 정확히 일치
- Ollama + Gemma4:e4b: 로컬 작업자 에이전트 실행 — API 키 불필요, 16GB RAM 기준 권장 모델
- SQLite (WAL 모드, SQLModel): 메시지 버스 + 상태 저장 — 외부 서버 불필요, 동시 읽기/쓰기 안전
- React 19 + Vite 6 + TypeScript: 웹 대시보드 — HMR 속도, WebSocket 타입 안정성, Concurrent 렌더링
- Claude CLI (subprocess): 팀장 역할 — 방향설정·최종검증에만 사용, subprocess로 실행하며 API 키 불필요
- Zustand 5.x + TanStack Query 5.x: 대시보드 클라이언트 상태 관리 — 전역 에이전트 상태와 REST 캐싱 분리

### Expected Features

**Must have (table stakes) — v1 출시 필수:**
- Claude CLI → Planner(Gemma4) 작업 디스패치 및 분석
- 구조화 메시지 스키마를 가진 에이전트 간 메시지 큐
- Planner/PM의 전체 워크플로우 추적 (단일 진실의 원천)
- 모든 에이전트 산출물을 실제 파일로 저장 (in-memory 금지)
- QA 에이전트의 단계별 검수 (중간 오류 포착)
- Claude 최종 검증 + 재지시 루프
- 웹 대시보드: 작업지시 입력, 에이전트 상태 보드, 실시간 로그 스트림, 산출물 뷰어

**Should have (differentiators) — 검증 후 v1.x:**
- 에이전트 간 자유로운 작업 요청 (Developer → Designer 자율 요청)
- 대시보드 워크플로우 그래프 (DAG 시각화)
- CLI 이중 진입점 (대시보드 + CLI)
- 에이전트별 로그 필터링

**Defer (v2+):**
- 산출물 diff/버전 뷰어 (리비전 루프가 안정된 후)
- 추가 에이전트 역할 (보안, DevOps, 데이터)
- 외부 API 연동 (GitHub, Slack) — 로컬 전용 제약 해제 후

**Anti-features (명시적으로 제외):**
- 에이전트 산출물 자동 배포
- 프로젝트 간 영구 메모리 공유
- 5개 초과 동시 에이전트 역할
- 무한 자율 루프 (인간 체크포인트 필수)

### Architecture Approach

Hub-Spoke Orchestration 패턴을 핵심으로 한다. Orchestration Server가 모든 에이전트 생명주기와 메시지 라우팅의 단일 허브이며, 에이전트들은 절대 서로를 직접 호출하지 않는다. Claude CLI는 `subprocess + JSON-lines` 프로토콜로 실행되며, Gemma4 에이전트들은 Ollama HTTP REST API를 통해 호출된다. 작업별로 격리된 워크스페이스 디렉토리(`workspace/<task-id>/`)가 파일 충돌을 방지하고, SQLite WAL 모드 데이터베이스가 메시지 버스와 상태 저장소 역할을 모두 담당한다.

**Major components:**
1. Orchestration Server — 작업 수신, 에이전트 생명주기 관리, 메시지 라우팅, WebSocket 브로드캐스트. 시스템의 단일 허브
2. Claude CLI Runner — subprocess stdin/stdout JSON-lines 프로토콜. 방향설정·최종검증에만 사용
3. Ollama Runner — HTTP REST 래퍼. Planner/Developer/Designer/QA 에이전트 실행
4. Message Bus (SQLite) — 에이전트 간 메시지 라우팅, ACK, 우선순위, 스레드 관리
5. State Store (SQLite) — 작업/에이전트 상태 영속화. 에이전트는 판단만, 저장은 서버가 담당
6. Workspace Storage — 태스크별 격리된 파일 산출물 디렉토리
7. Web Dashboard (React) — REST + WebSocket 소비자. 상태 저장소가 진실의 원천

**Build order (의존성 기반 필수 순서):**
Message Bus → State Store → Agent Runners (병렬) → Orchestration Server → Agent Prompts → Web Dashboard

### Critical Pitfalls

1. **Claude CLI subprocess 토큰 폭발** — 각 subprocess 시작 시 CLAUDE.md·MCP·플러그인 컨텍스트가 ~50K 토큰 재주입됨. 방지책: 스코프된 작업 디렉토리, `--setting-sources project,local`, 비어있는 `--plugin-dir`, 장기 실행 subprocess + `stream-json` 모드. Phase 1에서 반드시 해결.

2. **Claude CLI는 서브에이전트를 직접 생성할 수 없음** — Claude CLI subprocess에서 Ollama 에이전트를 동적으로 스폰할 수 없는 하드 제약. 방지책: Claude CLI는 판단 레이어만, 외부 Orchestration Server가 에이전트 생명주기를 관리. Phase 1 아키텍처 설계 시 반드시 확인.

3. **Gemma4 구조화 출력 불안정** — 특히 소형 변형(4B)에서 JSON 대신 산문, 마크다운 코드블록 내 JSON, XML 등 불일치 형식 출력. 방지책: 엄격 파서 + 실패 시 repair pass (코드블록에서 JSON 추출), Ollama `format: json` 파라미터, 시스템 프롬프트에 one-shot 예시. Phase 2 에이전트 역할 정의 시 반드시 검증.

4. **파일 기반 메시지 큐 경쟁 조건** — 다중 에이전트가 동시에 메시지 파일을 쓸 때 불완전한 파일을 읽는 경우 발생. 방지책: `tmp + atomic rename` 패턴을 모든 메시지 쓰기에 적용, 절대 직접 덮어쓰기 금지. Phase 1 첫 커밋부터 적용.

5. **에이전트 루프/교착 상태** — 역할 지시가 충돌하는 에이전트들이 무한 루프. 방지책: 에이전트 태스크당 최대 3회 재시도, 5분 타임아웃, 순환 의존성 감지, Claude CLI 최종 권한 계층 설정. Phase 2 오케스트레이션 로직 구현 시 필수.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: 인프라 기반 구축

**Rationale:** 아키텍처 연구의 build order와 Pitfalls 연구의 phase 매핑이 일치한다. Message Bus, State Store, 그리고 Claude CLI subprocess 격리는 다른 모든 것의 기반이다. 이 단계의 결함은 상위 레이어 전체에 전파된다.

**Delivers:**
- SQLite 메시지 버스 (WAL 모드, atomic write 패턴 포함)
- SQLite 상태 저장소 (작업/에이전트 상태 스키마)
- Claude CLI subprocess 러너 (설정 격리, stream-json 모드)
- Ollama/Gemma4 HTTP 래퍼 (OLLAMA_NUM_PARALLEL 벤치마크 포함)
- 작업별 워크스페이스 디렉토리 관리

**Addresses:** 파일 출력, 메시지 큐, 상태 추적 (테이블 스테이크)

**Avoids:** Claude CLI 토큰 폭발, 서브에이전트 생성 불가 제약, 파일 큐 경쟁 조건

**Research flag:** 표준 패턴 존재 — SQLite WAL, subprocess 격리 모두 문서화된 패턴. 추가 리서치 불필요.

---

### Phase 2: 에이전트 역할 및 오케스트레이션 로직

**Rationale:** 인프라가 안정화된 후 에이전트 역할 정의와 통신 프로토콜을 구현한다. Pitfalls 연구에 따르면 구조화 출력 계약과 QA 게이트를 에이전트 체인 연결 전에 반드시 검증해야 한다.

**Delivers:**
- Planner/Developer/Designer/QA 에이전트 시스템 프롬프트 (역할, 목표, 출력 스키마)
- 에이전트 간 메시지 스키마 정의 (task_request, task_result, status_update)
- Gemma4 구조화 출력 두 패스 파서 (strict + repair)
- 오케스트레이션 서버: 에이전트 생명주기, 메시지 라우팅, 재시도/타임아웃 로직
- Claude CLI 최종 검증 + 재지시 루프
- QA 에이전트 (원본 요구사항 기반 검수, rubber-stamping 방지)

**Uses:** CrewAI 1.13.0, Ollama SDK 0.6.1, SQLModel

**Implements:** Hub-Spoke Orchestration, Planner-as-Tracker 패턴

**Avoids:** Gemma4 출력 불안정, 에이전트 루프/교착, 에러 누적, QA 확인 편향, 컨텍스트 로트

**Research flag:** 에이전트 컨텍스트 세션 관리(컨텍스트 로트 방지)는 구체적 구현 전략이 필요 — `/gsd:research-phase` 고려.

---

### Phase 3: 웹 대시보드

**Rationale:** 대시보드는 오케스트레이션 서버 API가 확정된 후에 개발해야 한다(build order 최후 단계). Pitfalls 연구에서 WebSocket 업데이트 플러딩은 4개 에이전트 동시 실행 시 즉시 발생하므로, 배치 업데이트 아키텍처를 처음부터 설계해야 한다.

**Delivers:**
- 작업지시 입력 UI + 오케스트레이션 서버 REST 연동
- WebSocket 실시간 로그 스트림 (100-150ms 배치 업데이트, 가상화 목록)
- 에이전트 상태 보드 (저주파 상태 vs. 고주파 로그 분리)
- 산출물 뷰어 (파일 트리 + 구문 강조, Monaco Editor)
- 페이지 새로고침 후 상태 복구 (영구 저장 기반)

**Uses:** React 19, Vite 6, Zustand 5.x, TanStack Query 5.x, react-use-websocket 4.x, Monaco Editor

**Implements:** 대시보드 ↔ 오케스트레이션 서버 WebSocket + REST 경계

**Avoids:** WebSocket 업데이트 플러딩, 대시보드 임시 상태(새로고침 시 손실)

**Research flag:** 표준 패턴 — React WebSocket 배치 업데이트, 가상화 목록은 문서화된 패턴. 추가 리서치 불필요.

---

### Phase 4: v1.x 개선 (검증 후)

**Rationale:** v1 핵심이 실제 프로젝트에서 검증된 후, 사용자 피드백 기반으로 우선순위 결정.

**Delivers:**
- 에이전트 간 자유 작업 요청 (Developer → Designer 자율 요청)
- 에이전트별 로그 필터링
- CLI 이중 진입점
- 대시보드 워크플로우 DAG 그래프

**Research flag:** 자유 에이전트 간 요청은 novel 패턴 — 구현 전 `/gsd:research-phase` 권장.

---

### Phase Ordering Rationale

- Message Bus와 State Store는 에이전트, 서버, 대시보드 모두의 기반이므로 Phase 1 최우선
- Claude CLI 설정 격리는 Phase 1에서 해결하지 않으면 Phase 2 개발 전체가 토큰 비용과 레이턴시 문제로 오염됨
- Gemma4 구조화 출력 계약을 Phase 2에서 먼저 검증한 후 에이전트를 체인으로 연결해야 오류 누적 방지 가능
- 대시보드는 오케스트레이션 서버 API가 안정화된 Phase 3에서 구현 — 이전에 연결하면 API 변경 시마다 대시보드 코드도 변경해야 함
- v1.x 자유 에이전트 요청은 메시지 버스가 안정화된 이후에만 안전하게 추가 가능

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** 에이전트 컨텍스트 세션 관리 전략 — Gemma4 e4b의 실제 컨텍스트 한계와 summary 메커니즘 구현 방식이 문서화 부족
- **Phase 4 (자유 에이전트 요청):** 에이전트가 자율적으로 타 에이전트에게 작업을 요청하는 패턴은 CrewAI에서 명시적으로 지원하는지 확인 필요

Phases with standard patterns (skip research-phase):
- **Phase 1:** SQLite WAL, subprocess 격리, atomic file write — 모두 공식 문서로 검증된 패턴
- **Phase 3:** React WebSocket 배치 처리, 가상화 목록, Monaco Editor 통합 — 성숙한 생태계의 표준 패턴

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | 핵심 스택(CrewAI, Ollama, FastAPI, React/Vite)은 공식 PyPI/문서로 버전 검증됨. Orchestration Server 언어(Python vs. Node.js) 결정은 팀 선호도에 따라 조정 가능 |
| Features | MEDIUM | MAST 2025 피어리뷰 연구 및 Microsoft 공식 아키텍처 가이드에서 검증. 그러나 Claude CLI + Gemma4 조합은 novel — 일부 기능 복잡도 추정은 실제 구현 시 수정될 수 있음 |
| Architecture | MEDIUM-HIGH | Hub-Spoke 패턴, subprocess 프로토콜, SQLite WAL은 공식 소스로 검증됨. Planner-as-Tracker 패턴은 합리적 추론이나 이 정확한 조합의 실제 사례는 단일 소스 |
| Pitfalls | HIGH | 피어리뷰 논문, 공식 Ollama GitHub 이슈, Anthropic 공식 문서 등 다중 독립 소스로 검증. 실제 운영 post-mortem 기반 |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Orchestration Server 언어 선택:** STACK.md는 Python/FastAPI, ARCHITECTURE.md는 Node.js/TypeScript를 제안. 두 접근법 모두 유효하나 일관성을 위해 Phase 1 시작 전 결정 필요. Python으로 통일하면 CrewAI 직접 통합이 더 자연스러움.
- **Gemma4 e4b 실제 도구 호출 신뢰성:** 구조화 출력 불안정 pitfall은 문서화되어 있으나, Gemma4 e4b의 최신 Ollama 버전에서 `format: json`으로 해결되는 정도가 불명확. Phase 2 초반에 실제 파싱 실패율을 벤치마크해야 함.
- **Ollama 병렬 처리 실제 한계:** 타겟 하드웨어(macOS, 16GB RAM)에서 Gemma4 e4b의 실제 OLLAMA_NUM_PARALLEL 한계를 Phase 1에서 측정해야 Phase 2 에이전트 병렬화 설계가 가능.
- **CrewAI의 Planner-as-PM 패턴 지원:** CrewAI의 hierarchical 크루 모드가 이 프로젝트의 Planner/PM 패턴을 정확히 지원하는지 실제 코드 검증 필요.

## Sources

### Primary (HIGH confidence)
- [CrewAI 공식 문서 — LLM Connections](https://docs.crewai.com/en/learn/llm-connections) — Ollama LiteLLM 연동, 버전 1.13.0
- [FastAPI 릴리스 노트](https://fastapi.tiangolo.com/release-notes/) — 0.135.x, Python 3.10+ 요구사항
- [Claude Agent SDK — subprocess 통신](https://platform.claude.com/docs/en/agent-sdk/overview) — stdin/stdout JSON-lines 프로토콜
- [Ollama 공식 FAQ](https://docs.ollama.com/faq) — 병렬 처리 설정 및 한계
- [Ollama GitHub Issue #9054](https://github.com/ollama/ollama/issues/9054) — 단일 인스턴스 직렬화 확인
- [AI Agent Orchestration Patterns — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) — Hub-Spoke 패턴
- [Why Do Multi-Agent LLM Systems Fail? (MAST 2025)](https://arxiv.org/html/2503.13657v1) — 조율 실패율 36.9%, 메시지 스키마 요구사항
- [Mitigating LLM Hallucinations Using a Multi-Agent Framework](https://www.mdpi.com/2078-2489/16/7/517) — QA 확인 편향 (피어리뷰)

### Secondary (MEDIUM confidence)
- [Ollama Python SDK PyPI](https://pypi.org/project/ollama/) — 버전 0.6.1
- [Gemma4 Ollama 라이브러리](https://ollama.com/library/gemma4) — 모델 변형 및 용량
- [Agent Message Bus: Communication Infrastructure for 16 AI Agents](https://dev.to/linou518/agent-message-bus-communication-infrastructure-for-16-ai-agents-18af) — SQLite 메시지 버스 구현 사례
- [Building a 24/7 Claude Code Wrapper — Token Overhead](https://dev.to/jungjaehoon/why-claude-code-subagents-waste-50k-tokens-per-turn-and-how-to-fix-it-41ma) — subprocess 토큰 오버헤드 측정
- [When AI Agents Collide: Multi-Agent Orchestration Failure Playbook 2026](https://cogentinfo.com/resources/when-ai-agents-collide-multi-agent-orchestration-failure-playbook-for-2026) — 무한 루프, 교착 상태
- [Why Your Multi-Agent System is Failing: 17x Error Trap](https://towardsdatascience.com/why-your-multi-agent-system-is-failing-escaping-the-17x-error-trap-of-the-bag-of-agents/) — 에러 누적

### Tertiary (LOW confidence)
- [SQLite is the Best Database for AI Agents](https://dev.to/nathanhamlett/sqlite-is-the-best-database-for-ai-agents-and-youre-overcomplicating-it-1a5g) — WAL 모드 에이전트 패턴 (단일 소스)
- [CrewAI vs LangGraph comparison](https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared) — 프레임워크 비교 (블로그)

---
*Research completed: 2026-04-03*
*Ready for roadmap: yes*
