# Phase 2: Orchestration & Workflow - Research

**Researched:** 2026-04-03
**Domain:** Multi-agent orchestration — Hub-Spoke, DAG task graph, QA 검수, 보완 루프
**Confidence:** HIGH (Phase 1 구현체 직접 열람 + 기존 research 문서 교차 검증)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** 시스템 프롬프트 관리 방식은 Claude 재량 (파일 기반 또는 DB)
- **D-02:** 각 에이전트(기획자, 디자이너, 개발자, QA) 프롬프트에 반드시 포함: 역할 정의, JSON 출력 형식 스키마, 다른 에이전트에게 요청하는 방법(협업 규칙), 금지 사항(역할 외 작업)
- **D-03:** 4개 에이전트 각각 독립된 시스템 프롬프트를 가지며, Ollama 호출 시 system 필드로 주입
- **D-04:** 사용자 지시 → Claude(팀장) 분석 → 항상 기획자에게 진행방향과 함께 전달. Claude는 작업자에게 직접 지시하지 않고 반드시 기획자를 경유한다
- **D-05:** 기획자가 태스크 그래프(DAG)를 구성하여 의존성 기반으로 병렬/순차 작업을 자동 결정. 단, Gemma4 순차 실행 정책(Phase 1 INFR-03)에 따라 실제 실행은 큐를 통해 순차적
- **D-06:** 구성원 간 자유 작업 요청 가능 — 개발자가 디자이너에게 직접 요청할 수 있지만, 모든 요청은 메시지 버스를 통하며 기획자가 전체 흐름을 추적한다
- **D-07:** QA는 각 작업자의 작업 완료 시점에 검수를 수행한다 (디자이너 완료 → QA → 개발자 완료 → QA → 최종검증)
- **D-08:** QA는 원본 요구사항(기획자가 전달한 task_request의 요구사항)을 독립적으로 참조하여 검수
- **D-09:** QA 불합격 시 구체적 문제점과 함께 해당 작업자에게 직접 반려(task_result로 fail + 이유 전달)
- **D-10:** Claude 최종 검증 후 불합격 시 보완 지시는 기획자를 경유하여 전달
- **D-11:** 최대 보완 반복 횟수는 Claude 재량으로 결정
- **D-12:** 최대 반복 횟수 초과 시 사용자에게 에스컬레이션

### Claude's Discretion

- 시스템 프롬프트 저장 형태 (파일 vs DB) → **파일 기반 권장** (아래 섹션 참조)
- 태스크 그래프 구현 방식 (인메모리 vs SQLite) → **인메모리 Python 자료구조 권장** (아래 참조)
- 최대 보완 반복 횟수 결정 → **3회 권장** (아래 근거 참조)
- 에이전트 간 메시지 라우팅 구현 세부사항

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ORCH-01 | Claude CLI가 사용자의 프로젝트 지시를 분석하고 기획자에게 진행방향과 함께 전달할 수 있다 | `run_claude_isolated()` 재사용. Claude 응답을 파싱하여 MessageBus에 planner 수신 메시지로 발행하는 orchestration 레이어 신규 작성 |
| ORCH-02 | 기획자, 디자이너, 개발자, QA 4개 에이전트가 각각 독립된 역할과 시스템 프롬프트를 가진다 | `agents/` 디렉토리에 `.md` 파일 기반 프롬프트 4개 작성. Ollama 호출 시 `system` 필드로 주입 |
| ORCH-03 | 에이전트 간 통신은 JSON 구조화 메시지 스키마(task_request, task_result, status_update)를 따른다 | 기존 `AgentMessage` + `MessageBus`에 payload 스키마 Pydantic 모델 추가 (TaskRequestPayload, TaskResultPayload, StatusUpdatePayload) |
| ORCH-04 | Claude가 최종 산출물을 검증하고, 불합격 시 구체적 보완 사항과 함께 재지시할 수 있다 | `run_claude_isolated()` 재사용. 최종 검증 전용 프롬프트 + 보완 루프 상태 머신 구현 |
| ORCH-05 | Gemma4 에이전트는 순차적으로 실행되며, 로컬 하드웨어 부하를 고려한 실행 정책을 따른다 | Phase 1 `OllamaRunner` (asyncio.Queue 단일 워커) 그대로 재사용 — 신규 작업 없음 |
| WKFL-01 | 기획자가 PM으로서 전체 태스크 상태(대기/진행/완료/차단)를 추적하고 관리한다 | `TaskGraph` 클래스 (인메모리 DAG) + SQLite 영속화. 기획자 프롬프트에 PM 추적 역할 명시 |
| WKFL-02 | QA 에이전트가 각 작업 단계 완료 시 원본 요구사항 대비 검수를 수행한다 | QA 시스템 프롬프트에 "원본 요구사항만 참조" 패턴 적용 (Pitfall 8 방지). 작업 완료 이벤트 훅 구현 |
| WKFL-03 | 구성원이 다른 구성원에게 자유롭게 작업을 요청할 수 있다 | MessageBus의 `to_agent` 필드로 직접 라우팅. 기획자가 broadcast 구독으로 가시성 유지 |
| WKFL-04 | 기획자가 모든 에이전트 간 요청과 결과를 추적하여 전체 흐름을 파악한다 | MessageBus에 `to_agent='broadcast'` 복사 발행. 기획자는 broadcast 채널도 구독 |
</phase_requirements>

---

## Summary

Phase 2는 Phase 1에서 완성된 인프라(MessageBus, OllamaRunner, EventBus, WorkspaceManager, run_claude_isolated) 위에 오케스트레이션 로직을 구축하는 단계다. 새로운 라이브러리를 추가하는 것이 아니라, 기존 컴포넌트를 연결하는 **조율 레이어(orchestration layer)**를 신규로 작성하는 것이 핵심이다.

주요 신규 작성 대상은 네 가지다: (1) 4개 에이전트 시스템 프롬프트 파일(`agents/planner.md` 등), (2) payload 스키마 Pydantic 모델, (3) 태스크 그래프(DAG) 관리자, (4) 오케스트레이션 루프(Claude 분석 → 기획자 → 작업자 → QA → Claude 최종검증 → 보완 루프). FastAPI 엔드포인트는 최소한으로 추가한다(`POST /api/tasks`).

가장 큰 위험은 두 가지다: QA 확증편향(Pitfall 8 — QA가 원본 요구사항이 아닌 작업 결과물만 보고 통과 처리)과 에이전트 루프(Pitfall 4 — 상충하는 지시로 무한 반려/재작업). 두 위험 모두 설계 단계에서 차단해야 하며 구현 후 수정은 비용이 크다.

**Primary recommendation:** 기존 MessageBus를 그대로 두고, `server/orchestration/` 모듈을 신규로 추가하여 오케스트레이션 흐름 전체를 캡슐화한다. `main.py`는 `POST /api/tasks` 엔드포인트만 추가하고 나머지는 orchestration 모듈에 위임한다.

---

## Project Constraints (from CLAUDE.md)

프로젝트 루트의 `CLAUDE.md`에서 추출한 지시사항:

| 항목 | 내용 |
|------|------|
| CSS 방법론 | BEM (Phase 2는 백엔드 중심이므로 해당 없음) |
| CSS 전처리기 | SCSS (dart-sass) — Phase 2 해당 없음 |
| 패키지 매니저 | npm (프론트엔드), uv (백엔드 Python) |
| 인라인 스타일 금지 | Phase 2 해당 없음 |
| `!important` 금지 | Phase 2 해당 없음 |
| 들여쓰기 | 2 spaces |
| 따옴표 | single quote |
| 세미콜론 | 없음 (Python은 해당 없음 — Python 스타일 준수) |
| 주석 | 한국어로 작성 |
| 파일 수정 전 현재 내용 확인 | 반드시 준수 |
| Git commit 메시지 | 한국어, 명령형 |

**Python 코드 스타일**: 기존 Phase 1 코드(schemas.py, message_bus.py 등)가 따르는 패턴을 유지 — type hint 필수, docstring 한국어, Pydantic BaseModel 사용.

---

## Standard Stack

### Core (재사용 — 신규 설치 없음)

| 컴포넌트 | 현재 버전/위치 | Phase 2에서의 역할 |
|----------|---------------|-------------------|
| `MessageBus` | `server/bus/message_bus.py` | 에이전트 간 모든 메시지 라우팅 |
| `AgentMessage` | `server/bus/schemas.py` | 메시지 봉투 — payload 스키마 확장 필요 |
| `run_claude_isolated()` | `server/runners/claude_runner.py` | Claude 팀장 역할(분석, 최종검증) 호출 |
| `OllamaRunner` | `server/runners/ollama_runner.py` | 4개 Gemma4 에이전트 순차 호출 |
| `EventBus` | `server/log_bus/event_bus.py` | 오케스트레이션 이벤트 실시간 브로드캐스트 |
| `WorkspaceManager` | `server/workspace/manager.py` | 에이전트 산출물 파일 저장 |
| FastAPI + `main.py` | `server/main.py` | `POST /api/tasks` 엔드포인트 추가 |

### 신규 작성 대상

| 모듈/파일 | 목적 |
|-----------|------|
| `server/orchestration/loop.py` | 오케스트레이션 메인 루프 (상태 머신) |
| `server/orchestration/task_graph.py` | DAG 태스크 그래프 + 인메모리 상태 관리 |
| `server/orchestration/router.py` | MessageBus 메시지 라우팅 + 에이전트 디스패치 |
| `server/bus/payloads.py` | Pydantic payload 스키마 (TaskRequest, TaskResult, StatusUpdate) |
| `agents/planner.md` | 기획자 시스템 프롬프트 |
| `agents/developer.md` | 개발자 시스템 프롬프트 |
| `agents/designer.md` | 디자이너 시스템 프롬프트 |
| `agents/qa.md` | QA 시스템 프롬프트 |

### Discretion 결정 근거

**시스템 프롬프트 저장: 파일 기반(`.md`) 권장**
- 프롬프트 수정 시 서버 재시작 불필요 (ARCHITECTURE.md 근거)
- 버전 관리(git)가 자동으로 됨
- Ollama `system` 파라미터에 주입 시 파일 읽기 비용 무시할 수준

**태스크 그래프 구현: 인메모리 Python 자료구조 권장**
- 단일 프로젝트 단위 실행 — 프로세스 재시작 시 어차피 새 작업
- DAG 노드 수가 최대 10-15개 수준 — SQLite 오버킬
- `dict[str, TaskNode]` + `dict[str, list[str]]` (의존성 adjacency list)로 충분
- 태스크 상태 영속화는 SQLite가 아닌 WorkspaceManager의 `task_state.json` atomic write로 충분

**최대 보완 반복 횟수: 3회**
- PITFALLS.md 근거: "Max 3 retries per agent per task before escalating"
- 3회 초과 시 에러가 구조적(프롬프트 설계 문제) 가능성이 높아 사람 개입 필요
- 2회는 너무 적음(일시적 JSON 파싱 실패 포함), 5회는 무한 루프 위험 증가

---

## Architecture Patterns

### 권장 디렉토리 구조 (Phase 2 추가분)

```
server/
├── orchestration/          # Phase 2 신규 — 오케스트레이션 로직
│   ├── __init__.py
│   ├── loop.py             # 오케스트레이션 메인 루프 (상태 머신)
│   ├── task_graph.py       # DAG 태스크 그래프 관리자
│   └── router.py           # 메시지 라우팅 + 에이전트 디스패치
├── bus/
│   ├── schemas.py          # 기존 AgentMessage (변경 없음)
│   └── payloads.py         # Phase 2 신규 — payload Pydantic 모델
├── agents/                 # 시스템 프롬프트 파일 (서버 외부에도 가능)
│   ├── planner.md
│   ├── developer.md
│   ├── designer.md
│   └── qa.md
...
```

실제로 `agents/` 폴더는 `server/` 외부에 둘 수 있다(ARCHITECTURE.md 권장 패턴). Phase 1 코드 구조를 보면 `/Users/johyeonchang/ai-office/agents/` 위치가 자연스럽다.

### Pattern 1: 오케스트레이션 상태 머신

**What:** 전체 워크플로우를 명시적 상태 머신으로 구현. 상태 전이마다 EventBus에 이벤트 발행.

**States:**
```
IDLE → CLAUDE_ANALYZING → PLANNER_PLANNING → WORKER_EXECUTING
     → QA_REVIEWING → [WORKER_REVISING | CLAUDE_FINAL_VERIFYING]
     → [REVISION_LOOPING | COMPLETED | ESCALATED]
```

**When to use:** 보완 루프가 있는 모든 multi-step 워크플로우. 상태 머신 없이 구현하면 루프 감지와 반복 횟수 추적이 불가능하다.

**Example:**
```python
# server/orchestration/loop.py
from enum import Enum

class WorkflowState(str, Enum):
    IDLE = 'idle'
    CLAUDE_ANALYZING = 'claude_analyzing'
    PLANNER_PLANNING = 'planner_planning'
    WORKER_EXECUTING = 'worker_executing'
    QA_REVIEWING = 'qa_reviewing'
    CLAUDE_FINAL_VERIFYING = 'claude_final_verifying'
    REVISION_LOOPING = 'revision_looping'
    COMPLETED = 'completed'
    ESCALATED = 'escalated'   # 최대 반복 초과 시 사용자에게 에스컬레이션

class OrchestrationLoop:
    MAX_REVISION_ROUNDS = 3   # D-11: Claude 재량 → 3회로 결정

    def __init__(self, bus: MessageBus, runner: OllamaRunner, event_bus: EventBus):
        self.bus = bus
        self.runner = runner
        self.event_bus = event_bus
        self._state = WorkflowState.IDLE
        self._revision_count = 0
```

### Pattern 2: Payload 스키마 계층 분리

**What:** `AgentMessage.payload`는 현재 `Any` 타입. Phase 2에서 Pydantic 구조화 모델로 교체하여 에이전트 간 계약을 코드 레벨에서 강제한다.

**Example:**
```python
# server/bus/payloads.py
from pydantic import BaseModel
from typing import Literal

class TaskRequestPayload(BaseModel):
    task_id: str
    description: str                    # 수행할 작업 설명
    requirements: str                   # 원본 요구사항 (QA 독립 참조용 — D-08)
    depends_on: list[str] = []          # DAG 의존 task_id 목록
    assigned_to: str                    # 실행 에이전트 id

class TaskResultPayload(BaseModel):
    task_id: str
    status: Literal['success', 'fail']
    artifact_paths: list[str] = []      # workspace 내 상대 경로
    summary: str                        # 작업 요약 (기획자 추적용)
    failure_reason: str | None = None   # QA 반려 시 구체적 이유 (D-09)

class StatusUpdatePayload(BaseModel):
    task_id: str
    state: str                          # WorkflowState 값
    agent_id: str
    note: str = ''
```

### Pattern 3: 기획자 PM 추적 — broadcast 구독

**What:** 모든 에이전트 간 메시지에 `to_agent='broadcast'` 복사를 자동 발행하여 기획자가 전체 흐름을 파악한다.

**When to use:** WKFL-04 (기획자가 모든 흐름 파악), WKFL-03 (자유 요청 허용) 동시 구현.

**Example:**
```python
# server/orchestration/router.py
async def route_message(self, msg: AgentMessage) -> None:
    '''메시지 라우팅 + 기획자 broadcast 복사 자동 발행'''
    # 원본 메시지 발행
    self.bus.publish(msg)

    # 기획자에게 복사 전달 (WKFL-04)
    # 이미 to=planner인 경우 중복 방지
    if msg.to_agent != 'planner' and msg.to_agent != 'broadcast':
        copy = msg.model_copy(update={
            'id': str(uuid.uuid4()),
            'to_agent': 'planner',   # alias='to'
            'metadata': {**msg.metadata, 'is_copy': True},
        })
        self.bus.publish(copy)
```

### Pattern 4: QA 독립 참조 — 원본 요구사항 주입

**What:** QA 에이전트에게 `task_request.payload.requirements`(원본 요구사항)를 별도로 전달하여 작업 결과물과 독립적으로 검수.

**Critical:** QA 프롬프트에 다음 구조를 강제한다:
```
[원본 요구사항]
{requirements}

[작업 결과물 경로]
{artifact_paths}

질문: 원본 요구사항을 기준으로 결과물을 검수하라.
결과물만 보고 판단하지 말고 반드시 요구사항 대비 검증하라.
```

이 패턴이 없으면 QA가 개발자 출력에 앵커링되어 확증편향(Pitfall 8)이 발생한다.

### Anti-Patterns to Avoid

- **Claude가 기획자 우회하여 작업자에게 직접 지시:** D-04 위반. Claude 응답을 파싱하면 항상 planner 수신 메시지로 변환해야 한다.
- **QA에게 작업 결과물만 전달:** Pitfall 8. 반드시 `task_request.payload.requirements`를 함께 전달해야 한다.
- **보완 루프 횟수 제한 없음:** Pitfall 4. `MAX_REVISION_ROUNDS` 상수 없이 구현하면 무한 루프 발생.
- **`AgentMessage.payload`를 계속 `Any`로 유지:** ORCH-03 위반. payload 스키마 없으면 에이전트 역할 위반을 코드가 잡지 못함.
- **태스크 상태를 에이전트 컨텍스트에만 유지:** Pitfall 7 (컨텍스트 로트). 상태는 반드시 외부(파일/DB)에 저장해야 한다.

---

## Don't Hand-Roll

| 문제 | 직접 구현하지 말 것 | 사용할 것 | 이유 |
|------|---------------------|-----------|------|
| JSON 파싱 실패 복구 | 커스텀 파서 | `parse_json()` (Phase 1 구현체) | 이미 2-pass + trailing comma 복구 완비 |
| 에이전트 순차 실행 | 새로운 큐 시스템 | `OllamaRunner.generate_json()` | asyncio.Queue 단일 워커로 이미 구현 |
| 파일 atomic write | `open()` 직접 사용 | `WorkspaceManager.write_artifact()` | tmp+rename 패턴 이미 구현 |
| 에이전트 메시지 발행/소비 | SQLite 직접 쿼리 | `MessageBus.publish()` / `consume()` | ACK, 우선순위, 필터링 완비 |
| 실시간 이벤트 브로드캐스트 | polling 또는 새 WebSocket | `EventBus.publish()` | asyncio.Queue fan-out 완비 |
| Ollama system prompt 주입 | 프롬프트 prefix 직접 작성 | Ollama `/api/generate` `system` 필드 | 공식 Ollama API 필드 — 모델이 system/user 분리를 올바르게 처리 |

**Key insight:** Phase 1은 Phase 2를 위한 모든 인프라를 이미 완성했다. Phase 2의 실제 작업량은 "기존 부품을 올바른 순서로 연결하는 것"이다. 새로운 라이브러리 설치 없이 구현 가능하다.

---

## Common Pitfalls

### Pitfall 1: QA 확증편향 (Rubber-Stamping)
**What goes wrong:** QA가 개발자 산출물만 받고, 요구사항과 무관하게 "결과물이 일관성 있다"는 이유로 통과.
**Why it happens:** LLM은 컨텍스트 내 마지막으로 본 것에 앵커링됨. QA에게 개발자 출력을 주면 개발자 관점을 그대로 채택.
**How to avoid:** QA 에이전트에게 `TaskRequestPayload.requirements`를 반드시 별도 섹션으로 전달. QA 시스템 프롬프트에 "원본 요구사항 대비 검수"를 명시. PITFALLS.md Pitfall 8 전략 적용.
**Warning signs:** QA가 모든 태스크를 첫 시도에 통과시킴 — 이는 정상이 아님.

### Pitfall 2: 에이전트 무한 반려 루프
**What goes wrong:** QA가 요구사항을 너무 엄격하게 해석하여 작업자가 생산할 수 없는 결과를 요구, 작업자가 반복 시도하며 루프.
**Why it happens:** 에이전트 지시가 상충하거나 QA 기준이 모호할 때. 반복 횟수 상한 없으면 무한 루프.
**How to avoid:** `MAX_REVISION_ROUNDS = 3` 상수. 각 `task_request`에 `retry_count` 필드 포함. 초과 시 즉시 사용자 에스컬레이션.
**Warning signs:** 동일 `task_id`가 MessageBus에서 3회 이상 순환; 로그에 동일 에이전트 쌍이 반복.

### Pitfall 3: Claude가 기획자 우회
**What goes wrong:** Claude 응답에서 직접 `to_agent='developer'` 메시지를 생성하여 기획자 없이 작업자에게 전달.
**Why it happens:** Claude 응답 파싱 로직이 D-04를 강제하지 않으면 발생.
**How to avoid:** `run_claude_isolated()` 래핑 함수에서 항상 `to_agent='planner'`로만 발행. Claude 프롬프트에 "응답은 기획자에게 전달할 지시 형식으로 작성"을 명시.
**Warning signs:** MessageBus에서 `from_agent='claude'`, `to_agent='developer'|'designer'|'qa'` 메시지 발견.

### Pitfall 4: 태스크 그래프 상태 소실
**What goes wrong:** 인메모리 DAG가 예외나 프로세스 재시작으로 소실되어 작업 진행 상황 복구 불가.
**Why it happens:** 인메모리 자료구조는 프로세스 종료 시 소멸.
**How to avoid:** 태스크 상태를 `WorkspaceManager`를 통해 `task_state.json`으로 atomic write. 상태 전이마다 즉시 저장. 서버 재시작 시 JSON에서 상태 복원.
**Warning signs:** 서버 재시작 후 진행 중이던 작업이 `IDLE` 상태로 초기화됨.

### Pitfall 5: Gemma4 시스템 프롬프트 무시
**What goes wrong:** Ollama `system` 필드로 주입한 프롬프트를 Gemma4가 무시하고 일반 어시스턴트로 응답.
**Why it happens:** `format: json`과 `system` 필드가 동시에 있을 때 일부 Gemma4 버전에서 system 필드가 JSON 출력 지시로 덮어써질 수 있음.
**How to avoid:** `prompt` 필드 내부에도 system 지시를 반복 포함. 예: `[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}`. 출력에서 역할 정체성이 보존되는지 테스트.
**Warning signs:** 에이전트가 역할 외 작업을 수행하거나 다른 에이전트 역할을 참조.

---

## Code Examples

### Claude 응답 → 기획자 메시지 변환 패턴

```python
# server/orchestration/loop.py
# Source: Claude runner Phase 1 + D-04 결정
async def dispatch_to_planner(
    self,
    task_id: str,
    user_instruction: str,
) -> None:
    '''Claude 분석 결과를 기획자에게 전달 (D-04: 항상 기획자 경유)'''
    # Claude에게 분석 요청
    claude_prompt = (
        f'다음 프로젝트 지시를 분석하고 기획자에게 전달할 진행방향을 작성하라.\n'
        f'반드시 JSON 형식으로 응답하라.\n\n'
        f'지시: {user_instruction}\n\n'
        f'응답 형식:\n'
        f'{{"direction": "진행방향 요약", "requirements": "구체적 요구사항", "priority": "high|normal"}}'
    )
    claude_response = await run_claude_isolated(claude_prompt)
    parsed = parse_json(claude_response)

    if parsed is None:
        # 파싱 실패 시 raw text를 direction으로 사용
        parsed = {'direction': claude_response, 'requirements': user_instruction, 'priority': 'normal'}

    # 기획자에게 task_request 발행 (to_agent는 항상 'planner')
    payload = TaskRequestPayload(
        task_id=task_id,
        description=parsed.get('direction', ''),
        requirements=parsed.get('requirements', user_instruction),
        assigned_to='planner',
    )
    msg = AgentMessage(
        type='task_request',
        **{'from': 'claude', 'to': 'planner'},
        payload=payload.model_dump(),
        priority=parsed.get('priority', 'normal'),
    )
    self.bus.publish(msg)
    await self.event_bus.publish(LogEvent(
        agent_id='claude',
        event_type='task_start',
        message=f'기획자에게 진행방향 전달: {task_id}',
        data={'task_id': task_id},
    ))
```

### Ollama 에이전트 호출 (system 프롬프트 주입)

```python
# server/orchestration/router.py
# Source: OllamaRunner Phase 1 + D-03 결정
import httpx
from pathlib import Path

async def call_agent(
    self,
    agent_id: str,            # 'planner' | 'developer' | 'designer' | 'qa'
    user_message: str,
) -> dict | None:
    '''Ollama에 에이전트별 system 프롬프트를 주입하여 호출'''
    agents_dir = Path(__file__).parent.parent.parent / 'agents'
    system_prompt = (agents_dir / f'{agent_id}.md').read_text(encoding='utf-8')

    # OllamaRunner는 /api/generate를 사용하므로 system 필드를 직접 HTTP로 전달
    # OllamaRunner._call_ollama에 system 파라미터 추가 필요
    prompt_with_system = f'[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_message}'
    raw = await self.runner.generate(prompt_with_system)
    return parse_json(raw)
```

**주의:** `OllamaRunner._call_ollama()`의 `json` 파라미터에 `system` 필드를 추가하거나, 위처럼 prompt 내부에 포함하는 방식 중 하나를 선택해야 한다. Ollama `/api/generate`는 `system` 필드를 공식 지원하므로 전자가 더 clean하다.

### QA 원본 요구사항 독립 참조 패턴

```python
# server/orchestration/loop.py
# Source: PITFALLS.md Pitfall 8 방지 패턴
async def invoke_qa(
    self,
    task_id: str,
    original_requirements: str,   # TaskRequestPayload.requirements
    artifact_paths: list[str],
    workspace: WorkspaceManager,
) -> TaskResultPayload:
    '''QA 에이전트 호출 — 원본 요구사항과 산출물을 분리하여 주입'''
    # 산출물 내용 읽기
    artifacts_content = []
    for path in artifact_paths:
        try:
            content = workspace.safe_path(path).read_text(encoding='utf-8')
            artifacts_content.append(f'=== {path} ===\n{content}')
        except Exception:
            artifacts_content.append(f'=== {path} === [읽기 실패]')

    qa_message = (
        f'[원본 요구사항 — 이것이 검수 기준이다]\n{original_requirements}\n\n'
        f'[작업 결과물]\n{"".join(artifacts_content)}\n\n'
        f'원본 요구사항을 기준으로 결과물을 검수하라. '
        f'결과물만 보고 판단하지 말고 반드시 요구사항 대비 검증하라.'
    )
    result = await self.call_agent('qa', qa_message)
    # ... TaskResultPayload로 변환
```

### 보완 루프 상태 머신 (최대 3회)

```python
# server/orchestration/loop.py
async def run_revision_loop(self, task_id: str, workspace: WorkspaceManager) -> bool:
    '''Claude 최종 검증 → 보완 루프. 최대 MAX_REVISION_ROUNDS=3회.

    Returns:
        True: 승인 완료
        False: 최대 횟수 초과 (에스컬레이션 필요)
    '''
    for round_num in range(1, self.MAX_REVISION_ROUNDS + 1):
        # Claude 최종 검증
        verification_result = await self._claude_final_verify(task_id, workspace)
        if verification_result['approved']:
            return True

        # 불합격 — 기획자 경유 보완 지시 (D-10)
        if round_num < self.MAX_REVISION_ROUNDS:
            await self.dispatch_revision_to_planner(
                task_id=task_id,
                revision_notes=verification_result['notes'],
                round_num=round_num,
            )
            # 기획자 → 작업자 실행 대기 (재귀적으로 워크플로우 재실행)
            await self._wait_for_worker_completion(task_id)

    # 최대 횟수 초과 — D-12: 에스컬레이션
    await self.event_bus.publish(LogEvent(
        agent_id='orchestrator',
        event_type='error',
        message=f'보완 {self.MAX_REVISION_ROUNDS}회 초과 — 사용자 에스컬레이션 필요',
        data={'task_id': task_id, 'rounds': self.MAX_REVISION_ROUNDS},
    ))
    return False
```

---

## Runtime State Inventory

> Phase 2는 신규 기능 추가 (greenfield orchestration layer)이므로 rename/refactor 트리거 없음. 단, 기존 Phase 1 컴포넌트와의 연동에서 주의할 상태가 존재한다.

| 카테고리 | 발견된 항목 | 필요 조치 |
|----------|-------------|-----------|
| 저장 데이터 | `data/bus.db` — Phase 1 메시지 버스 DB. `messages` 테이블 스키마는 변경 없음 | 없음 — AgentMessage 스키마 호환 유지 |
| 저장 데이터 | 태스크 상태 (인메모리 DAG) | 신규 — `workspace/<task_id>/task_state.json`으로 atomic write 설계 |
| 실행 중 서비스 | `OllamaRunner` singleton (`main.py`의 `ollama_runner`) | Phase 2 orchestration 모듈이 이 싱글턴을 주입받아야 함 |
| 시크릿/환경변수 | 없음 — 전체 로컬 실행, API 키 없음 | 없음 |
| 빌드 아티팩트 | `server/__pycache__`, `server/.venv` | 없음 — 신규 모듈 추가 시 자동 갱신 |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | 모든 서버 코드 | ✓ | 3.12.12 (uv 가상환경) | — |
| ollama CLI | Gemma4 에이전트 실행 | ✓ | 0.20.0 | — |
| claude CLI | Claude 팀장 역할 | ✓ | 2.1.91 (Claude Code) | — |
| uv | Python 패키지 관리 | ✓ | (가상환경 active 확인됨) | pip |
| pytest + pytest-asyncio | 테스트 실행 | ✓ | pytest 9.0.2 / asyncio 1.3.0 | — |
| Gemma4 모델 (Ollama) | 에이전트 실제 호출 | 불확실 | `ollama list`로 확인 필요 | gemma4:e4b (경량) |

**Missing dependencies with no fallback:**
- 없음 (모든 코어 도구 사용 가능)

**Missing dependencies with fallback:**
- Gemma4 모델: `ollama list`로 실제 로드 여부 확인 필요. 없으면 `ollama pull gemma4:e4b`

**주의:** `server/main.py`의 `OllamaRunner`는 `DEFAULT_MODEL = 'gemma4:26b'`로 하드코딩됨. 실제 환경에 `gemma4:26b`가 없으면 에이전트 호출이 모두 실패한다. Phase 2 Wave 0에서 모델 가용성 확인 + 환경 변수로 모델 이름 설정 가능하게 변경 필요.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `server/pyproject.toml` (`asyncio_mode = "auto"`) |
| Quick run command | `cd server && uv run pytest tests/test_orchestration.py -x` |
| Full suite command | `cd server && uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ORCH-01 | Claude 응답 → planner 메시지 변환 | unit | `uv run pytest tests/test_orchestration.py::test_claude_dispatches_to_planner -x` | ❌ Wave 0 |
| ORCH-02 | 4개 에이전트 시스템 프롬프트 로드 | unit | `uv run pytest tests/test_agents.py::test_agent_prompts_load -x` | ❌ Wave 0 |
| ORCH-03 | TaskRequestPayload / TaskResultPayload 스키마 검증 | unit | `uv run pytest tests/test_payloads.py -x` | ❌ Wave 0 |
| ORCH-04 | Claude 최종검증 → 보완 루프 (3회 제한) | unit | `uv run pytest tests/test_orchestration.py::test_revision_loop_max_rounds -x` | ❌ Wave 0 |
| ORCH-05 | Gemma4 순차 실행 (기존 OllamaRunner) | unit | `uv run pytest tests/test_ollama_runner.py` (기존 테스트 재사용) | ✅ |
| WKFL-01 | TaskGraph DAG 상태 추적 | unit | `uv run pytest tests/test_task_graph.py -x` | ❌ Wave 0 |
| WKFL-02 | QA 에이전트 원본 요구사항 독립 참조 | unit | `uv run pytest tests/test_orchestration.py::test_qa_receives_original_requirements -x` | ❌ Wave 0 |
| WKFL-03 | 에이전트 자유 요청 (developer→designer) | unit | `uv run pytest tests/test_orchestration.py::test_cross_agent_request -x` | ❌ Wave 0 |
| WKFL-04 | 기획자 broadcast 복사 수신 | unit | `uv run pytest tests/test_orchestration.py::test_planner_receives_broadcast_copy -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/test_payloads.py tests/test_task_graph.py -x`
- **Per wave merge:** `cd server && uv run pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `server/tests/test_orchestration.py` — ORCH-01, ORCH-04, WKFL-02, WKFL-03, WKFL-04 커버
- [ ] `server/tests/test_agents.py` — ORCH-02 커버 (에이전트 프롬프트 파일 로드 확인)
- [ ] `server/tests/test_payloads.py` — ORCH-03 커버 (payload 스키마 직렬화/역직렬화)
- [ ] `server/tests/test_task_graph.py` — WKFL-01 커버 (DAG 상태 전이)

---

## State of the Art

| 구 접근법 | 현재 접근법 | 변경 시점 | 영향 |
|-----------|-------------|-----------|------|
| LangChain 직접 사용 | CrewAI / LangGraph (LangChain 위에 구축) | 2024-2025 | 직접 LangChain API 노출 시 추상화 충돌 위험 — CLAUDE.md에 명시 |
| Ollama `/api/chat` multimodal | `/api/generate` with `system` field | Ollama 0.x | `/api/generate`가 더 단순하고 Phase 1 OllamaRunner가 이미 사용 |
| Claude API 직접 호출 | Claude CLI subprocess (`--bare`) | 프로젝트 제약 | 프로젝트 제약 상 API 키 없음 — subprocess만 사용 |

---

## Open Questions

1. **Gemma4 `system` 필드 신뢰성**
   - 무엇을 아는가: Ollama `/api/generate`가 `system` 필드를 공식 지원함
   - 불확실한 점: Gemma4:e4b / Gemma4:26b가 `system` 프롬프트를 얼마나 잘 따르는지 실제 측정값 없음
   - 권장 조치: Wave 1에서 smoke test — 역할 정의만 담긴 간단한 system 프롬프트로 역할 준수 여부 측정

2. **기획자가 생성하는 DAG의 구체적 형식**
   - 무엇을 아는가: Gemma4가 JSON DAG 구조를 출력하도록 프롬프트 가능
   - 불확실한 점: 기획자가 얼마나 복잡한 의존성 그래프를 일관성 있게 생성하는지 측정 필요
   - 권장 조치: 기획자 프롬프트에 고정된 간단한 DAG 스키마 예시를 one-shot으로 포함 (3-5개 태스크 이내로 시작)

3. **모델 파라미터: `gemma4:26b` vs `gemma4:e4b`**
   - 무엇을 아는가: `ollama_runner.py`에 `DEFAULT_MODEL = 'gemma4:26b'` 하드코딩
   - 불확실한 점: 로컬 환경에 어떤 모델이 실제로 설치되어 있는지 확인 필요
   - 권장 조치: Wave 0에서 `OLLAMA_MODEL` 환경 변수로 추출하여 설정 가능하게 변경

---

## Sources

### Primary (HIGH confidence)

- Phase 1 구현체 직접 열람: `server/bus/schemas.py`, `server/bus/message_bus.py`, `server/runners/claude_runner.py`, `server/runners/ollama_runner.py`, `server/runners/json_parser.py`, `server/log_bus/event_bus.py`, `server/workspace/manager.py`, `server/main.py`
- `.planning/research/PITFALLS.md` — Pitfall 4 (무한 루프), Pitfall 8 (QA 확증편향), Pitfall 3 (에러 누적) 직접 적용
- `.planning/research/ARCHITECTURE.md` — Hub-Spoke 패턴, 에이전트 간 통신 구조
- `.planning/phases/02-orchestration-workflow/02-CONTEXT.md` — 모든 locked decision (D-01~D-12)

### Secondary (MEDIUM confidence)

- `.planning/research/FEATURES.md` — 오케스트레이션 기능 요구사항, 자유 요청 패턴
- [Why Do Multi-Agent LLM Systems Fail? (MAST 2025)](https://arxiv.org/html/2503.13657v1) — QA 확증편향, 에러 누적 근거
- [Ollama FAQ — system field](https://docs.ollama.com/faq) — Ollama system 파라미터 공식 지원 확인

### Tertiary (LOW confidence — validation 필요)

- Gemma4 system prompt 준수 신뢰성: 공식 측정값 없음. Wave 1 smoke test에서 검증 필요.

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — Phase 1 구현체 직접 확인, 재사용 목록 명확
- Architecture: HIGH — ARCHITECTURE.md + CONTEXT.md decisions 교차 검증
- Pitfalls: HIGH — PITFALLS.md 직접 적용, peer-reviewed 근거 있음
- Test map: MEDIUM — 테스트 파일 신규 작성 필요 (존재 확인됨)

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (30일 — Phase 2 실행 중 Ollama/Gemma4 업데이트 감시)
