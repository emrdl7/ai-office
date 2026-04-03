# Milestones

## v1.0 MVP (Shipped: 2026-04-03)

**Phases completed:** 4 phases, 15 plans, 23 tasks

**Key accomplishments:**

- uv Python 3.12 환경 + FastAPI/SQLModel/pytest 의존성 + 전체 컴포넌트 stub 트리 + 15개 xfail 테스트 scaffold 구축
- SQLite WAL 모드 기반 MessageBus(publish/consume/ack)와 get_connection/init_schema 구현 — 5개 pytest 모두 PASSED
- WorkspaceManager로 태스크별 격리 atomic write 구현, Gemma4 JSON 불안정 대응 2-pass 파서 추가 — 15개 테스트 전부 PASSED
- One-liner:
- asyncio.Queue 기반 단일 워커 Ollama HTTP 클라이언트 구현 — format:json 파라미터로 gemma4:26b 구조화 출력 요청, 동시 요청을 직렬화하여 메모리 스래싱 방지
- asyncio.Queue 기반 in-process EventBus와 FastAPI /ws/logs WebSocket 엔드포인트로 에이전트 이벤트를 폴링 없이 대시보드에 실시간 브로드캐스트하는 인프라 완성
- TaskRequestPayload/TaskResultPayload/StatusUpdatePayload Pydantic 스키마 + 4개 에이전트 시스템 프롬프트 파일 + 19개 xfail 테스트 stub으로 Phase 2 구현 계약 완성
- 인메모리 DAG TaskGraph(add_task/ready_tasks/update_status/all_done)와 기획자 broadcast 복사가 자동 발행되는 MessageRouter를 구현하여 오케스트레이션 루프(Plan 03)의 핵심 의존성 완성
- 1. [Rule 1 - Bug] mock patch 경로 수정
- POST /api/tasks 엔드포인트와 OrchestrationLoop 싱글턴을 FastAPI lifespan에 연결, 에이전트 프롬프트 테스트 57개 전부 GREEN
- server/agents/designer.md
- 에이전트별 JSON 파일 기반 경험 메모리 모듈(AgentMemory + MemoryRecord) — atomic write + lazy compaction으로 data/memory/{agent}_memory.json 저장 및 관리
- AgentMemory를 OrchestrationLoop 세 지점(_run_agent/QA/Claude검증)에 통합하여 에이전트 경험 자동 주입·기록 완성
- 1. [Plan Design] 04-01-PLAN.md를 실행 전에 생성
- FastAPI server/main.py에 대시보드용 6개 신규 엔드포인트(DAG/파일/에이전트/로그히스토리/태스크목록)와 CORSMiddleware(localhost:5173) 추가

---
