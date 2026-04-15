# TODOS

## P1 — office.py 분할 로드맵

`server/orchestration/office.py`는 현재 **3,962 LOC 단일 파일 / 단일 클래스**에
50개 이상의 메서드를 담고 있다. 팀장 판정, 프로젝트 실행, 팀원 상호작용, 자율
루프, 회고, 건의 파일링이 모두 하나의 `Office` 클래스에 결합돼 있어 단위 테스트는
사실상 불가능하고, 신규 기능 추가 시 관련 없는 로직까지 읽어야 한다.

**원칙**: 한 번에 분할하지 않는다. (1) **동결 규칙**을 먼저 세우고, (2) 새로 추가되는
기능만 새 모듈로 받으며, (3) 기존 메서드는 손댈 일이 생길 때마다 해당 도메인 모듈로
이관한다. 순수 리팩터링 커밋은 지양 (행동 변화 없는 2,000줄 이동은 리뷰 불가능).

### 동결 규칙 (선적용)

- [ ] `office.py`에 새 메서드 추가 금지 — 신규 기능은 무조건 도메인 모듈에.
- [ ] 기존 메서드 수정 시, 50줄 이상 손보게 되면 **먼저** 도메인 모듈로 이동한 뒤
      변경 (2단계 커밋: `refactor: move X from office.py` → `feat: ...`).
- [ ] `Office` 클래스의 public API는 당분간 유지 (main.py가 의존).

### 도메인 분할 목표 (순서 의미 있음)

1. [x] **`teamlead_review.py`** — `start_teamlead_review_loop`, `_run_single_review`,
       `stop_teamlead_review_loop`, `_team_retrospective` 분리 완료.
       office.py 4,144 → 3,772 LOC (−372). teamlead_review.py 395 LOC 신규.
       Office 메서드는 forwarder 4개로 축소 (public API 유지).
2. [x] **`autonomous_loop.py`** — `start_autonomous_loop`, `stop_autonomous_loop`,
       `_load_digest_state`, `_save_digest_state`, `_react_to_received_reactions`,
       `_agents_react_to_peers`, `_autonomous_react`, `_autonomous_closing` 분리 완료.
       office.py 3,772 → 3,205 LOC (−567). autonomous_loop.py 634 LOC 신규.
       Office는 8개 forwarder만 유지.
3. [x] **`agent_interactions.py`** — `_team_reaction`, `_consult_peers`, `_peer_review`,
       `_handoff_comment`, `_task_acknowledgment`, `_phase_intro`, `_work_commentary`,
       `_contextual_reaction`, `_team_chat`, `_resolve_reviewer` 분리 완료.
       office.py 3,205 → 2,564 LOC (−641). agent_interactions.py 726 LOC 신규.
       `_record_dynamic`/`_PEER_REVIEWERS`는 공유 인프라로 Office에 유지.
4. [x] **`project_runner.py`** — `_handle_project`, `_continue_project`,
       `_plan_project_phases`, `_default_phases`, `_execute_project`, `_cross_review`,
       `_auto_export`, `_run_qa_check`, `_teamlead_final_review`,
       `_run_planner_synthesize`, `_quick_task_second_opinion`, `_handle_quick_task`
       분리 완료. office.py 2,564 → 1,228 LOC (−1,336). project_runner.py 1,452 LOC.
5. [ ] **`suggestion_filer.py`** — `_file_reaction_suggestion`, `_auto_file_suggestion`.
6. [ ] **`Office` 본체** = 상태 머신 + `receive()` 디스패치 + `__init__`만 남김.
       목표 ≤ 500 LOC.

### 각 분할 단계 공통 원칙

- 이동하면서 **행동 변경 금지** (테스트 추가/수정 없이 import 경로만 변경).
- 도메인 모듈은 `Office` 인스턴스를 생성자로 받고, 필요한 상태는 property 접근.
- 각 분할 커밋은 `git diff --stat`으로 **추가·삭제 줄 수가 거의 대칭**이어야 함
  (로직 이동만, 생성 아님).
- 이동 후 해당 도메인에 **처음 신규 테스트 파일 추가** — 분할의 가치를 테스트로 잠금.

### 측정

- 분할 전 기준: `office.py` 3,962 LOC, `Office` 클래스 메서드 50+.
- 각 단계 완료 시 `wc -l server/orchestration/*.py` 기록.
- 최종 목표: `office.py` ≤ 500 LOC, 도메인 모듈 각 ≤ 800 LOC.

---

## P2 — 메시지 버스 아카이브 잡

`data/bus.db`의 messages 테이블이 영구 누적되어 장기 운영 시 쿼리·디스크 선형 증가.

- [x] 메시지 스키마에 `archived_at` 컬럼 추가 마이그레이션.
- [x] 완료된 프로젝트 메시지는 N일(예: 30) 후 아카이브 테이블로 이동.
- [x] 월간 정리 잡 (서버 시작 시 1회 + 24h 주기, `main._archive_loop`).
- [x] 기존 인덱스 외에 `(to, status, created_at)` 복합 인덱스 검토.

---

## P3 — REST 엔드포인트 인증 일관성

`WS_AUTH_TOKEN`은 WebSocket만 보호. REST (`/api/chat`, `/api/suggestions/*`,
`/api/workspace/*`)는 현재 로컬호스트 전제로 공개.

- [x] 배포 모드별 인증 정책 문서화 (README, d388d1c).
- [x] 외부 노출 시 동일 토큰 또는 세션 기반 보호 미들웨어 추가 (REST_AUTH_TOKEN).
- [x] CORS 설정 재점검 — localhost:3100/127.0.0.1:3100만 허용 (main.py:139).

---

## P4 — 기타

- [x] `_patch_lock` 점유 중 다른 suggestion apply 시 현황 브로드캐스트 (8535015).
- [x] `_RETRY_MAX=2`로 낮춰 최악 락 점유 축소 (8535015, code_patcher.py:16).
- [x] `code_patcher._build_patch_prompt`에 "FORBIDDEN 경로 수정 시 FILES 블록 필수" 안내 (8535015).
