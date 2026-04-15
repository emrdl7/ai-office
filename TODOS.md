# TODOS

> **현재 상태 (2026-04-15)**: office.py **706 LOC** (시작 4,144 대비 −83%).
> 도메인별 분할 완료 — teamlead_review / autonomous_loop / agent_interactions /
> project_runner / suggestion_filer. 상호작용·학습·관찰 루프 3종 가동 중.

---

## P1 — office.py 본체 최종 정리 (목표 ≤500 LOC)

현재 706 LOC. 잔존 약 200 LOC가 목표 초과분. 대부분 forwarder 37개 (~110 LOC)와
핵심 로직(`__init__`, `receive()` 디스패치, `_emit` 등)이다.

### 잔존 대표 메서드
- [x] `_route_agent_mentions` → `agent_interactions`로 이동 (2026-04-15).
- [x] `_create_handoff_guide` + `_generate_stitch_mockup` → `project_runner`로 이동 (2026-04-15).
- [x] `_extract_user_questions` + `_check_user_directive` → `project_runner`로 이동 (2026-04-15).
- [x] forwarder `from orchestration import X` → 모듈 상수로 캐싱 (2026-04-15).
- [ ] 37개 forwarder를 `__getattr__` 기반 동적 위임으로 압축 → ~70 LOC 추가 절감
      예상. 단, IDE 자동완성 손해 있음 — 트레이드오프 검토 필요.
- [ ] **선결 버그**: `project_runner.py`가 `OfficeState`를 import 없이 참조
      (16곳). `test_quick_task_routes_to_single_agent` 실패. OfficeState를
      별도 모듈(`orchestration/state.py`)로 추출하면 해결.

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
- [ ] `_phase_intro`에 해당 담당자의 **과거 실패 규칙 상위 1개** + **관련 팀원
      한 줄 조언** 삽입. 현재는 착수 인사만 나감.
- [ ] `_task_acknowledgment`에 **직전 피어 리뷰 피드백 재고지**. 수령 확인이
      컨텍스트와 분리되어 있음.
- [ ] `_work_commentary`가 `_route_agent_mentions` 트리거 경로와 연동되도록
      — 진행 중 코멘트에 `@팀원` 포함되면 즉시 라우팅.

### 관찰·메타 학습
- [ ] 주간 배치 리뷰(`teamlead_review.run_loop`)에서 **TeamDynamic 집계**
      추가 — "누가 누구와 잘 맞는지 / stuck 패턴" 요약을 팀 맥락 텍스트에 주입.
- [ ] `_peer_review`의 `peer_concern` 누적이 임계치(예: 같은 쌍 3회) 넘으면
      **자동 건의 등록** (`관계 개선 필요: X↔Y`).
- [ ] `TeamDynamic.dynamic_type` 어휘 표준화 문서 (team_memory.py) —
      현재 자유 문자열 (peer_concern/peer_approved/consulted/committed_to_request
      등)이 흩어져 있음.

### Draft 건의 상태 (자기 다짐 과잉 등록 완충)
- [ ] `suggestion_store`에 `status='draft'` 추가. 현재 `_file_commitment_suggestion`
      이 바로 pending을 만들어 auto_triage로 돌입 — 말로만 한 다짐도 실행됨.
- [ ] draft → pending 승격 조건: (a) 요청자/팀장이 확정, (b) 24h 경과 후 자동 승격,
      (c) 같은 committer의 같은 주제 반복 시 자동 승격.
- [ ] UI: 대시보드에서 draft 건의 목록 별도 탭.

### 출처 추적
- [ ] 건의에 `source_log_id` 컬럼 추가. `_file_commitment_suggestion`/
      `_auto_file_suggestion`/`_file_reaction_suggestion` 등록 시 원본
      message 로그 ID 저장.
- [ ] 대시보드에서 건의 → 원본 발화로 이동 가능.

---

## P3 — 테스트 커버리지

22개 테스트 파일 존재하나 **E2E/통합 시나리오 부재**. 분할된 도메인 모듈의
행동 고착화가 급선무.

- [ ] `test_teamlead_review_integration.py` — force=True로 `run_single` 호출,
      JSON 파싱 실패 시 fallback, circuit breaker 트리거.
- [ ] `test_autonomous_loop_state.py` — digest state 저장/로드 라운드트립,
      stuck detection 트리거.
- [ ] `test_project_runner_e2e.py` — 프로젝트 입력 → 회의 → phase 실행 →
      peer_review(CONCERN) → 보완 → 최종 리뷰 전 구간 1개 시나리오.
- [ ] `test_commitment_filing.py` — "반영하겠습니다" 발화 → draft 생성 →
      승격 → auto_apply → PromptEvolver 규칙 주입 검증.
- [ ] `test_team_dynamic_recording.py` — peer_review / consult /
      commitment 3종 훅이 모두 TeamDynamic에 기록되는지.

---

## P4 — 보조 개선 (우선순위 낮음)

- [ ] `_execute_project` (659 LOC) 자체 분할 — 프로젝트 실행 로직의 단계별
      sub-helper(`_run_phase_group`, `_persist_phase_output` 등)로 쪼갬.
      project_runner.py 내부 리팩터.
- [ ] `agent_interactions._team_chat` (~220 LOC)의 `_single_agent_chat` 내부
      함수 외부화 — 테스트 가능하게.
- [ ] MCP 재연결 시 plugin:telegram 토큰/정책 재점검 (세션 간 연결 실패 관찰됨).
- [ ] 로그 DB 아카이빙 — `log_storage_stats` 임계치(30일+ 1만건 or 50MB)에
      도달하면 `chat_logs_archive`로 이관 (버스 아카이브와 동일 패턴).

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
