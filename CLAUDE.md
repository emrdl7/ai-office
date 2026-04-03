<!-- GSD:project-start source:PROJECT.md -->
## Project

**AI Office**

AI 구성원들이 역할을 나눠 유기적으로 협업하는 범용 작업 시스템. 사용자가 프로젝트를 지시하면 Claude(팀장)가 진행방향을 제시하고 Gemma4 기반 구성원들(기획자, 디자이너, 개발자, QA)이 실무를 수행하며, 전 과정을 웹 대시보드에서 모니터링할 수 있다.

**Core Value:** 사용자의 지시 하나로 AI 구성원들이 자율적으로 협업하여 실제 결과물(파일)을 만들어내는 것.

### Constraints

- **AI 런타임**: Claude = CLI (API 없음), Gemma4 = Ollama 로컬
- **인프라**: 모두 로컬 머신에서 실행 (macOS)
- **통신**: 구성원 간 통신은 로컬에서 해결 (외부 서비스 없음)
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12 | 에이전트 오케스트레이터 런타임 | 3.12는 성능 개선 및 FastAPI 0.130+가 요구하는 3.10+ 중 안정적 선택. 비동기 처리(asyncio)와 subprocess 관리가 성숙해 에이전트 프로세스 관리에 적합 |
| FastAPI | 0.135.x | 백엔드 API + WebSocket 서버 | Python 비동기 프레임워크 중 WebSocket 네이티브 지원이 가장 성숙함. 대시보드 REST API와 실시간 로그 스트리밍을 단일 프로세스로 처리 가능. Pydantic 내장으로 에이전트 메시지 스키마 검증 무료 |
| CrewAI | 1.13.0 | 다중 에이전트 역할 기반 오케스트레이션 | 역할(Role) + 목표(Goal) 추상화가 이 프로젝트의 "팀장/기획자/디자이너/개발자/QA" 구조와 정확히 일치. Ollama 로컬 모델을 LiteLLM 경유로 네이티브 지원. CrewAI = 빠른 팀 구성, LangGraph보다 진입 장벽 낮음 |
| Ollama Python SDK | 0.6.1 | Gemma4 로컬 모델 호출 클라이언트 | 공식 Python 클라이언트. OpenAI 호환 엔드포인트(`/v1/`)로 CrewAI의 LiteLLM이 `ollama/gemma4` 모델 식별자로 직접 연결 가능. REST API 폴백도 지원 |
| SQLite (via SQLModel) | 0.0.x (최신) | 작업 상태·큐·로그 영구 저장 | 외부 서버 불필요. WAL 모드로 다중 에이전트 동시 읽기/쓰기 안전. SQLModel은 Pydantic + SQLAlchemy 결합이라 FastAPI 스키마와 DB 모델을 공유 가능 |
| React + Vite + TypeScript | React 19 / Vite 6 | 웹 대시보드 프론트엔드 | Vite는 로컬 개발 HMR 속도 최고. TypeScript로 WebSocket 메시지 타입 안정성 확보. React 19의 Concurrent 기능은 실시간 로그 렌더링에 유리 |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uvicorn` | 0.34.x | FastAPI ASGI 서버 | FastAPI 실행 전용. `--reload` 플래그로 개발 중 자동 재시작 |
| `python-multipart` | 최신 | FastAPI 파일 업로드 지원 | 산출물(artifact) 파일 수신 시 필요 |
| `pydantic-settings` | 2.x | 환경 설정 관리 | `.env` 기반 포트/경로/모델 이름 설정 분리 |
| `httpx` | 0.28.x | 비동기 HTTP 클라이언트 | FastAPI 내부에서 Ollama REST API 직접 호출 시 사용 |
| `react-use-websocket` | 4.x | React WebSocket 훅 | 대시보드의 실시간 로그·상태 수신. 재연결 로직 내장으로 불안정한 로컬 연결에 안전 |
| `zustand` | 5.x | React 전역 상태 관리 | 에이전트 상태 보드, 작업 목록 등 대시보드 전역 상태. Redux보다 보일러플레이트 없음 |
| `@tanstack/react-query` | 5.x | 서버 상태 캐싱 + 폴링 | REST API 응답(작업 목록, 산출물 메타데이터) 캐싱. WebSocket과 병행 사용 |
| `tailwindcss` | 4.x | 대시보드 스타일링 | 로컬 대시보드는 BEM/SCSS 오버엔지니어링. Tailwind는 컴포넌트 단위 빠른 UI 구성에 최적 (단, 전역 CLAUDE.md 규칙은 일반 웹 프로젝트 기준이며, 이 대시보드 서브앱은 내부 도구이므로 예외 적용 가능) |
| `monaco-editor` (via `@monaco-editor/react`) | 4.x | 산출물 코드 뷰어 | 에이전트가 생성한 코드 파일을 구문 강조와 함께 브라우저에서 표시. VS Code 동일 엔진 |
| `crewai-tools` | 최신 | CrewAI 기본 도구 모음 | 에이전트에게 파일 읽기/쓰기, 검색 등 도구 제공 시 필요 |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| `uv` | Python 패키지 관리 + 가상환경 | pip보다 10-100x 빠름. `uv sync`로 lockfile 기반 재현 가능 환경 |
| `ruff` | Python 린터 + 포매터 | flake8 + black 대체. 설정 없이 즉시 사용 가능 |
| `vitest` | 프론트엔드 단위 테스트 | Vite와 동일 설정 공유. Jest 대체로 속도 빠름 |
| `pytest` + `pytest-asyncio` | 백엔드 테스트 | FastAPI 비동기 엔드포인트 테스트에 필수 |
| `ollama` CLI | 모델 다운로드 및 실행 관리 | `ollama pull gemma4:e4b`로 모델 사전 다운로드 |
## Installation
# Python 환경 (uv 사용 권장)
# 개발 의존성
# React 대시보드 (Vite 스캐폴드)
# Gemma4 모델 (macOS, 16GB RAM 기준 e4b 권장)
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| CrewAI | LangGraph | 세밀한 그래프 기반 흐름 제어, 체크포인팅, 인간-루프 인터럽트가 필수일 때. 이 프로젝트는 역할 기반 팀 구조라 CrewAI가 더 자연스러움 |
| CrewAI | AutoGen | 에이전트 간 대화형(conversational) 반복 협상이 주 패턴일 때. 이 프로젝트는 지시→실행→검수 선형 흐름이라 CrewAI로 충분 |
| SQLite + SQLModel | PostgreSQL + SQLAlchemy | 여러 머신 분산 실행, 10만 건 이상 로그 처리 필요 시. 로컬 단일 머신에서는 SQLite WAL 모드로 충분 |
| FastAPI WebSocket | Socket.IO | 방(room) 기반 멀티 클라이언트 브로드캐스트가 복잡할 때. 단일 대시보드 클라이언트에는 순수 WebSocket으로 충분 |
| React + Vite | Next.js | 서버사이드 렌더링, SEO, 다중 페이지 앱이 필요할 때. 로컬 내부 도구에는 불필요한 복잡도 |
| react-use-websocket | native WebSocket API | 라이브러리 의존성을 최소화해야 할 때. 재연결 로직 직접 구현 부담이 있음 |
| Tailwind CSS | SCSS + BEM | 공개 배포되는 브랜딩이 있는 사이트. 내부 대시보드는 BEM 오버엔지니어링 |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| LangChain (직접) | CrewAI + LangGraph이 LangChain 위에 구축되어 있어 내부적으로 사용됨. LangChain API 직접 노출 시 추상화 레이어 충돌 및 버전 불일치 위험 | CrewAI (LangChain을 내부에서 관리) |
| Redis | 로컬 단일 머신 환경에서 별도 데몬 설치 불필요. SQLite WAL이 같은 역할 수행 | SQLite with WAL mode |
| Celery | 분산 태스크 큐 과잉설계. 로컬 에이전트 프로세스 관리는 Python `subprocess` + SQLite 큐로 충분 | Python subprocess + SQLite task table |
| Anthropic Python SDK (직접 API 호출) | 프로젝트 제약: Claude는 CLI로만 동작. API 키 없이 Claude Code CLI를 subprocess로 실행해야 함 | `subprocess.Popen(['claude', ...])` + stdin/stdout 파이프 |
| Streamlit | 대화형 대시보드 프로토타이핑에는 빠르지만, 실시간 WebSocket + 커스텀 작업 지시 UI + 산출물 뷰어를 구현하려면 한계 명확 | React + Vite |
| Docker (v1 단계) | 로컬 macOS 개발에 Docker 오버헤드 불필요. 모든 컴포넌트가 macOS 네이티브로 실행 가능 | 직접 로컬 프로세스 실행 |
## Stack Patterns by Variant
- 8GB RAM: `gemma4:e2b` (7.2GB, 기능 제한)
- 16GB RAM: `gemma4:e4b` (9.6GB, 권장 — 에이전트 역할 분리에 충분)
- 32GB+ RAM: `gemma4:26b` (18GB, 고품질 결과 필요 시)
- 1단계 (파일 기반): 에이전트가 SQLite `tasks` 테이블에 작업 등록 → 다른 에이전트가 폴링하여 수령. 단순하고 디버깅 용이
- 2단계 (이벤트 기반, 필요 시 확장): FastAPI의 `asyncio.Queue`로 인메모리 브로드캐스트. Redis 없이 WebSocket 팬아웃 가능
# Claude Code를 subprocess로 실행, stdout 스트리밍
## Version Compatibility
| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `fastapi 0.135.x` | `Python 3.10+` (3.12 권장) | 0.130.0부터 Python 3.9 지원 종료 |
| `crewai 1.13.0` | `Python 3.10–3.13` | LiteLLM을 통해 `ollama/gemma4:e4b` 모델 식별자 사용 |
| `ollama 0.6.1` (Python) | `ollama CLI 0.9.x+` | Gemma4 모델은 Ollama CLI 최신 버전 필요. `ollama --version` 확인 |
| `sqlmodel` | `pydantic 2.x`, `sqlalchemy 2.x` | FastAPI와 같은 Pydantic 버전 사용해야 스키마 충돌 없음 |
| `react 19` | `react-use-websocket 4.x`, `zustand 5.x` | React 18에서는 `react-use-websocket 4.x` 동작하나, React 19 Concurrent 기능 활용하려면 업그레이드 권장 |
| `tailwindcss 4.x` | `vite 6.x` (`@tailwindcss/vite` 플러그인) | Tailwind 4는 PostCSS 설정 불필요, Vite 플러그인으로 직접 통합 |
## Sources
- [CrewAI PyPI 공식 페이지](https://pypi.org/project/crewai/) — 버전 1.13.0 확인 (2026-04-02 릴리스)
- [Ollama Python SDK PyPI](https://pypi.org/project/ollama/) — 버전 0.6.1 확인
- [Gemma4 Ollama 라이브러리](https://ollama.com/library/gemma4) — 모델 변형 및 용량 확인
- [FastAPI 릴리스 노트](https://fastapi.tiangolo.com/release-notes/) — 0.135.x, Python 3.10+ 요구사항 확인
- [CrewAI Ollama 연동 공식 문서](https://docs.crewai.com/en/learn/llm-connections) — LiteLLM 경유 로컬 모델 연결 방식
- [SQLite is the Best Database for AI Agents](https://dev.to/nathanhamlett/sqlite-is-the-best-database-for-ai-agents-and-youre-overcomplicating-it-1a5g) — WAL 모드 에이전트 상태 관리 패턴 (MEDIUM confidence, 단일 소스)
- [Claude Agent SDK Architecture](https://www.ksred.com/the-claude-agent-sdk-what-it-is-and-why-its-worth-understanding/) — Claude CLI subprocess 패턴 확인
- [Building Multi-Agent Systems with LangGraph and Ollama](https://medium.com/@diwakarkumar_18755/building-multi-agent-systems-with-langgraph-and-ollama-architectures-concepts-and-code-383d4c01e00c) — CrewAI vs LangGraph 트레이드오프 참고
- [CrewAI vs LangGraph comparison](https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared) — 프레임워크 비교 (MEDIUM confidence, 블로그 소스)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
