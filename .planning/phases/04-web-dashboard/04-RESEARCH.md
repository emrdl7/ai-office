# Phase 4: Web Dashboard - Research

**Researched:** 2026-04-03
**Domain:** React 19 + Vite 프론트엔드 대시보드, FastAPI WebSocket 연동, React Flow DAG 시각화
**Confidence:** HIGH (백엔드 코드 직접 분석, npm registry 버전 검증 완료)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** React 19 + Vite로 프론트엔드를 구축한다. dashboard/ 디렉토리에 위치.
- **D-02:** Tailwind CSS를 스타일링에 사용한다.
- **D-03:** React Flow 라이브러리로 DAG 워크플로우를 시각화한다.
- **D-04:** 다크 모드와 라이트 모드를 둘 다 지원한다 (토글).
- **D-05:** 대시보드 레이아웃 구성은 Claude 재량.
- **D-06:** 작업 지시 입력 UI — `POST /api/tasks`로 전달, 지시 내역 목록 표시
- **D-07:** 에이전트 상태 보드 — 작업중/대기/완료/에러 실시간 표시
- **D-08:** 실시간 로그 스트림 — WebSocket `/ws/logs` 연결, 새로고침 후 복구
- **D-09:** 산출물 뷰어 — 파일 트리 + 코드 구문 강조 + 마크다운 렌더링
- **D-10:** DAG 시각화 — React Flow로 태스크 의존성과 진행 상태 표시

### Claude's Discretion
- 대시보드 레이아웃 구성 (단일 페이지 vs 탭 vs 사이드바)
- 코드 구문 강조 라이브러리 선택
- 마크다운 렌더링 라이브러리 선택
- 로그 복구 메커니즘 (REST API vs WebSocket 히스토리)
- 상태 보드 폴링 vs WebSocket 방식

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-01 | 웹 대시보드에서 프로젝트 작업 지시를 입력하고 Claude 팀장에게 전달할 수 있다 | POST /api/tasks 엔드포인트 확인 완료. TaskRequest { instruction: str } 전송 |
| DASH-02 | 에이전트별 상태(작업중/대기/완료/에러)를 실시간 상태 보드로 확인할 수 있다 | WorkflowState enum 8개 값 확인. WebSocket LogEvent의 event_type='status_change' 활용 |
| DASH-03 | 모든 에이전트의 작업 로그를 실시간 스트리밍으로 확인할 수 있다 (WebSocket) | /ws/logs WebSocket 엔드포인트 확인. LogEvent { agent_id, event_type, message, data, id, timestamp } 스키마 확인 |
| DASH-04 | 생성된 산출물을 대시보드에서 확인할 수 있다 (코드 구문 강조, 마크다운 렌더링) | workspace/{task_id}/ 경로 패턴 확인. 파일 목록/내용 조회 API 추가 필요 |
| DASH-05 | 작업 지시 내역을 확인할 수 있다 | active_tasks dict (메모리 기반) 확인. GET /api/tasks/{id} 엔드포인트 존재. 목록 API 추가 필요 |
| WKFL-05 | 워크플로우가 DAG 형태로 시각화되어 태스크 의존성과 진행상태를 보여준다 | TaskGraph.to_state_dict() 출력 구조 확인. React Flow 노드/엣지 변환 로직 필요 |
</phase_requirements>

---

## Summary

Phase 4는 백엔드 API가 이미 완성된 상태에서 프론트엔드를 처음부터 구축하는 작업이다. 핵심 연동 포인트는 세 가지다: `POST /api/tasks` (작업 지시 제출), `WebSocket /ws/logs` (실시간 이벤트 수신), 그리고 이 Phase에서 새로 추가해야 할 파일 서빙 API. React Flow는 `@xyflow/react` 패키지(v12)로 제공되며, 기존 `reactflow` 패키지명은 레거시다. TaskGraph.to_state_dict()의 딕셔너리 출력을 React Flow의 nodes/edges 배열로 변환하는 어댑터 함수가 핵심 구현 과제다.

백엔드에 누락된 API가 두 개 있다: (1) 전체 작업 목록 조회 (`GET /api/tasks`), (2) 산출물 파일 접근 (`GET /api/workspace/{task_id}/files`, `GET /api/workspace/{task_id}/files/{path}`). 이 두 엔드포인트를 FastAPI에 추가하는 작업이 Wave 1 초반에 필요하다. 프론트엔드 단독으로는 대시보드를 완성할 수 없다.

레이아웃 권장안: 사이드바 + 메인 패널 구조. 왼쪽 사이드바에 작업 지시 입력과 지시 내역 목록, 오른쪽 메인 패널에 탭(상태 보드 / 로그 스트림 / DAG 뷰 / 산출물 뷰어). 이 구조는 단일 페이지에서 모든 DASH 요구사항을 커버하면서 정보 밀도를 적절히 분산시킨다.

**Primary recommendation:** `@xyflow/react` v12 + `zustand` v5 + `react-use-websocket` v4 + `react-markdown` + `shiki` 조합으로 구현한다.

---

## Project Constraints (from CLAUDE.md)

CLAUDE.md는 전역 개발 규칙을 정의한다. 이 대시보드는 내부 도구이지만, CLAUDE.md가 명시적으로 예외를 허용하지 않으므로 아래 지침을 준수한다.

| 지침 | 적용 여부 | 비고 |
|------|----------|------|
| 패키지 매니저: npm | 필수 | npm 사용 (uv는 Python 전용) |
| 인라인 스타일 금지 | 필수 | Tailwind 클래스만 사용, `style={}` 금지 |
| `!important` 금지 | 필수 | Tailwind 커스텀 클래스에서도 금지 |
| 이미지 `alt` 속성 필수 | 필수 | 아이콘에도 `aria-label` 적용 |
| 인터랙티브 요소 aria-label | 필수 | 버튼, 입력 필드 전수 적용 |
| 키보드 네비게이션 지원 | 필수 | Tab 포커스, Enter/Space 동작 |
| 색상 대비 4.5:1 이상 | 필수 | 다크/라이트 모드 양쪽 검증 |
| 들여쓰기 2 spaces | 필수 | TSX 파일 전체 |
| 따옴표 single quote | 필수 | import, string literal |
| 세미콜론 없음 | 필수 | TypeScript/TSX 전체 |
| 주석 한국어 | 필수 | 코드 주석 |
| CSS 방법론: BEM | 조건부 | Tailwind를 사용하므로 BEM className은 불필요. 단, Tailwind로 표현 불가한 CSS가 있을 때 SCSS + BEM 적용 |
| 전처리기: SCSS | 조건부 | Tailwind 외 추가 CSS 필요 시 SCSS 사용 |

> 주의: STACK.md에 "내부 도구이므로 BEM/SCSS 예외 가능"이라는 주석이 있으나, CLAUDE.md가 이를 명시적으로 오버라이드하지 않으므로 Tailwind CSS가 기본, SCSS는 Tailwind 불가 시 보조 도구로 사용한다.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react | 19.2.4 | UI 프레임워크 | D-01 잠금 결정. Concurrent 기능으로 실시간 로그 렌더링 최적화 |
| react-dom | 19.2.4 | React DOM 렌더러 | react와 동일 버전 필수 |
| vite | 8.0.3 | 빌드/개발 서버 | D-01 잠금 결정. HMR 속도 최고, npm create vite 스캐폴드 제공 |
| @vitejs/plugin-react | 6.0.1 | Vite React SWC 플러그인 | React 19와 함께 공식 권장 |
| tailwindcss | 4.2.2 | 스타일링 | D-02 잠금 결정. Vite 4.x는 PostCSS 불필요, @tailwindcss/vite 플러그인으로 직접 통합 |
| @tailwindcss/vite | 4.x | Tailwind Vite 플러그인 | Tailwind v4 전용 Vite 통합, tailwind.config.js 불필요 |
| @xyflow/react | 12.10.2 | DAG 시각화 | D-03 잠금 결정. React Flow의 최신 패키지명 (구: reactflow). v12부터 @xyflow/react로 이전 |
| typescript | 6.0.2 | 타입 안전성 | WebSocket 메시지 타입 안전성, 백엔드 Pydantic 스키마와 정렬 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| zustand | 5.0.12 | 전역 상태 관리 | 에이전트 상태 보드, 작업 목록, 로그 버퍼 등 앱 전역 상태 |
| react-use-websocket | 4.13.0 | WebSocket 훅 | /ws/logs 연결. 재연결 로직 내장, readyState 관리 자동화 |
| @tanstack/react-query | 5.96.1 | 서버 상태 캐싱 | REST API 폴링 (작업 목록, 파일 트리). WebSocket과 병행 |
| react-markdown | 10.1.0 | 마크다운 렌더링 | 산출물 .md 파일 렌더링. remark/rehype 플러그인 에코시스템 풍부 |
| shiki | 4.0.2 | 코드 구문 강조 | 산출물 코드 파일 렌더링. VS Code 동일 테마 시스템, 번들 크기 최소화 가능 |
| vitest | 4.1.2 | 프론트엔드 단위 테스트 | Vite 설정 공유, Jest 대체. 컴포넌트 및 유틸 함수 테스트 |
| @testing-library/react | 16.3.2 | React 컴포넌트 테스트 | vitest와 함께 사용, DOM 기반 테스트 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| @xyflow/react v12 | reactflow v11 | reactflow v11은 레거시. @xyflow/react로 마이그레이션 완료. v12에서 React 19 지원 |
| shiki | @monaco-editor/react | Monaco는 번들 크기 3MB+로 과중. 읽기 전용 뷰어에 shiki가 적합 |
| react-markdown | marked + DOMPurify | react-markdown이 XSS 방지 기본 내장, React 컴포넌트 커스터마이징 용이 |
| zustand | @tanstack/react-query만 사용 | WebSocket 이벤트 버퍼는 서버 상태가 아닌 클라이언트 상태라 zustand 필요 |
| react-use-websocket | native WebSocket | 재연결, 하트비트, readyState 직접 구현 불필요 |

**Installation:**
```bash
# dashboard/ 디렉토리 초기화
npm create vite@latest dashboard -- --template react-ts
cd dashboard

# 핵심 의존성
npm install @xyflow/react zustand react-use-websocket @tanstack/react-query react-markdown shiki

# Tailwind v4 (Vite 플러그인 방식)
npm install tailwindcss @tailwindcss/vite

# 개발 의존성
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

**Version verification (2026-04-03 기준 npm registry 확인):**
- react: 19.2.4
- vite: 8.0.3
- @xyflow/react: 12.10.2 (구 reactflow 11.11.4와 별개 패키지)
- tailwindcss: 4.2.2
- zustand: 5.0.12
- react-use-websocket: 4.13.0
- @tanstack/react-query: 5.96.1
- react-markdown: 10.1.0
- shiki: 4.0.2
- vitest: 4.1.2

---

## Backend API 분석 (실제 코드 기반)

### 존재하는 엔드포인트

| 엔드포인트 | 메서드 | 요청 스키마 | 응답 스키마 | 상태 |
|-----------|--------|-----------|-----------|------|
| `/health` | GET | — | `{ status, log_bus_subscribers }` | 구현 완료 |
| `/api/tasks` | POST | `{ instruction: str }` | `{ task_id: str, status: 'accepted' }` | 구현 완료 |
| `/api/tasks/{task_id}` | GET | path param | `{ task_id, state: WorkflowState }` | 구현 완료 |
| `/ws/logs` | WS | — | LogEvent JSON 스트림 | 구현 완료 |

### 누락된 엔드포인트 (이 Phase에서 추가 필요)

| 엔드포인트 | 메서드 | 용도 | 요구사항 |
|-----------|--------|-----|---------|
| `/api/tasks` | GET | 전체 작업 목록 조회 (DASH-05) | active_tasks dict 직렬화 |
| `/api/workspace/{task_id}/files` | GET | 파일 트리 조회 (DASH-04) | workspace/{task_id}/ 디렉토리 목록 |
| `/api/workspace/{task_id}/files/{path:path}` | GET | 파일 내용 조회 (DASH-04) | 파일 읽기, MIME 타입 감지 |
| `/api/tasks/{task_id}/dag` | GET | DAG 상태 조회 (WKFL-05) | TaskGraph.to_state_dict() 직렬화 |

### WebSocket LogEvent 스키마 (server/log_bus/event_bus.py에서 확인)

```typescript
// LogEvent — /ws/logs에서 수신하는 이벤트 타입
interface LogEvent {
  id: string           // UUID
  agent_id: string     // 'planner' | 'developer' | 'designer' | 'qa' | 'orchestrator'
  event_type: string   // 'log' | 'status_change' | 'task_start' | 'task_done' | 'error'
  message: string
  data: Record<string, unknown>
  timestamp: string    // ISO 8601
}
```

### WorkflowState 값 (server/orchestration/loop.py에서 확인)

```typescript
// WorkflowState — 오케스트레이션 상태 열거형
type WorkflowState =
  | 'idle'
  | 'claude_analyzing'
  | 'planner_planning'
  | 'worker_executing'
  | 'qa_reviewing'
  | 'claude_final_verifying'
  | 'revision_looping'
  | 'completed'
  | 'escalated'
```

### TaskGraph.to_state_dict() 출력 구조 (server/orchestration/task_graph.py에서 확인)

```typescript
// to_state_dict() 반환값 — React Flow 변환 전 원본
interface TaskStateDict {
  [task_id: string]: {
    task_id: string
    description: string
    requirements: string
    assigned_to: string    // 'planner' | 'developer' | 'designer' | 'qa'
    depends_on: string[]   // 의존 task_id 목록
    status: 'pending' | 'processing' | 'done' | 'failed' | 'blocked'
    artifact_paths: string[]
    failure_reason: string | null
  }
}
```

---

## Architecture Patterns

### Recommended Project Structure

```
dashboard/
├── src/
│   ├── api/
│   │   ├── client.ts           # fetch 래퍼 (base URL, 에러 처리)
│   │   ├── tasks.ts            # POST /api/tasks, GET /api/tasks
│   │   ├── workspace.ts        # GET /api/workspace 파일 API
│   │   └── dag.ts              # GET /api/tasks/{id}/dag
│   ├── hooks/
│   │   ├── useLogStream.ts     # react-use-websocket 기반 로그 스트림
│   │   ├── useTasks.ts         # @tanstack/react-query 기반 작업 목록
│   │   └── useTheme.ts         # 다크/라이트 모드 토글
│   ├── store/
│   │   ├── logStore.ts         # zustand: 로그 버퍼 (최대 N개)
│   │   ├── agentStore.ts       # zustand: 에이전트별 최신 상태
│   │   └── taskStore.ts        # zustand: 제출된 작업 지시 목록
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx    # 전체 레이아웃 (사이드바 + 메인)
│   │   │   └── ThemeToggle.tsx # 다크/라이트 토글 버튼
│   │   ├── task/
│   │   │   ├── TaskInput.tsx   # 작업 지시 입력 폼 (DASH-01)
│   │   │   └── TaskHistory.tsx # 지시 내역 목록 (DASH-05)
│   │   ├── agent/
│   │   │   └── AgentBoard.tsx  # 에이전트 상태 카드 (DASH-02)
│   │   ├── log/
│   │   │   └── LogStream.tsx   # 실시간 로그 뷰 (DASH-03)
│   │   ├── dag/
│   │   │   ├── DagView.tsx     # React Flow 래퍼 (WKFL-05)
│   │   │   ├── TaskNode.tsx    # 커스텀 노드 컴포넌트
│   │   │   └── dagAdapter.ts   # to_state_dict → nodes/edges 변환
│   │   └── artifact/
│   │       ├── ArtifactPanel.tsx  # 파일 트리 + 뷰어 (DASH-04)
│   │       ├── FileTree.tsx
│   │       └── FileViewer.tsx  # 코드/마크다운 렌더링
│   ├── types/
│   │   ├── api.ts              # 백엔드 API 타입 정의
│   │   └── events.ts           # LogEvent, WorkflowState 타입
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css               # Tailwind 임포트 (@import 'tailwindcss')
├── vite.config.ts
├── tsconfig.json
└── package.json
```

### Pattern 1: WebSocket 로그 수신 + zustand 버퍼

```typescript
// Source: react-use-websocket v4 공식 패턴
// hooks/useLogStream.ts
import useWebSocket, { ReadyState } from 'react-use-websocket'
import { useLogStore } from '../store/logStore'
import type { LogEvent } from '../types/events'

export function useLogStream() {
  const addLog = useLogStore(s => s.addLog)
  const setAgentState = useLogStore(s => s.setAgentState)

  const { readyState } = useWebSocket('ws://localhost:8000/ws/logs', {
    onMessage: (event) => {
      const log: LogEvent = JSON.parse(event.data)
      addLog(log)
      if (log.event_type === 'status_change') {
        setAgentState(log.agent_id, log.message)
      }
    },
    shouldReconnect: () => true,  // 새로고침 후 자동 재연결
    reconnectInterval: 1500,
    reconnectAttempts: 20,
  })

  return { readyState, isConnected: readyState === ReadyState.OPEN }
}
```

### Pattern 2: TaskGraph.to_state_dict() → React Flow 변환

```typescript
// components/dag/dagAdapter.ts
import type { Node, Edge } from '@xyflow/react'
import type { TaskStateDict } from '../../types/api'

const STATUS_COLORS: Record<string, string> = {
  pending: '#6b7280',     // gray
  processing: '#3b82f6',  // blue
  done: '#22c55e',        // green
  failed: '#ef4444',      // red
  blocked: '#f59e0b',     // amber
}

export function adaptToFlow(state: TaskStateDict): {
  nodes: Node[]
  edges: Edge[]
} {
  const nodes: Node[] = Object.values(state).map((task, i) => ({
    id: task.task_id,
    type: 'taskNode',          // 커스텀 노드 타입
    position: { x: i * 200, y: 0 },  // 초기 위치 (dagre 레이아웃으로 개선 가능)
    data: {
      label: task.description,
      status: task.status,
      assignedTo: task.assigned_to,
      color: STATUS_COLORS[task.status],
    },
  }))

  const edges: Edge[] = Object.values(state).flatMap(task =>
    task.depends_on.map(depId => ({
      id: `${depId}-${task.task_id}`,
      source: depId,
      target: task.task_id,
      animated: task.status === 'processing',
    }))
  )

  return { nodes, edges }
}
```

### Pattern 3: Tailwind v4 + 다크 모드 설정

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
```

```css
/* src/index.css — Tailwind v4 */
@import 'tailwindcss';

@theme {
  /* 다크 모드 CSS 변수 */
  --color-bg-primary: #0f172a;
  --color-bg-secondary: #1e293b;
}
```

```typescript
// hooks/useTheme.ts — 다크/라이트 모드 토글
import { useState, useEffect } from 'react'

export function useTheme() {
  const [isDark, setIsDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches
  )

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    localStorage.setItem('theme', isDark ? 'dark' : 'light')
  }, [isDark])

  return { isDark, toggle: () => setIsDark(p => !p) }
}
```

### Pattern 4: 산출물 파일 뷰어 (shiki + react-markdown)

```typescript
// components/artifact/FileViewer.tsx
import { codeToHtml } from 'shiki'
import ReactMarkdown from 'react-markdown'

// 코드 파일 — shiki로 구문 강조
async function renderCode(content: string, lang: string): Promise<string> {
  return codeToHtml(content, {
    lang,
    theme: 'github-dark',   // 다크 모드
  })
}

// 마크다운 파일 — react-markdown으로 렌더링
function MarkdownViewer({ content }: { content: string }) {
  return <ReactMarkdown>{content}</ReactMarkdown>
}
```

### Pattern 5: 로그 복구 (새로고침 후)

새로고침 시 WebSocket 재연결로 신규 이벤트는 수신하나, 이전 로그는 유실된다. 현재 백엔드 EventBus는 in-memory이므로 히스토리를 제공하지 않는다. 두 가지 접근:

1. **sessionStorage 활용 (권장):** 로그를 sessionStorage에 저장하여 새로고침 후 복원. 탭 종료 시 자동 삭제.
2. **백엔드 히스토리 API 추가:** EventBus에 히스토리 버퍼를 추가하고 `GET /api/logs/history` 엔드포인트 제공. 더 정확하나 백엔드 수정 필요.

**권장: sessionStorage 방식** — 백엔드 변경 없이 구현 가능. zustand persist 미들웨어의 storage를 sessionStorage로 지정.

```typescript
// store/logStore.ts
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { LogEvent } from '../types/events'

const MAX_LOGS = 500

interface LogStore {
  logs: LogEvent[]
  addLog: (log: LogEvent) => void
  clear: () => void
}

export const useLogStore = create<LogStore>()(
  persist(
    (set) => ({
      logs: [],
      addLog: (log) =>
        set(s => ({
          logs: [...s.logs.slice(-(MAX_LOGS - 1)), log],
        })),
      clear: () => set({ logs: [] }),
    }),
    {
      name: 'ai-office-logs',
      storage: createJSONStorage(() => sessionStorage),  // 탭 종료 시 삭제
    }
  )
)
```

### Anti-Patterns to Avoid

- **`reactflow` 패키지 사용:** v11 레거시 패키지. `@xyflow/react` v12를 사용한다.
- **WebSocket 재연결 직접 구현:** react-use-websocket에 내장된 재연결 로직을 사용한다.
- **로그를 컴포넌트 local state로 관리:** zustand store로 분리해야 컴포넌트 언마운트 시 유실되지 않는다.
- **`style={}` 인라인 스타일:** CLAUDE.md 금지 규칙. Tailwind 클래스 사용.
- **`!important` Tailwind 클래스:** `!` 접두사 Tailwind 유틸리티는 `!important`를 생성하므로 사용 금지.
- **Tailwind v4에서 `tailwind.config.js` 생성:** v4는 CSS-first 설정. `@theme {}` 블록을 CSS에서 직접 정의.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket 재연결 로직 | 커스텀 재연결 훅 | react-use-websocket | 지수 백오프, 하트비트, readyState 관리 모두 내장 |
| DAG 레이아웃 계산 | 의존성 기반 노드 위치 직접 계산 | @xyflow/react 내장 레이아웃 또는 dagre | 위상 정렬 + 레이아웃 알고리즘 구현은 비범해서 오류 빈발 |
| 코드 구문 강조 파서 | 언어별 파서 직접 구현 | shiki | 언어 지원, 테마 시스템, HTML escape 모두 처리됨 |
| 마크다운 → HTML 변환 | 정규식 기반 변환 | react-markdown | XSS, 중첩 구조, 특수 문자 처리가 매우 복잡 |
| 전역 상태 동기화 | Context API + useReducer 직접 조합 | zustand | WebSocket 이벤트로 상태 업데이트 시 Context re-render 성능 문제 |
| 서버 상태 캐싱 | 수동 fetch + state + 폴링 | @tanstack/react-query | 중복 요청 제거, 캐시 무효화, 로딩/에러 상태 자동 관리 |

**Key insight:** 실시간 대시보드는 재연결, 버퍼링, 상태 동기화가 얽혀 있어 라이브러리 없이 구현 시 엣지 케이스가 급증한다.

---

## Common Pitfalls

### Pitfall 1: @xyflow/react vs reactflow 패키지 혼동
**What goes wrong:** `npm install reactflow`로 설치 시 v11(레거시) 설치됨. React 19와 호환 문제 발생.
**Why it happens:** 패키지명이 v12에서 `@xyflow/react`로 변경되었으나 구 패키지도 여전히 npm에 존재.
**How to avoid:** 반드시 `npm install @xyflow/react` 사용. import도 `from '@xyflow/react'`.
**Warning signs:** `from 'reactflow'` import가 보이면 레거시.

### Pitfall 2: Tailwind v4 설정 방식 변경
**What goes wrong:** `tailwind.config.js` 생성, `content` 배열 설정, PostCSS 설정 시도 → v4에서 불필요하거나 충돌.
**Why it happens:** Tailwind v3 방식으로 구성 시도.
**How to avoid:** v4는 `@tailwindcss/vite` 플러그인만 추가하면 된다. CSS 파일에 `@import 'tailwindcss'`. 커스텀 색상은 `@theme {}` 블록.
**Warning signs:** PostCSS 관련 에러, `content is undefined` 경고.

### Pitfall 3: WebSocket CORS — Vite proxy 미설정
**What goes wrong:** 브라우저에서 `ws://localhost:8000/ws/logs`로 직접 연결 시 개발 환경에서 문제 없으나, 빌드 배포 시 origin 불일치.
**Why it happens:** Vite dev server가 8000포트 FastAPI를 프록시하지 않으면 개발/프로덕션 URL이 달라짐.
**How to avoid:** `vite.config.ts`에 proxy 설정 (`/api` → `http://localhost:8000`, `/ws` → `ws://localhost:8000` with `ws: true`).

### Pitfall 4: @xyflow/react CSS 미임포트
**What goes wrong:** DAG 뷰가 렌더링되지 않거나 레이아웃이 깨짐.
**Why it happens:** React Flow는 필수 CSS를 별도 임포트해야 함.
**How to avoid:** `import '@xyflow/react/dist/style.css'` 반드시 포함.

### Pitfall 5: zustand persist + sessionStorage 크기 초과
**What goes wrong:** 로그가 많아지면 sessionStorage 5MB 한도 초과 → quota exceeded 에러.
**Why it happens:** 로그 이벤트 수 무제한 누적.
**How to avoid:** `MAX_LOGS = 500`으로 제한. addLog에서 slice(-MAX_LOGS).

### Pitfall 6: react-markdown XSS 에이전트 출력
**What goes wrong:** 에이전트 생성 마크다운에 악성 HTML 포함 가능.
**Why it happens:** react-markdown 기본 설정은 raw HTML을 렌더링하지 않으나, `rehype-raw` 플러그인 추가 시 노출.
**How to avoid:** `rehype-raw` 플러그인 사용 금지. 기본 react-markdown만 사용.

### Pitfall 7: DAG 데이터 폴링 vs WebSocket 이벤트
**What goes wrong:** DAG 상태를 폴링으로만 업데이트 시 지연 발생. WebSocket status_change 이벤트와 불일치.
**Why it happens:** 두 데이터 소스가 독립적으로 업데이트.
**How to avoid:** WebSocket의 `task_done`/`status_change` 이벤트 수신 시 `GET /api/tasks/{id}/dag`를 React Query로 즉시 invalidate.

---

## Code Examples

### WebSocket 연결 + 에이전트 상태 파생

```typescript
// types/events.ts
export interface LogEvent {
  id: string
  agent_id: 'planner' | 'developer' | 'designer' | 'qa' | 'orchestrator'
  event_type: 'log' | 'status_change' | 'task_start' | 'task_done' | 'error'
  message: string
  data: Record<string, unknown>
  timestamp: string
}

export type WorkflowState =
  | 'idle' | 'claude_analyzing' | 'planner_planning' | 'worker_executing'
  | 'qa_reviewing' | 'claude_final_verifying' | 'revision_looping'
  | 'completed' | 'escalated'
```

### 작업 지시 제출 API

```typescript
// api/tasks.ts
interface TaskRequest {
  instruction: string
}

interface TaskResponse {
  task_id: string
  status: 'accepted'
}

export async function submitTask(instruction: string): Promise<TaskResponse> {
  const res = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction }),
  })
  if (!res.ok) throw new Error(`태스크 제출 실패: ${res.status}`)
  return res.json()
}
```

### React Flow 커스텀 노드

```typescript
// components/dag/TaskNode.tsx
import { Handle, Position, type NodeProps } from '@xyflow/react'

interface TaskNodeData {
  label: string
  status: string
  assignedTo: string
  color: string
}

export function TaskNodeComponent({ data }: NodeProps<TaskNodeData>) {
  return (
    <div
      className='rounded-lg border-2 p-3 min-w-32 text-sm'
      style={{ borderColor: data.color }}
      role='listitem'
      aria-label={`태스크: ${data.label}, 상태: ${data.status}`}
    >
      <Handle type='target' position={Position.Left} />
      <div className='font-medium truncate'>{data.label}</div>
      <div className='text-xs opacity-70'>{data.assignedTo}</div>
      <Handle type='source' position={Position.Right} />
    </div>
  )
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `reactflow` 패키지 | `@xyflow/react` 패키지 | v12 (2024) | import 경로 변경 필수 |
| Tailwind v3 + PostCSS + tailwind.config.js | Tailwind v4 + @tailwindcss/vite | v4 (2025) | 설정 파일 불필요, CSS-first 설정 |
| React 18 + createRoot | React 19 + createRoot (동일) | React 19 (2024) | Concurrent 기능 기본 활성화 |
| zustand v4 | zustand v5 (immer 기본 내장) | 2024 | 불변성 업데이트 문법 변화 없음 |

**Deprecated/outdated:**
- `reactflow` v11: `@xyflow/react` v12로 이전. 구 패키지는 유지보수 종료.
- Tailwind `purge` 옵션: v3에서 `content`로 이름 변경, v4에서 불필요.
- `react-use-websocket` v3: v4에서 API 변경됨. `sendMessage` 대신 `sendJsonMessage` 권장.

---

## Open Questions

1. **DAG 데이터 실시간 업데이트 메커니즘**
   - What we know: `/api/tasks/{id}/dag` 엔드포인트는 이 Phase에서 추가 예정. WebSocket으로 상태 변경 이벤트가 옴.
   - What's unclear: OrchestrationLoop의 _task_graph이 in-memory이므로, 루프 종료 후에도 상태 유지되는지 확인 필요.
   - Recommendation: `app.state.orch_loop._task_graph`를 직렬화하는 엔드포인트 추가. WebSocket `task_done` 이벤트 수신 시 React Query invalidate.

2. **DAG 레이아웃 자동 배치**
   - What we know: React Flow는 초기 노드 위치를 수동 지정해야 함. 의존성 기반 계층 배치가 가능.
   - What's unclear: dagre 라이브러리(`@dagrejs/dagre`) 추가 여부. 태스크가 5개 이하라면 수동 배치도 충분.
   - Recommendation: 초기 구현은 수동 배치 (tasks 수가 적음). 복잡해지면 dagre 추가.

3. **workspace 파일 보안**
   - What we know: WorkspaceManager의 `safe_path`가 심볼릭 링크 우회를 방지함 (Phase 1 결정).
   - What's unclear: 파일 내용 조회 API에서 같은 보안 로직 재사용 여부.
   - Recommendation: `GET /api/workspace/{task_id}/files/{path}` 구현 시 WorkspaceManager.safe_path 활용. FastAPI에서 직접 Path 조작 금지.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Vite 빌드 서버 | ✓ | v22.21.1 | — |
| npm | 패키지 설치 | ✓ | 10.9.4 | — |
| Python / FastAPI 서버 | 백엔드 API | ✓ (Phase 1-3 완료) | — | — |

**Missing dependencies with no fallback:** 없음.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | vitest 4.1.2 + @testing-library/react 16.3.2 |
| Config file | `dashboard/vite.config.ts` (test 섹션 추가) |
| Quick run command | `cd dashboard && npm run test` |
| Full suite command | `cd dashboard && npm run test -- --run` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DASH-01 | TaskInput 폼 제출 → POST /api/tasks 호출 | unit (msw mock) | `vitest run src/components/task/TaskInput.test.tsx` | Wave 0 |
| DASH-02 | LogEvent 수신 → 에이전트 상태 카드 업데이트 | unit | `vitest run src/store/agentStore.test.ts` | Wave 0 |
| DASH-03 | WebSocket 메시지 수신 → 로그 버퍼 추가 | unit | `vitest run src/hooks/useLogStream.test.ts` | Wave 0 |
| DASH-04 | 파일 확장자 → 올바른 뷰어(코드/마크다운) 분기 | unit | `vitest run src/components/artifact/FileViewer.test.tsx` | Wave 0 |
| DASH-05 | 작업 지시 제출 후 목록에 표시 | unit | `vitest run src/components/task/TaskHistory.test.tsx` | Wave 0 |
| WKFL-05 | to_state_dict 출력 → nodes/edges 변환 | unit | `vitest run src/components/dag/dagAdapter.test.ts` | Wave 0 |

### Sampling Rate

- **Per task commit:** `cd dashboard && npm run test -- --run`
- **Per wave merge:** `cd dashboard && npm run test -- --run`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `dashboard/src/components/task/TaskInput.test.tsx` — DASH-01
- [ ] `dashboard/src/store/agentStore.test.ts` — DASH-02
- [ ] `dashboard/src/hooks/useLogStream.test.ts` — DASH-03
- [ ] `dashboard/src/components/artifact/FileViewer.test.tsx` — DASH-04
- [ ] `dashboard/src/components/task/TaskHistory.test.tsx` — DASH-05
- [ ] `dashboard/src/components/dag/dagAdapter.test.ts` — WKFL-05
- [ ] `dashboard/src/test/setup.ts` — @testing-library/jest-dom setup
- [ ] vitest 설정: `dashboard/vite.config.ts`에 test 섹션 추가
- [ ] 프레임워크 설치: `npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom`

---

## Sources

### Primary (HIGH confidence)

- `server/main.py` — FastAPI 엔드포인트 직접 코드 분석
- `server/orchestration/loop.py` — WorkflowState enum 8개 값 직접 확인
- `server/orchestration/task_graph.py` — to_state_dict() 출력 구조 직접 확인
- `server/log_bus/event_bus.py` — LogEvent 스키마, EventBus 동작 직접 확인
- npm registry (2026-04-03) — react 19.2.4, vite 8.0.3, @xyflow/react 12.10.2, tailwindcss 4.2.2 등 버전 실측

### Secondary (MEDIUM confidence)

- `.planning/research/STACK.md` — 프로젝트 스택 사전 조사 결과 활용
- @xyflow/react npm 패키지 정보 — reactflow v11과의 패키지 분리 확인

### Tertiary (LOW confidence)

- Training data: dagre 레이아웃 통합 패턴 — 버전 검증 없이 패턴만 참조

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — npm registry에서 실제 버전 확인
- Architecture: HIGH — 백엔드 코드 직접 분석하여 API 계약 파악
- Pitfalls: HIGH — @xyflow/react 패키지명 변경, Tailwind v4 설정 변경 모두 실측 기반

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (30일 — React Flow, Tailwind v4 안정 릴리스)
