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
- [x] autonomous 시간대 **사이드 프로젝트** 자율성 — `auto_triage_new_suggestion`이
      자발 건의를 LLM 보수 판정으로 자동 승인하고, prompt/rule은 즉시 auto_apply,
      code는 auto_merge_pipeline으로 패치→테스트→커밋 수행. 24h 롤백 가드 + 15건/24h
      예산 + [다짐]/[능력] 접두 가드로 폭주 방지. (P2.5 완료 시점 재확인: 2026-04-15)
- [x] **dynamics 임계치 선제 중재** — peer_concern 3회 누적 시 팀장이
      채팅에 중재 메시지 즉시 발화 (기존 suggestion 등록 + 발화 추가).
      24h 쿨다운 공유.

### 🔥 P2.5 — 말·행동 일치 시스템 (공허한 외침 제거)

> 배경 (2026-04-15 대화): 아이브가 "건의게시판에 올리겠습니다"라고 말했지만
> 실제 suggestion 등록은 0건. 팀장 배치 리뷰도 "분석 30건, 건의 0건".
> 채팅 발화가 실행·결정·진행으로 수렴하지 않는 구조 문제.
> 원칙: "말을 하면 토론이 되어야 하고, 질문을 하면 답변이 되어야 하며,
> 결론을 내고, 업무의 진행이 되어야 한다."

- [x] **① 팀장 리뷰 프롬프트 반전** (최대 임팩트) —
      `teamlead_review.py` 프롬프트에서 "선언형 발언은 신뢰하지 마세요"를 제거하고,
      *"선언형 발언은 반드시 `[다짐]` 카테고리로 등록, target=발화자 본인"*으로 반전.
      "도구/템플릿 없음" 발화도 `도구 부족`/`정보 부족`으로 강제 등록 지시.
      "결론 없이 끝난 주제"는 `프로세스 개선`으로 올리도록 명시.
      최대 건수 3→5, 카테고리 `다짐` 추가, 다짐은 auto_safe=false 고정.
- [x] **② commit_markers 확장** —
      `올리겠/등록하겠/건의하겠/제안하겠/요청하겠/보고하겠/공유하겠/알리겠` +
      `올릴게/등록할게/건의할게/제안할게` 추가 (suggestion_filer.py).
- [x] **③ 다짐 follow-up 워커** —
      `teamlead_review.run_commitment_followup` 신설. 30분 경과 다짐에
      실행 흔적(커밋/PR/반영/완료 키워드) 없으면 팀장이 채팅에서 재촉 발화,
      `followup_nudged` 이벤트 기록. 24h 쿨다운. 팀장 리뷰 루프 말미에서 호출.
      LLM 호출 없는 저비용 DB 조회.
- [x] **④ "능력 부족" 마커 신설** —
      `suggestion_filer._file_capability_gap_suggestion` 추가.
      도구 부족 마커(도구/스크립트/자동화/권한/API/기능/인프라/환경/템플릿 없) vs
      정보 부족 마커(가이드/기준/문서/레퍼런스/데이터/정보 없, 모르겠 등) 분기.
      autonomous 자발/리액션/클로징/멘션 응답 4개 호출 지점 연결.
      pending으로 즉시 등록, auto_triage 경유.
- [x] **⑤ 멘션 응답 SLA** —
      `_route_agent_mentions`에서 응답이 비거나 실패 시 팀장이 재촉 발화
      (*"즉답 어려우면 이유 공유하거나 건의게시판 등록"*). 대상 에이전트가
      팀에 없으면 팀장이 즉시 해명.
- [x] **⑥ 다짐 기본 status 상향** —
      `initial_status` draft→pending 변경 (게시판 전면 노출).
      부작용 방지를 위해 `auto_triage_new_suggestion`에 `[다짐]`/`[능력]`
      접두어 가드 추가 — 자동 반영 대상에서는 영구 제외, 실행 추적 전용.
      테스트 `test_commitment_filing.py` 갱신.

### 🔎 P2.5-α — 사용자 개입 경로 점검 (2026-04-15)

> 현재 사용자는 (a) 자율 대화 중, (b) 프로젝트 진행 중, (c) DM 3가지 상황에서
> 언제든 개입 가능. 구조는 갖춰져 있으나 세부 개선 여지.

- [x] **⑦ 중단 키워드 단어 경계 체크** —
      `user_input._is_stop_command` 도입. 부정형 패턴(`중단하지|멈추지|그만하지|
      취소하지|...|아님|don't stop`)을 선제 제외한 뒤 기존 키워드 매칭.
      회귀 테스트 `test_user_input_stop.py` 3종.
- [x] **⑧ `_user_mid_feedback` 추적 검증** —
      실측 결과 미연결 확인. `handle_mid_work_input`의 팀장/에이전트 멘션
      응답 3개 지점 + 기본 ack에 `_record_commitment` 헬퍼 도입으로
      `_file_commitment_suggestion` 호출 연결. 회귀 테스트
      `test_user_input_commitment.py` 3종.
- [x] **⑨ receive()와 handle_mid_work_input 중복 로직 정리** —
      판단: 방어 코드 유지. `receive()`는 `/api/chat`(tasks.py:107, state 선체크) /
      `/api/tasks`(tasks.py:208, 선체크 없음) / `office.py:300` 재실행 / 테스트
      등 다중 엔트리포인트이므로 내부 state 가드는 필수. 호출자 한 곳만 체크한다
      해서 제거하면 다른 경로에서 실시간 동시 실행 가능.

---

## 🧹 P3 — 코드 건강성 남은 것

- [ ] `project_runner.py` 1,711 LOC 재검토 — P1 리팩터 경험으로 더 분해 가능한지
      (과거 판단은 "역효과 지점"이었으나 라우터 분리 선례로 임계치 달라졌을 수 있음).
- [ ] 스킵된 테스트 재작성 — `test_qa_gate`, `test_revision_loop`은
      `runners.gemma_runner` 제거 + Office 시그니처 변경으로 현재 skip.
      신규 흐름(`test_qa_pushback_loop`, `test_retrospective`)으로 커버되지만
      정식 재작성 가치 있음.
- [ ] **frontend 타입 정리** — dashboard 4.3K. 빠진 타입/any 잔존 점검.
- [x] **placeholder 검사 중복 제거** — `log_store._check_placeholder_contamination`
      제거, event_bus `_build_placeholder_notice` 단일 경로로 통합.
      system_notice 이벤트 발행만 유지 (logger.warning 경로 폐기).
- [x] **dashboard/dist git 트래킹 확인** — `.gitignore`에 이미 등록,
      `git ls-files dashboard/dist` 결과 0건. 실제 오염 없음. (재검토 완료)
- [x] **ProjectStatusBar 적응형 폴링** —
      visibilitychange 훅 + refetchInterval 동적 계산. 활성 2초, idle 10초,
      탭 숨김 시 일시정지. `refetchIntervalInBackground=false`로 이중 방어.

---

## 🛡️ P4 — 안전망 강화 (선순위 낮음)

- [x] CI에 `ruff check` 추가 — F(pyflakes) + E7/E9/W605/B006 실 버그 중심 규칙.
      스타일(E501/E701/E702/E741/B008) 제외. 기존 코드에서 발견된 실제 버그 4종 수정:
      `project_runner._total_dur` 정의 누락(회고 duration=0 전달됨),
      `suggestion_filer._extract_keywords` import 누락,
      `teamlead_review.existing_titles` 미정의,
      `agent_interactions._team_chat` 로컬 `import random`이 모듈 상단 import를
      shadowing해 F823 유발. 죽은 변수 6종 정리. ruff 0 violations.
- [ ] CI에 `mypy` 추가 — 점진적 타이핑 도입 전제. 현재 시그니처에 타입 힌트
      부족(특히 orchestration)해서 `--ignore-missing-imports` + 가벼운 설정부터
      시작 필요. ruff 정착 후 별도 작업.
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
