# TODOS

> **현재 상태 (2026-04-15, 341 commits)**
> - 앱 LOC: backend 14.4K / frontend 4.3K / tests 3.5K ≈ **22K total**.
> - office.py 603 LOC (시작 4,144 대비 −85%). 도메인 6분할 정착.
> - project_runner.py 1,711 LOC — 5 helper 추출 후 수치, 추가 분해 역효과 지점.
> - **핫스팟**: main.py **2,485 LOC / 46 엔드포인트 / 119 함수** (다음 분리 최우선).
> - 학습 루프 3종 가동: QA pushback → 팀장 중재 → rule draft /
>   dynamics 점수 기반 peer reviewer 자동 선정 / 회고 유기화(metrics+synthesis).
> - 통합 검색 API + SearchPanel UI 완성.
> - 최근 사고: `test_project_runner_e2e`가 log_store DB_PATH 격리 누락
>   → prod `data/logs.db` 오염 271건 + workspace 24 dir 누수.
>   conftest autouse fixture로 DB 격리 안전망 구축 (커밋 `e2c4620`).
>   `restore_pending_tasks`는 context_json 없는 running은 cancelled 처리
>   (커밋 `b2c3985`) — "어흥" 재시작 복구 오동작 수정.

---

## 🔥 P1 — main.py 라우터 분리 (최우선 위험)

`main.py` 2,485 LOC 단일 파일에 46개 REST 엔드포인트 + WS + 생명주기 훅.
책임 과적재: 인증, 파일 업로드, 검색, 건의, 대시보드 API, ws 브로드캐스트,
서버 재시작, MCP 등. 한 줄 바꾸려 해도 풀 파일 컨텍스트 필요.

**기준**: 기능 영역별 FastAPI `APIRouter` 분리. main.py는 앱 생성 +
미들웨어 + 라우터 include + 생명주기 훅만 남긴다 (<500 LOC 목표).

- [ ] `routes/suggestions.py` — 건의 CRUD + promote + events (~400 LOC 이관)
- [ ] `routes/search.py` — `/api/search` + `/api/suggestions` 리스트
- [ ] `routes/tasks.py` — chat + create_task + uploads + 파일 다운로드
- [ ] `routes/team.py` — `/api/agents` `/api/team` + reactions stats
- [ ] `routes/artifacts.py` — workspace/artifact 관련
- [ ] `routes/admin.py` — server restart, MCP 상태 등
- [ ] `routes/ws.py` — WebSocket + ws-token 엔드포인트
- [ ] **의존성**: `app.state.office`, `event_bus`, `logger` 공유 헬퍼 묶기
- [ ] 각 분리마다 E2E 회귀 — 대시보드 탭 전부 손수 확인 (또는 smoke test 추가)

**행동 변경 금지 원칙**: 순수 이관. 경로·응답 스키마·인증 미들웨어 동일.
기능 개선은 분리 후 별도 단계.

---

## 🛡️ P2 — 테스트/실행 격리 안전망 보강

오늘 prod DB 오염 사고 재발 방지 + 유사 누수 경로 차단.

- [ ] `workspace_root` 격리 — conftest autouse fixture에 추가.
      (이번 사고에서 workspace는 일부 테스트가 수동 격리했으나
      restore_pending_tasks 경로로 하드코딩 `Path(...) / 'workspace'`가
      prod 경로를 잡음. `WORKSPACE_ROOT` 상수화 후 주입 가능하게 리팩터.)
- [ ] CI에서 `data/*.db` 변경 감지 가드 — 테스트 후 git diff 체크.
- [ ] `memory_root` 기본값도 env 주입 가능하게 (TeamMemory 생성자는
      이미 인자 받지만 호출부 일부 하드코딩 — 점검).
- [ ] 테스트 155건 중 env 의존 실패군(fastapi/pydantic_core) 정리 —
      requirements 고정 or skip 마킹.

---

## 🧭 P3 — autonomous_loop 복잡도 완화

`autonomous_loop.py` 642 LOC — 무엇을 판단해 어떤 발화를 할지
조건 분기가 길다. 오늘 채팅 로그에서도 autonomous 경로에서
Claude 응답 끊김(exit=1) 재시도 로그 관찰.

- [ ] 루프 단계 분해: `_should_speak` / `_pick_speaker` /
      `_build_context` / `_generate_response` helper로 추출.
- [ ] 현재 조건 분기 결정 트리를 한 곳에서 읽을 수 있도록 문서 주석.
- [ ] 실패 경로(LLM 타임아웃/끊김) 재시도 정책 명문화 —
      현재 2회 재시도 후 `건의 #integ-01 Claude 오류` 이벤트만 남고
      다음 iteration까지 침묵. 사용자 관측성 낮음.

---

## 👀 P4 — 관측성/자가 진단

- [ ] 프로젝트 실행 중 진행 상태 엔드포인트 — 현재 어느 phase 몇 %인지
      프론트에서 볼 수 있는 `/api/project/status`.
- [ ] metrics.db — 누적 QA 합격률 / 평균 revision / phase별 평균 시간
      대시보드 패널(“자가개선 분석”이 이미 있으나 UI 미노출).
- [ ] 실패 이벤트 필터 — 통합 검색에 `event_type=error` 프리셋 추가.
- [ ] 오염 감지 — placeholder 문자열("초안 내용입니다" 등) 프로덕션
      유입 시 로그 레벨 warning으로 감지.

---

## 🌱 유기성 축 (상시 고려)

피처 제안·설계 시 **에이전트들이 서로 유기적으로 피드백·의견 주고받고
프로젝트를 능동적으로 처리하는 방향**을 항상 우선 검토.
`memory/feedback_team_organic.md` 메모리에 영구 저장됨.

이미 가동 중:
- QA 불합격 → peer 반박/지지/보강 → 팀장 중재 → 규칙 draft 학습.
- peer reviewer 자동 선정 (dynamics 점수 > 임계치면 경험 기반 선정).
- 회고 = 팀원 각자 메트릭 기반 교훈 + 팀장 종합 `retrospective.md`.

다음 확장 후보 (우선순위 낮음, P1~P3 이후 고려):
- 팀원 간 상호 회고 코멘트 ("X의 교훈은 내 다음 작업에 이렇게 적용")
- autonomous 시간대에 팀원끼리 사이드 프로젝트 시작 자율성.

---

## ✅ 최근 완료 (2026-04-15)

### 신규 피처
- **QA 피드백 루프** — `_qa_pushback_round` + `_file_qa_rule_suggestion`.
  불합격 → peer 2명 [지지/반박/보강] → 팀장 JSON 중재 (ADOPT/MODIFY/REJECT)
  → draft rule 등록 → 1h auto_promote → PromptEvolver.
- **Dynamics 기반 peer reviewer 선정** — `_select_peer_reviewers`.
  peer_approved +1 / committed_to_request +0.3 / peer_concern -0.5,
  신호 < 3 이면 하드코딩 매핑 폴백. 팀장 공지 emit으로 가시화.
- **회고 유기화** — `_build_agent_metrics_context` + `_synthesize_and_save_retrospective`.
  각 에이전트 회고에 QA/리비전/받은 피드백 요약 주입, 팀장이 3섹션
  마크다운 종합 → `workspace/retrospective.md`.
- **통합 검색** — `log_store.search_logs`, `list_suggestions` 확장,
  `/api/search?q=&type=logs|suggestions|dynamics|all`,
  `SearchPanel.tsx` Portal 모달 + 원본 점프.

### Polish
- `_auto_export` ZIP/PDF에 `retrospective.md` 포함.
- 프론트 `CATEGORY_LABEL`: 'QA 규칙' 외 라벨 4종 추가.
- `_peer_review` 진입 시 팀장이 선정된 리뷰어 공지.

### 사고 수습
- `conftest.py` autouse fixture로 prod DB 격리 안전망 (커밋 `e2c4620`).
- prod chat_logs 227건 + workspace 24 dir 삭제 (test 누수).
- `restore_pending_tasks` context_json 없는 running은 조용히 cancelled
  (커밋 `b2c3985`) — "어흥" 재시작 복구 오동작 해결.

### 테스트 (이번 세션 신규)
- `test_qa_pushback_loop` (ADOPT/REJECT/MODIFY 3)
- `test_peer_reviewer_selection` (폴백/점수/배제 3)
- `test_retrospective` (메트릭 컨텍스트 2 + artifact 저장 1)
- `test_search` (logs q/agent + suggestions category/q 4)
- 누적 regression 23/23 pass (env 의존 실패군 제외).

---

## 📦 이전 로드맵 (완료 누적 요약)

- 도메인 6분할 (teamlead_review / autonomous_loop / agent_interactions /
  project_runner / suggestion_filer / user_input).
- `_execute_project` 5 helper 추출.
- Draft 건의 + source_log_id + 1h 자동 승격 루프.
- 대시보드 📝 초안 탭 + 승격/철회 + `POST /api/suggestions/{id}/promote`.
- 메시지 버스 30일 아카이브 + chat_logs 10K/50MB 임계 자동 이관.
- REST 인증 미들웨어, patch_lock 브로드캐스트.
- 약한 엣지 3종 (_phase_intro 맥락 / _task_acknowledgment 우려 /
  _work_commentary ↔ _route_agent_mentions).
- 메타 학습 3종 (_summarize_team_dynamics 팀장 리뷰 주입 /
  _peer_review peer_concern 임계치 자동 건의 / `DYNAMIC_TYPES` 표준 어휘).
