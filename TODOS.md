# TODOS

> **현재 상태 (2026-04-15, 354 commits)**
> - 앱 LOC: server 14.3K / routes 2.5K / tests ~3.7K / frontend 4.3K ≈ **25K total**.
> - **main.py 328 LOC** (시작 4,144 → −92%). 8개 라우터 분리 완료.
> - `routes/`: admin·team·search·artifacts·logs·tasks·suggestion_branch·suggestions.
> - `project_runner.py` 1,711 LOC — 추가 분해 역효과 지점 판단 유지 (재검토 대상).
> - 학습 루프 3종 가동: QA pushback → 팀장 중재 → rule draft /
>   dynamics 기반 peer reviewer 자동 선정 / 회고 유기화(metrics+synthesis).
> - 통합 검색 API + SearchPanel UI + **errors preset** 필터 완성.
> - 관측: `/api/project/status` (state/phase/elapsed/nodes) + placeholder 오염 warning 감지.
> - 테스트: **169 pass / 0 fail / 5 skip**. CI 워크플로우 + `data/` 오염 가드.
> - 경로: `core/paths.py` 단일 출처 (WORKSPACE_ROOT / MEMORY_ROOT, env 주입).

---

## 🎨 P1 — 관측성 UI 노출 ✅ 완료

- [x] `ProjectStatusBar` — `/api/project/status` 2초 폴링, ChatRoom 상단에
      state/phase/agent/elapsed/rev/nodes 배너.
- [x] `MetricsPanel` — 사이드바 "자가개선 분석" 버튼 복귀. 누적 QA 합격률 /
      평균 revision / 평균 phase / 평균 소요 + 최근 8건.
- [x] SearchPanel `⚠ 에러만` 토글 — `preset=errors` 원클릭.
- [x] placeholder 오염 `system_notice` 2차 이벤트로 EventBus 공개 —
      원본 event id/pattern/preview 포함, 검색 에러 프리셋에서 즉시 확인.

---

## 🌱 P2 — 유기성 확장 (피처 설계 시 우선 고려축)

에이전트 간 유기적 피드백/자율성 확장. `memory/feedback_team_organic.md` 원칙.

- [x] 팀원 간 **상호 회고 코멘트** — 회고 후 라운드로빈으로 다른 팀원이
      "↳ X 교훈 반영: ..." 한 문장 연결. `lesson_applied` dynamic 기록.
- [ ] autonomous 시간대 **사이드 프로젝트** 자율성 — 팀원이 자발적으로
      소규모 개선을 건의 + 수행. 현재 건의 등록은 되지만 수행은 사용자 승인 후.
- [x] **dynamics 임계치 선제 중재** — peer_concern 3회 누적 시 팀장이
      채팅에 중재 메시지 즉시 발화 (기존 suggestion 등록 + 발화 추가).
      24h 쿨다운 공유.

---

## 🧹 P3 — 코드 건강성 남은 것

- [ ] `project_runner.py` 1,711 LOC 재검토 — P1 리팩터 경험으로 더 분해 가능한지
      (과거 판단은 "역효과 지점"이었으나 라우터 분리 선례로 임계치 달라졌을 수 있음).
- [ ] 스킵된 테스트 재작성 — `test_qa_gate`, `test_revision_loop`은
      `runners.gemma_runner` 제거 + Office 시그니처 변경으로 현재 skip.
      신규 흐름(`test_qa_pushback_loop`, `test_retrospective`)으로 커버되지만
      정식 재작성 가치 있음.
- [ ] **frontend 타입 정리** — dashboard 4.3K. 빠진 타입/any 잔존 점검.

---

## 🛡️ P4 — 안전망 강화 (선순위 낮음)

- [ ] CI에 `ruff check` + `mypy` 추가 — 현재 pytest + data/ 가드만.
- [ ] pytest fixture에 event_bus 격리 — 현재 직접 publish 가능 (DB는 격리됐으나 bus는).
- [ ] 프론트엔드 React 컴포넌트 테스트 — 현재 서버 쪽만 테스트.

---

## ✅ 이번 세션 완료 (2026-04-15, 13 커밋)

### P1 — main.py 라우터 분리 (8 커밋)
- pilot: `routes/admin.py` — server/restart, teamlead/review, improvement 5개.
- `routes/team.py` — agents/quotes/team/team-memory/reactions 5개.
- `routes/search.py` — search + suggestions(list) 2개.
- `routes/artifacts.py` — artifacts/uploads/files/exports/project/active 8개.
- `routes/logs.py` — logs CRUD + /ws/logs + 리액션 학습 6개. WS_AUTH_TOKEN은
  `app.state.ws_token`으로 공유하여 순환 임포트 회피.
- `routes/tasks.py` — chat/tasks/dag 6개. `_build_prev_context` 데드 콜 정리.
- `routes/suggestion_branch.py` — branch/explain/merge/rollback/supplement/
  discard 6개 + `_BRANCH_EXPLAIN_CACHE` + `_run_git` + `_run_one_supplement_iter`.
- `routes/suggestions.py` — CRUD/events + auto_triage + _auto_merge_pipeline +
  _apply_suggestion_to_prompts + _extract_rule_body.

### P2 — 테스트 격리 안전망 (4 커밋)
- `core/paths.py` 중앙화: `WORKSPACE_ROOT`, `MEMORY_ROOT` + env 주입
  (`AI_OFFICE_WORKSPACE`, `AI_OFFICE_MEMORY`). office.py 6곳 + main/routes
  하드코딩 제거. TeamMemory/AgentMemory/Office의 `'data/memory'` cwd 의존
  기본값 제거.
- conftest autouse fixture에 `paths.WORKSPACE_ROOT` / `paths.MEMORY_ROOT`
  monkeypatch 추가. 과거 사고(prod chat_logs 227건 오염) 재발 방지.
- env 의존 테스트 실패군 정리 — 126 pass/8 fail/5 err → **169 pass/0 fail/5 skip**.
  - test_message_bus: 'claude' → 'orchestrator' (스키마 role 갱신).
  - test_claude_runner: --bare/cwd 기대 현재 CLI에 맞게 수정.
  - test_agents: '역할 정의' → '## 역할' (페르소나 섹션 반영).
  - test_qa_gate / test_revision_loop: gemma_runner/Office 시그니처 deep stale → skip.
- `.github/workflows/server-tests.yml` — pytest + git status --porcelain data/
  변경 감지 가드.

### P3 — autonomous_loop 분해 (1 커밋)
- `run_loop` 350 LOC → 8개 헬퍼 추출: `_gather_conversation_context`,
  `_detect_topic_stuck`, `_gather_real_seeds`, `_choose_topic`, `_pick_speakers`,
  `_load_code_context`, `_run_speaker_chain`, `_maybe_teamlead_closing`.
- 결정 트리 + 재시도 정책 모듈 상단 주석 명문화.

### P4 — 관측성 3종 (1 커밋)
- `GET /api/project/status` — state/project/active_agent/phase/elapsed_sec/
  revision_count/nodes{total,completed,in_progress}.
- `/api/search?preset=errors` — event_type IN (error, system_notice) 필터.
  `search_logs`에 `event_types` 파라미터 추가.
- `log_store.save_log`에 placeholder 오염 감지 — "초안 내용입니다" 등 테스트
  mock 문자열이 프로덕션 로그에 유입되면 warning.

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
- QA 피드백 루프 (_qa_pushback_round, _file_qa_rule_suggestion).
- Dynamics 기반 peer reviewer 자동 선정.
- 회고 유기화 (metrics + teamlead synthesis).
- 통합 검색 (`/api/search`) + SearchPanel Portal 모달.
