# TODOS

> **현재 상태 (2026-04-15)**: office.py **669 LOC** (시작 4,144 대비 −84%).
> 도메인별 분할 완료 — teamlead_review / autonomous_loop / agent_interactions /
> project_runner / suggestion_filer. 상호작용·학습·관찰 루프 3종 가동 중.
> P2 완료 (약한 엣지 3종, 메타 학습 3종, Draft 건의 백엔드+UI+엔드포인트,
> source_log_id 스키마+배선). P3 단위 테스트 4종 14케이스 추가. 남은 큰 항목:
> P3 E2E, P4 _execute_project 분할/로그 아카이빙.

---

## P1 — office.py 본체 최종 정리 (목표 ≤500 LOC)

현재 669 LOC. 잔존 ~170 LOC가 목표 초과. 대부분 forwarder 35개와 핵심 로직
(`__init__`, `receive()` 디스패치, `_emit`, `handle_mid_work_input` 등).

### 잔존 대표 메서드
- [x] `_route_agent_mentions` → `agent_interactions` (2026-04-15).
- [x] `_create_handoff_guide` + `_generate_stitch_mockup` → `project_runner` (2026-04-15).
- [x] `_extract_user_questions` + `_check_user_directive` → `project_runner` (2026-04-15).
- [x] forwarder `from orchestration import X` → 모듈 상수로 캐싱 (2026-04-15).
- [x] 35개 forwarder를 1라인으로 압축 (2026-04-15).
- [x] `OfficeState`를 `orchestration/state.py`로 추출 (NameError 16곳 해결).
- [ ] forwarder를 `__getattr__` 기반 동적 위임으로 추가 압축 → ~50 LOC 절감
      가능하나 타입 힌트/IDE 자동완성 손해. 트레이드오프 보류.
- [ ] `handle_mid_work_input` (~80 LOC) 도메인 검토 — agent_interactions 또는
      신규 `user_input.py`로 이관 검토.

### 유지 (Office 본체 핵심)
- `__init__`, `receive()` 디스패치, `_emit`, `_compress_history`,
  `_update_context`, `restore_pending_tasks`, `_record_dynamic`, `OfficeState`,
  `_DIGEST_PATH`, `_PEER_REVIEWERS`.

### 원칙 (유지)
- 이동 커밋은 행동 변경 금지, `self.*` → `office.*` 기계적 치환.
- 각 분할 커밋 완료 시 `wc -l` 기록.

---

## P2 — 상호작용·학습 루프 강화

멀티 에이전트 진단 (2026-04-15) 기준 약한 영역. 구조는 섰지만 **관찰 → 적응**
고리가 미약.

### 약한 엣지 보강
- [x] `_phase_intro`에 과거 교훈 + 직전 동료 의견 주입 (2026-04-15).
- [x] `_task_acknowledgment`에 직전 피어 우려 재고지 (2026-04-15).
- [x] `_work_commentary`가 @멘션 포함 시 `_route_agent_mentions` 즉시 연동 (2026-04-15).

### 관찰·메타 학습
- [x] 팀장 배치 리뷰에 TeamDynamic 집계 주입 (`_summarize_team_dynamics`,
      2026-04-15). 상위 8쌍 + peer_concern 2회+ 경고 쌍.
- [x] `_peer_review` peer_concern 임계치 → 자동 건의 (2026-04-15).
- [x] `TeamDynamic.dynamic_type` 어휘 표준화 (`DYNAMIC_TYPES`, 2026-04-15).

### Draft 건의 상태 (자기 다짐 과잉 등록 완충)
- [x] `suggestion_store.create_suggestion(status='draft')` + `promote_draft`/
      `auto_promote_drafts` (2026-04-15).
- [x] `_file_commitment_suggestion` 기본 draft, 동일 주제 반복 시 **기존 draft를
      pending 승격** (중복 등록 아님, 2026-04-15).
- [x] `main._draft_promotion_loop` — 1시간 주기로 24h 경과 draft 자동 승격.
- [x] UI: 대시보드 '📝 초안' 탭 + 승격/철회 버튼 (2026-04-15).
- [x] `POST /api/suggestions/{id}/promote` 관리자 엔드포인트 (2026-04-15).

### 출처 추적
- [x] `suggestions.source_log_id` 컬럼 + `create_suggestion` 매개변수 (2026-04-15).
- [x] autonomous_loop의 speaker/reactor/closing 3개 경로에서 LogEvent.id를
      캡처해 `_file_commitment_suggestion` / `_auto_file_suggestion`에 전파.
- [x] `_file_reaction_suggestion` source_log_id 매개변수 + create_suggestion
      전파 (2026-04-15). 호출부 배선은 해당 위치에서 log id가 가용해질 때 추가.
- [x] 대시보드 SuggestionModal에 '📍 원본' 링크 + ChatRoom 메시지 컨테이너에
      `id='log-{id}'` 부여 — 클릭 시 스크롤 + 2초 ring 강조 (2026-04-15).

---

## P3 — 테스트 커버리지

26개 테스트 파일 (P2 신규 4종 추가). 분할된 도메인 모듈의
행동 고착화가 급선무.

- [x] `test_commitment_filing.py` — draft 생성, 재다짐 승격, promote_draft,
      auto_promote_drafts stale 분리 (2026-04-15, 4 케이스).
- [x] `test_team_dynamic_recording.py` — peer_review / commitment 2종 훅이
      TeamDynamic에 기록 (2026-04-15, 2 케이스).
- [x] `test_teamlead_review_integration.py` — `_summarize_team_dynamics`
      상위 쌍 / peer_concern 경고 / 빈 집계 / 임계 미달 run_single
      (2026-04-15, 4 케이스).
- [x] `test_autonomous_loop_state.py` — digest state 라운드트립 / 기본값 /
      손상 JSON 복구 / 키워드 추출 (2026-04-15, 4 케이스).
- [ ] `test_project_runner_e2e.py` — 프로젝트 입력 → 회의 → phase 실행 →
      peer_review(CONCERN) → 보완 → 최종 리뷰 전 구간 1개 시나리오. 대량
      mock 필요 — 우선순위 보류.
- [ ] PromptEvolver 규칙 주입 검증 (commitment auto_apply 후 규칙 파일 변화)
      — auto_triage_new_suggestion이 main.py에 있어 교차 mock 필요.

---

## P4 — 보조 개선 (우선순위 낮음)

- [ ] `_execute_project` (659 LOC) 자체 분할 — 프로젝트 실행 로직의 단계별
      sub-helper(`_run_phase_group`, `_persist_phase_output` 등)로 쪼갬.
      project_runner.py 내부 리팩터. **위험도 높음** — 행동 변경 없는 분할이
      어려워 충분한 E2E 테스트 선행 필요.
- [ ] `agent_interactions._team_chat` (~220 LOC)의 `_single_agent_chat` 내부
      함수 외부화 — 테스트 가능하게. office/user_input/mentioned_ids를 인자로 승격.
- [ ] MCP 재연결 시 plugin:telegram 토큰/정책 재점검 (세션 간 연결 실패 관찰됨).
- [x] 로그 DB 아카이빙 (2026-04-15) — `chat_logs_archive` + `archive_old_logs`
      / `maybe_archive_logs` (1만건 또는 50MB 임계). main.archive_loop에 통합.

---

## ✅ 완료 (이전 로드맵 기록용)

### P1 분할 (5단계)
- [x] 1. `teamlead_review.py` (395 LOC) — 팀장 배치 리뷰·회고.
- [x] 2. `autonomous_loop.py` (634 LOC) — 자율 활동·리액션 체인.
- [x] 3. `agent_interactions.py` (726 LOC) — 팀원 간 협의·잡답·리뷰.
- [x] 4. `project_runner.py` (1,452 LOC) — 프로젝트 실행 파이프라인 12종.
- [x] 5. `suggestion_filer.py` (312 LOC) — 건의 자동 등록 감지 3종.

### P2 메시지 버스 아카이브 (완료)
- [x] `archived_at` 컬럼 + 마이그레이션.
- [x] 30일 경과 done 메시지 이관.
- [x] 서버 시작 시 1회 + 24h 주기 `_archive_loop` (`main.py`).
- [x] `(to, status, created_at)` 복합 인덱스.

### P3 REST 인증 (완료)
- [x] 배포 모드별 인증 정책 문서 (`server/README.md`).
- [x] `REST_AUTH_TOKEN` 미들웨어 (Bearer / ?token=).
- [x] CORS — localhost:3100/127.0.0.1:3100만 허용.

### P4 patch_lock/자가개선 (완료)
- [x] `_patch_lock` 점유 중 브로드캐스트.
- [x] `_RETRY_MAX` 3→2 축소.
- [x] `_build_patch_prompt`에 FORBIDDEN 안내.

### 상호작용·학습 루프 (완료)
- [x] 멀티 에이전트 진단 (2026-04-15).
- [x] 자기 다짐 감지 훅 (`_file_commitment_suggestion` + 3개 훅 지점).
- [x] 협업 관찰 루프 (`_record_dynamic` + `_peer_review`/`_consult_peers`/
      commitment 3개 훅 지점). TeamDynamic이 에이전트 프롬프트에 자동 주입.
