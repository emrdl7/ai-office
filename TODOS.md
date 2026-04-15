# TODOS

> **현재 상태 (2026-04-15)**: office.py **669 LOC** (시작 4,144 대비 −84%).
> 도메인 5분할 / 상호작용·학습 루프 3종 가동. P1 본체 정리·P2 강화·P3 단위
> 테스트 14케이스·P4 로그 아카이빙 완료. 테스트 113 pass / 1 pre-existing fail.
> 남은 큰 덩어리: E2E 테스트와 그를 선결로 하는 `_execute_project` 분할.

---

## P1 — 테스트 인프라 (E2E 선결)

`_execute_project` 분할이 막혀 있는 진짜 이유: 행동 변경 없는 대규모 분할을
검증할 E2E가 없다. 먼저 시나리오 테스트를 깔고 그 뒤에 리팩터.

- [ ] **`test_project_runner_e2e.py`** — 단일 시나리오 1개:
      프로젝트 입력 → 회의 → phase 실행 → peer_review(CONCERN) → 보완 →
      최종 리뷰. mock 전략:
      - `run_claude_isolated` / `run_gemini` → 스크립트화된 응답 시퀀스
      - `Agent.handle` → 각 단계별 미리 정의된 산출물 반환
      - `office.workspace`는 tmp_path
      - LLM 호출 횟수와 호출 순서 검증 (스텝 수, 리뷰 라운드)
- [ ] **PromptEvolver 규칙 주입 검증** — commitment auto_apply 후 규칙 파일
      diff 확인. `auto_triage_new_suggestion`(main.py)을 부분 mock하거나
      별도 모듈로 추출해 직접 호출.
- [ ] **`test_pre_existing_orchestration_failure` 정리** —
      `test_quick_task_routes_to_single_agent`가 revision 루프 변경 후 깨진
      상태로 방치 중. 의도 vs 현행 동작 확정 후 어서션 갱신 또는 코드 수정.

---

## P2 — `_execute_project` 분할 (P1 완료 후 착수)

`project_runner._execute_project`는 660 LOC 단일 함수. E2E가 깔린 뒤 단계별
sub-helper로 쪼갠다. 행동 변경 금지.

- [ ] `_check_existing_phase_output(office, phase, PHASES)` —
      서버 재시작 시 기존 산출물 스킵 로직(~50 LOC).
- [ ] `_build_phase_prompt(office, phase, prev_result, ...)` —
      그룹별 프로젝트 텍스트·인수인계 조립(~40 LOC).
- [ ] `_run_phase_with_qa(office, phase, prompt)` — QA 게이트 + 보완 루프(~80 LOC).
- [ ] `_persist_phase_output(office, phase, content, artifacts)` —
      파일 저장 + artifacts 기록(~30 LOC).
- [ ] `_collect_project_metrics` — PhaseMetrics → ProjectMetrics 마감.

---

## P3 — 테스트 보강 (병행 가능)

- [ ] `_single_agent_chat` 모듈 외부화 + 단위 테스트.
      `_team_chat` 내부 함수를 모듈 함수로 승격 (office, user_input,
      mentioned_ids를 인자로). PASS 판정 / 멘션 필수응답 / Round 2 컨텍스트
      각각 1 케이스.
- [ ] `_route_agent_mentions` 라우팅 케이스 — teamlead 멘션 / 본인 멘션 무시 /
      최대 3개 / `_file_commitment_suggestion` 트리거.
- [ ] `_maybe_file_relationship_suggestion` 임계치/쿨다운 — 3회 미만 등록
      안 됨 / 24h 내 중복 등록 안 됨.
- [ ] `_archive_loop` 실패 시 후속 루프 계속 동작 (cancel 분리).

---

## P4 — 보조 개선 (기회 되면)

- [ ] office.py forwarder를 `__getattr__` 동적 위임으로 추가 압축
      (~50 LOC 절감, IDE 자동완성 손해 트레이드오프).
- [ ] `handle_mid_work_input` (~80 LOC) → `agent_interactions` 또는
      신규 `user_input.py` 이관 검토.
- [ ] MCP 재연결 시 `plugin:telegram` 토큰/정책 재점검 (세션 간 연결 실패
      관찰됨, 환경 점검 위주).
- [ ] `_file_reaction_suggestion` / 멘션 응답 호출부에서 source_log_id 실제
      값 전파 (현재는 매개변수만 받고 호출부는 빈 문자열).

---

## ✅ 완료 (요약)

### 도메인 분할 (P1 1~7단계, 2026-04-15)
- 5개 모듈 분할: teamlead_review / autonomous_loop / agent_interactions /
  project_runner / suggestion_filer.
- forwarder 캐싱·1라인 압축, OfficeState를 `state.py`로 추출.
- 부수 효과: project_runner의 NameError 16곳 + agent_interactions
  AttributeError 2곳 해결.

### 상호작용·학습 루프 (P2, 2026-04-15)
- 약한 엣지 3종: `_phase_intro` 맥락 주입 / `_task_acknowledgment` 우려
  재고지 / `_work_commentary` ↔ `_route_agent_mentions` 연동.
- 메타 학습 3종: `_summarize_team_dynamics` 팀장 리뷰 주입 /
  `_peer_review` peer_concern 임계치 자동 건의 / `DYNAMIC_TYPES` 표준 어휘.
- TeamMemory `add_dynamic` 누적 허용 (덮어쓰기 → append, MAX 200).

### Draft 건의 + 출처 추적 (2026-04-15)
- `status='draft'` + `promote_draft` / `auto_promote_drafts` + 1h 자동 승격 루프.
- 대시보드 '📝 초안' 탭 + 승격/철회 + `POST /api/suggestions/{id}/promote`.
- `source_log_id` 컬럼 + autonomous_loop 3경로 배선 + 대시보드 '📍 원본'
  점프 (`#log-{id}` 스크롤 + ring 강조).

### 인프라 (이전 로드맵)
- 메시지 버스 30일 아카이브 + 24h 주기 루프.
- chat_logs 30일+ 1만건/50MB 임계 아카이브 (2026-04-15).
- REST 인증 미들웨어, patch_lock 브로드캐스트, retry 축소.
- 단위 테스트 14케이스 (commitment / dynamic / teamlead / autonomous /
  chat_logs archive).
