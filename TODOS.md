# TODOS

> **현재 상태 (2026-04-15, 366 commits)**
> - 앱 LOC: server 14.3K / routes 2.5K / tests ~3.7K / frontend 4.3K ≈ **25K total**.
> - `main.py` 328 LOC (시작 4,144 → −92%) · 8개 라우터 분리 완료.
> - `project_runner._execute_project` 411 → 283 LOC. `_emit_final_report` /
>   `_finalize_project` 추출. phase 루프 본체는 중간 return 다발로 유지.
> - 학습 루프 3종 + 말·행동 일치(P2.5 6종) + 사용자 개입 점검(P2.5-α 3종) 가동.
> - 관측: `/api/project/status` · 통합 검색 + errors preset · placeholder 오염 감지.
> - 테스트: **170 pass / 0 fail / 0 skip**. CI = pytest + ruff + `data/` 오염 가드.
> - 경로: `core/paths.py` 단일 출처(WORKSPACE_ROOT/MEMORY_ROOT, env 주입).

---

## 🚧 남은 작업 (2건, 모두 인프라성)

### mypy 점진 도입
- 배경: ruff 정착 완료. 다음 단계는 타입 체커.
- 장벽: `orchestration/` 계열 시그니처에 타입 힌트 부족. 한꺼번에 `strict`는
  비현실적.
- 다음 세션 시작점:
  1. `mypy.ini` 생성 — `ignore_missing_imports=true`, `check_untyped_defs=false`,
     `warn_unused_ignores=true`, `warn_redundant_casts=true` 정도로 시작.
  2. 파일별 per-module section으로 `core/paths.py`, `db/*`, `log_bus/*`만
     strict 적용 (이미 힌트 잘 된 모듈).
  3. `.github/workflows/server-tests.yml`에 `mypy server/` 스텝 추가.
  4. 이후 orchestration 모듈을 하나씩 strict로 승격.

### React 컴포넌트 테스트 인프라
- 배경: 현재 서버 쪽만 테스트 (170 pass). dashboard 4.3K는 `tsc --noEmit`만
  통과하고 런타임 회귀 안전망 없음.
- 다음 세션 시작점:
  1. `vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom`
     devDependency 추가.
  2. `vite.config.ts`에 `test: { environment: 'jsdom', setupFiles: [...] }`.
  3. 첫 테스트 대상 후보 — `ProjectStatusBar`(폴링 주기 전환) /
     `SearchPanel`(errors preset 토글) / `MetricsPanel`(빈 상태 렌더).
  4. `.github/workflows/server-tests.yml` 또는 별도 워크플로우에
     `npm --prefix dashboard test` 스텝.

---

## 📦 완료 누적 (요약)

### 이번 사이클 하이라이트
- **라우터 분리** 8종: admin/team/search/artifacts/logs/tasks/suggestion_branch/
  suggestions. `main.py` 4,144 → 328 LOC.
- **도메인 6분할**: teamlead_review / autonomous_loop / agent_interactions /
  project_runner / suggestion_filer / user_input.
- **P2.5 말·행동 일치 6종**: 팀장 리뷰 프롬프트 반전, commit_markers 확장,
  다짐 follow-up 워커, 능력 부족 마커, 멘션 응답 SLA, 다짐 status 상향.
- **P2.5-α 사용자 개입 3종**: 중단 키워드 단어 경계(`_is_stop_command`),
  사용자 개입 응답의 다짐 연결(`_record_commitment`), `receive()` 방어 코드
  유지 판단.
- **학습 루프 3종**: QA pushback→중재→rule draft / dynamics 기반 peer reviewer /
  회고 유기화(metrics + teamlead synthesis).
- **관측 3종**: `/api/project/status` / 통합 검색 + errors preset /
  placeholder 오염 `system_notice` 2차 이벤트.
- **UI 관측**: ProjectStatusBar(적응형 폴링) / MetricsPanel / SearchPanel.
- **테스트 격리**: `core/paths.py` + conftest autouse(WORKSPACE_ROOT/MEMORY_ROOT
  + event_bus subscribers). prod 오염 사고 재발 방지.
- **코드 건강성**: autonomous_loop `run_loop` 350 LOC → 8 헬퍼 /
  `_execute_project` 411 → 283 LOC / 스킵 테스트 정리 /
  placeholder 검사 중복 제거 / frontend strict 확인.
- **안전망**: CI ruff 도입 + 실 버그 4종 수정. REST 인증 미들웨어,
  patch_lock 브로드캐스트, 메시지 버스 30일 아카이브, draft 건의 + 1h 자동 승격.

### 이전 로드맵 (더 먼저 완료)
- 약한 엣지 3종 (_phase_intro / _task_acknowledgment / _work_commentary ↔
  _route_agent_mentions).
- 메타 학습 3종 (`_summarize_team_dynamics` 팀장 리뷰 주입 /
  `_peer_review` peer_concern 임계치 자동 건의 / `DYNAMIC_TYPES` 표준 어휘).
- QA 피드백 루프 (`_qa_pushback_round`, `_file_qa_rule_suggestion`).
- 대시보드 📝 초안 탭 + 승격/철회.
