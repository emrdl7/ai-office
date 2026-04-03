# Architecture Research

**Domain:** AI Multi-Agent Collaboration System (Local Orchestration)
**Researched:** 2026-04-03
**Confidence:** MEDIUM-HIGH

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         사용자 인터페이스 레이어                          │
│  ┌───────────────────────────────┐  ┌─────────────────────────────┐  │
│  │     Web Dashboard (React)     │  │     CLI (stdin 직접 입력)     │  │
│  │  작업지시 / 실시간 로그 / 상태보드  │  │   초기 작업지시 인터페이스      │  │
│  └──────────────┬────────────────┘  └────────────┬────────────────┘  │
│                 │ WebSocket / REST                │ subprocess         │
├─────────────────┼─────────────────────────────────┼──────────────────┤
│                 │         오케스트레이션 레이어         │                  │
│  ┌──────────────▼─────────────────────────────────▼────────────────┐ │
│  │                  Orchestration Server (Node.js)                  │ │
│  │  - 작업 수신 및 라우팅        - Claude CLI 프로세스 관리              │ │
│  │  - 메시지 버스 (SQLite)      - 에이전트 상태 추적                    │ │
│  │  - WebSocket 브로드캐스트    - 파일 산출물 관리                      │ │
│  └──────┬──────────┬──────────┬──────────┬──────────┬──────────────┘ │
│         │          │          │          │          │                  │
├─────────┼──────────┼──────────┼──────────┼──────────┼─────────────── ┤
│         │          │       에이전트 레이어   │          │                  │
│  ┌──────▼──────┐  ┌▼──────────┐  ┌──────▼──────┐  ┌▼──────────────┐ │
│  │  Claude CLI │  │  Planner  │  │  Developer  │  │  Designer /   │ │
│  │   (팀장)    │  │ (기획자/PM) │  │   (개발자)   │  │  QA 에이전트   │ │
│  │             │  │           │  │             │  │               │ │
│  │ Claude Code │  │ Gemma4    │  │ Gemma4      │  │ Gemma4        │ │
│  │ subprocess  │  │ via Ollama│  │ via Ollama  │  │ via Ollama    │ │
│  └──────┬──────┘  └─────┬─────┘  └──────┬──────┘  └───────┬───────┘ │
│         │               │               │                  │          │
├─────────┼───────────────┼───────────────┼──────────────────┼──────── ┤
│         │               │   공유 인프라 레이어 │                │          │
│  ┌──────▼───────────────▼───────────────▼──────────────────▼───────┐ │
│  │                    Message Bus (SQLite WAL)                      │ │
│  │    메시지 라우팅 / 우선순위 / 스레드 / ACK / 에이전트 등록 관리           │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────┐  ┌──────────────────────────────────────┐   │
│  │  Workspace Storage  │  │         State Store (SQLite)          │   │
│  │  /workspace/<task>  │  │   작업 상태 / 히스토리 / 에이전트 상태     │   │
│  │  실제 파일 산출물 저장 │  │                                      │   │
│  └─────────────────────┘  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| Web Dashboard | 작업 지시 입력, 실시간 로그 뷰, 산출물 뷰어, 상태 보드 | Orchestration Server (WebSocket + REST) |
| Orchestration Server | 작업 수신, 에이전트 생명주기 관리, 메시지 라우팅, WebSocket 브로드캐스트 | 모든 컴포넌트의 허브 |
| Claude CLI (팀장) | 작업 분석 및 방향 설정, Planner에게 지시, 최종 산출물 검증 | Orchestration Server (subprocess stdin/stdout) |
| Planner Agent (기획자/PM) | 작업 분해, 전체 워크플로우 추적, 구성원 간 조율 | Message Bus 경유로 모든 에이전트 |
| Developer Agent (개발자) | 코드 작성, 실제 파일 생성 | Message Bus (Planner, QA와 통신) |
| Designer Agent (디자이너) | 디자인 산출물 생성 | Message Bus (Planner, Developer와 통신) |
| QA Agent | 단계별 산출물 검수 | Message Bus (모든 에이전트 산출물 수신) |
| Message Bus | 에이전트 간 메시지 라우팅, 우선순위/ACK/스레드 관리 | 모든 에이전트 |
| State Store | 작업/에이전트 상태 영속화, 워크플로우 이력 저장 | Orchestration Server |
| Workspace Storage | 에이전트가 생성한 실제 파일 저장 | 모든 에이전트 (파일시스템 직접 접근) |

## Recommended Project Structure

```
ai-office/
├── server/                     # Orchestration Server (Node.js)
│   ├── index.ts                # 진입점, Express + WebSocket 서버
│   ├── agents/                 # 에이전트 생명주기 관리
│   │   ├── claude-runner.ts    # Claude CLI subprocess 래퍼
│   │   ├── ollama-runner.ts    # Ollama API 래퍼 (Gemma4 호출)
│   │   └── registry.ts        # 에이전트 등록/상태 추적
│   ├── bus/                    # 메시지 버스
│   │   ├── message-bus.ts      # SQLite 기반 메시지 라우팅
│   │   └── schemas.ts          # 메시지 타입 정의
│   ├── tasks/                  # 작업 관리
│   │   ├── task-manager.ts     # 작업 생성/상태 추적
│   │   └── workspace.ts        # 작업별 파일 디렉토리 관리
│   ├── ws/                     # WebSocket
│   │   └── broadcaster.ts      # 대시보드로 실시간 이벤트 전송
│   └── db/                     # 데이터베이스
│       ├── migrations/         # SQLite 스키마 마이그레이션
│       └── client.ts           # better-sqlite3 클라이언트
├── dashboard/                  # Web Dashboard (React/Vite)
│   ├── src/
│   │   ├── components/         # UI 컴포넌트
│   │   │   ├── TaskInput/      # 작업 지시 입력
│   │   │   ├── AgentBoard/     # 에이전트 상태 보드
│   │   │   ├── LogStream/      # 실시간 로그 스트림
│   │   │   └── ArtifactViewer/ # 산출물 파일 뷰어
│   │   ├── hooks/              # WebSocket 연결 등 커스텀 훅
│   │   └── store/              # 클라이언트 상태 관리 (Zustand)
├── agents/                     # 에이전트 시스템 프롬프트 정의
│   ├── planner.md              # Planner 역할/프롬프트
│   ├── developer.md            # Developer 역할/프롬프트
│   ├── designer.md             # Designer 역할/프롬프트
│   └── qa.md                   # QA 역할/프롬프트
├── workspace/                  # 작업 산출물 저장 루트
│   └── <task-id>/              # 태스크별 격리된 작업공간
│       ├── brief.md            # 작업 개요
│       ├── plan.md             # Planner 생성 계획서
│       └── ...                 # 개발자/디자이너 생성 파일
└── data/                       # SQLite 데이터베이스 파일
    ├── bus.db                  # 메시지 버스
    └── state.db                # 작업/에이전트 상태
```

### Structure Rationale

- **server/agents/:** Claude와 Ollama는 실행 방식이 근본적으로 다르므로 별도 러너로 분리. 교체나 테스트가 쉬워짐.
- **server/bus/:** 메시지 버스를 핵심 인프라로 독립 모듈화. 에이전트들은 버스만 알면 되고 서로를 직접 알 필요 없음.
- **agents/*.md:** 에이전트 역할 정의를 코드 밖에 두면 프롬프트 수정 시 서버 재시작 불필요.
- **workspace/<task-id>/:** 태스크별 격리로 동시 작업 시 파일 충돌 방지.

## Architectural Patterns

### Pattern 1: Hub-Spoke Orchestration (이 프로젝트의 핵심 패턴)

**What:** Orchestration Server가 허브, 에이전트들이 스포크. 모든 메시지는 허브를 통해 라우팅되며 허브가 전체 상태를 소유한다.

**When to use:** 에이전트 수가 많고 자유로운 inter-agent 통신이 필요하지만 전체 가시성도 유지해야 할 때. Planner가 모든 것을 볼 수 있어야 한다는 요구사항에 정확히 부합한다.

**Trade-offs:** 단일 허브가 SPOF가 될 수 있으나 로컬 단일 머신 환경에서는 수용 가능.

**Example:**
```typescript
// server/bus/message-bus.ts
interface Message {
  id: string
  from: AgentId
  to: AgentId | 'broadcast'
  type: 'task' | 'result' | 'status' | 'query'
  content: string
  priority: 'normal' | 'high' | 'urgent'
  reply_to?: string
  task_id: string
  created_at: number
  ack_at?: number
}

// Planner는 자신이 보낸/받은 메시지 외에 모든 broadcast도 구독
function subscribeAsPlanner(agentId: 'planner') {
  return db.prepare(
    `SELECT * FROM messages WHERE to = ? OR to = 'broadcast' ORDER BY created_at DESC`
  ).all(agentId)
}
```

### Pattern 2: Claude CLI subprocess (stdin/stdout JSON-lines)

**What:** Claude Agent SDK 방식으로 Claude CLI를 subprocess로 실행하고 JSON-lines 프로토콜로 통신. Orchestration Server가 stdin에 작업 입력, stdout에서 응답 수신.

**When to use:** Claude API 없이 CLI만 사용해야 하는 이 프로젝트의 핵심 제약에 대응.

**Trade-offs:** API 대비 세밀한 제어가 어렵고 오류 처리가 복잡. 그러나 Claude CLI가 공식 지원하는 유일한 방법.

**Example:**
```typescript
// server/agents/claude-runner.ts
import { spawn } from 'child_process'

function runClaude(prompt: string, onChunk: (text: string) => void) {
  const proc = spawn('claude', ['--output-format', 'stream-json', '--print'], {
    stdio: ['pipe', 'pipe', 'pipe']
  })

  proc.stdin.write(prompt)
  proc.stdin.end()

  proc.stdout.on('data', (chunk) => {
    // JSON-lines 파싱 후 onChunk 콜백
    const lines = chunk.toString().split('\n').filter(Boolean)
    for (const line of lines) {
      const msg = JSON.parse(line)
      if (msg.type === 'assistant') onChunk(msg.content)
    }
  })
}
```

### Pattern 3: Planner-as-Tracker (상태 소유권 분리)

**What:** Planner 에이전트가 워크플로우 추적 역할을 담당하되, 실제 상태 영속화는 Orchestration Server의 State Store에 위임. Planner는 상태를 "읽고 판단"하는 역할, 저장은 서버가 담당.

**When to use:** 에이전트 간 자유로운 통신을 허용하면서 전체 흐름을 잃지 않아야 할 때. "기획자에게 PM 역할 겸임" 요구사항을 구현하는 방법.

**Trade-offs:** Planner의 컨텍스트가 너무 커질 수 있음 — 긴 작업에서는 요약 메커니즘 필요.

## Data Flow

### 작업 시작 플로우 (사용자 → 산출물)

```
사용자 (Dashboard / CLI)
    │
    ▼ POST /api/tasks
Orchestration Server
    │ 작업 레코드 생성 (State Store)
    │ 워크스페이스 디렉토리 생성 (workspace/<task-id>/)
    ▼
Claude CLI subprocess 시작
    │ 작업 내용 + 컨텍스트를 stdin에 주입
    ▼
Claude CLI (팀장)
    │ 작업 분석 → 방향 설정
    │ stdout JSON-lines로 응답
    ▼
Orchestration Server
    │ Claude 응답 파싱
    │ Message Bus에 Planner 수신 메시지 삽입
    ▼
Planner Agent (Gemma4/Ollama)
    │ 작업 계획 수립 (plan.md 생성)
    │ 구성원별 태스크 분해
    │ Message Bus에 태스크 메시지 발행
    ▼
Developer / Designer / QA Agents (병렬 또는 순차)
    │ 각자 역할에 따라 파일 생성 (workspace/<task-id>/ 에 직접 저장)
    │ 완료 시 Message Bus에 result 메시지 발행
    ▼
Planner Agent (진행 추적)
    │ 모든 result 수신 → 전체 완료 여부 판단
    │ QA에게 검수 요청
    ▼
QA Agent
    │ 산출물 검수 → 결과 보고
    ▼
Claude CLI (최종 검증)
    │ 전체 산출물 검토 → 승인 또는 재지시
    ▼
Orchestration Server
    │ 작업 상태를 'completed'로 업데이트
    ▼
Web Dashboard (WebSocket push)
    완료 알림 + 산출물 뷰어 업데이트
```

### 실시간 모니터링 플로우

```
에이전트 (모든 에이전트)
    │ 로그 이벤트 / 상태 변경 발생
    ▼
Orchestration Server
    │ State Store 업데이트
    │ WebSocket 브로드캐스트 (socket.io rooms 또는 ws)
    ▼
Web Dashboard
    실시간 로그 스트림 / 에이전트 상태 보드 갱신
```

### 에이전트 간 직접 메시지 플로우

```
Developer Agent
    │ "디자인 스펙 필요" → Message Bus에 to: 'designer' 메시지 발행
    ▼
Orchestration Server (Message Bus polling / notification)
    │ Planner에게도 복사 전달 (PM 가시성 보장)
    │ WebSocket으로 대시보드에 통신 이벤트 표시
    ▼
Designer Agent
    │ 요청 처리 → 응답 메시지 발행
    ▼
Developer Agent
    응답 수신 후 작업 계속
```

### Key Data Flows 요약

1. **작업 지시 플로우:** 사용자 → Orchestration Server → Claude CLI → Planner → Worker Agents
2. **산출물 생성 플로우:** Worker Agents → workspace/ 파일시스템 → State Store 기록 → Dashboard 알림
3. **모니터링 플로우:** 모든 에이전트 이벤트 → Orchestration Server → WebSocket → Dashboard
4. **PM 가시성 플로우:** 모든 inter-agent 메시지 → Message Bus broadcast 복사 → Planner 구독

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1개 작업, 로컬 | 현재 설계 그대로 — SQLite + 단일 서버 프로세스 충분 |
| 동시 3-5개 작업 | SQLite WAL 모드로 대응 가능, Ollama OLLAMA_NUM_PARALLEL 설정 |
| 동시 10개 이상 작업 | SQLite를 PostgreSQL로 교체, Ollama 인스턴스 다중화 |

### Scaling Priorities

1. **첫 번째 병목:** Ollama 단일 인스턴스 큐. Gemma4 에이전트가 4개면 순차 처리됨. OLLAMA_NUM_PARALLEL=4 설정으로 완화, 또는 에이전트별 포트 다른 Ollama 인스턴스 실행.
2. **두 번째 병목:** SQLite 동시 쓰기. WAL 모드로 읽기/쓰기 분리. 심각한 경우 PostgreSQL 마이그레이션.

## Anti-Patterns

### Anti-Pattern 1: 에이전트가 서로를 직접 호출

**What people do:** Developer Agent가 Designer Agent의 Ollama 엔드포인트를 직접 HTTP 호출
**Why it's wrong:** Planner의 가시성 상실. 에이전트 주소 하드코딩. 오류 전파 시 전체 흐름 파악 불가.
**Do this instead:** 모든 통신은 Message Bus 경유. Orchestration Server가 메시지 라우팅 담당.

### Anti-Pattern 2: 에이전트에 상태 저장

**What people do:** Planner Agent가 자신의 컨텍스트 안에만 전체 워크플로우 상태를 유지
**Why it's wrong:** Ollama 세션 재시작 시 상태 소멸. 대시보드에서 상태 조회 불가. 장기 작업에서 컨텍스트 한계 도달.
**Do this instead:** 에이전트는 판단만, 상태는 State Store(SQLite)에 영속화. Planner는 상태를 읽어서 판단하되 저장은 서버에 위임.

### Anti-Pattern 3: Claude CLI를 과도하게 사용

**What people do:** Claude CLI subprocess를 모든 에이전트 역할에 사용 (비용/속도 문제 무시)
**Why it's wrong:** Claude CLI는 실행 오버헤드가 크고 로컬 Gemma4 대비 느림. 팀장 역할(방향설정, 최종검증)에만 필요한 고품질 판단을 모든 작업에 낭비.
**Do this instead:** Claude는 방향설정과 최종검증에만. 반복적 실무 작업은 Gemma4(Ollama)에 위임.

### Anti-Pattern 4: 동기 에이전트 체인

**What people do:** Developer가 완료할 때까지 Designer를 블록, Designer 완료 후 QA 시작 — 순수 순차 처리
**Why it's wrong:** 병렬화 가능한 작업도 직렬화됨. 전체 작업 시간이 불필요하게 길어짐.
**Do this instead:** Planner가 의존성 없는 태스크는 Message Bus에 동시 발행. Worker들이 독립적으로 처리. QA는 각 단계 완료 시마다 검수.

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Dashboard ↔ Orchestration Server | REST (작업 생성/조회) + WebSocket (실시간 이벤트) | Socket.io 또는 ws 라이브러리 |
| Orchestration Server ↔ Claude CLI | subprocess stdin/stdout (JSON-lines) | Claude Agent SDK 프로토콜 참고 |
| Orchestration Server ↔ Ollama | HTTP REST (POST /api/generate or /api/chat) | Ollama 기본 포트 11434 |
| 에이전트 ↔ 에이전트 | Message Bus (SQLite 테이블) polling | 직접 통신 금지 — 항상 버스 경유 |
| 에이전트 ↔ Workspace | 파일시스템 직접 접근 | 에이전트별 workspace/<task-id>/ 하위 경로 |
| Orchestration Server ↔ State Store | better-sqlite3 직접 쿼리 | 동기 API, WAL 모드 필수 |

### Build Order (의존성 순서)

다음 순서로 빌드해야 이전 레이어에 의존하는 컴포넌트가 제대로 테스트 가능하다.

```
1. Message Bus (SQLite 스키마 + 라우팅 로직)
        ↓
2. State Store (작업/에이전트 상태 스키마)
        ↓
3. Ollama Runner (Gemma4 HTTP 래퍼)
   Claude CLI Runner (subprocess 래퍼)          [병렬 가능]
        ↓
4. Orchestration Server (라우팅 허브 + WebSocket)
        ↓
5. Agent System Prompts (Planner, Developer, Designer, QA)
        ↓
6. Web Dashboard (REST + WebSocket 소비자)
```

**핵심 의존성 설명:**
- Message Bus와 State Store는 다른 모든 것의 기반 — 먼저 안정화
- Agent Runners는 서버 없이 독립 테스트 가능 — 3단계에서 병렬 개발 가능
- Orchestration Server는 러너 + 버스 + 상태스토어를 조합 — 4단계에서 통합
- Dashboard는 서버 API가 확정된 후 개발 — 마지막에 연결

## Sources

- [AI Agent Orchestration Patterns - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) — HIGH confidence, 공식 Microsoft 문서 (2026-02-12 업데이트)
- [Agent Message Bus: Communication Infrastructure for 16 AI Agents](https://dev.to/linou518/agent-message-bus-communication-infrastructure-for-16-ai-agents-18af) — MEDIUM confidence, SQLite+Flask 기반 로컬 메시지버스 실제 구현 사례
- [Multi-Agent AI Systems: Architecture Patterns That Actually Work](https://dev.to/futhgar/multi-agent-ai-systems-architecture-patterns-that-actually-work-107b) — MEDIUM confidence, 프로덕션 패턴 경험 기반
- [Claude Agent SDK - stdin/stdout subprocess communication](https://platform.claude.com/docs/en/agent-sdk/overview) — HIGH confidence, Anthropic 공식 문서
- [Ollama Parallel Requests Configuration](https://docs.ollama.com/faq) — HIGH confidence, Ollama 공식 FAQ
- [Persisting Agent State with SQLite](https://jokerdii.github.io/di-blog/2025/01/24/Persisting-Agent-State/) — MEDIUM confidence, LangGraph SQLiteSaver 패턴

---
*Architecture research for: AI Multi-Agent Collaboration System (Local Orchestration)*
*Researched: 2026-04-03*
