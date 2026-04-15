# TODOS

> **현재 상태 (2026-04-15, 367 commits)**
> - 앱 LOC: server 14.3K / routes 2.5K / tests ~3.7K / frontend 4.3K ≈ **25K total**.
> - `main.py` 328 LOC (시작 4,144 → −92%) · 8개 라우터 분리 완료.
> - `project_runner._execute_project` 411 → 283 LOC. `_emit_final_report` /
>   `_finalize_project` 추출. phase 루프 본체는 중간 return 다발로 유지.
> - 학습 루프 3종 + 말·행동 일치(P2.5 6종) + 사용자 개입 점검(P2.5-α 3종) 가동.
> - 관측: `/api/project/status` · 통합 검색 + errors preset · placeholder 오염 감지.
> - 테스트: **179 pass(서버) + 19 pass(dashboard)**. CI = pytest + ruff + **mypy(strict 48모듈 — 앱 코드 전수)** + vitest(MetricsPanel/ProjectStatusBar/SearchPanel/TaskInput) + `data/` 오염 가드.
> - 경로: `core/paths.py` 단일 출처(WORKSPACE_ROOT/MEMORY_ROOT, env 주입).

---

## 🚧 남은 작업 — 채팅/건의 고도화 로드맵

### P1. 모드 메타 표기 + 오탐 차단 (이번 세션 구현)
- `_run_speaker_chain`이 발행하는 `LogEvent.data`에
  `{'autonomous_mode': 'joke'|'improvement'|'reaction'|'closing'|'trend_research'}` 추가.
- `_auto_file_suggestion` / `_file_commitment_suggestion` /
  `_file_capability_gap_suggestion`에 `mode` 파라미터 전달.
  `mode in {'joke','trend_research','reaction'}` 이면 즉시 return.
- **효과**: "kill -9 ㅎㅎ" 같은 농담이 능력부족 건의로 둔갑하는 오탐
  구조적 차단. 리액션성 발화가 다짐으로 오등록되던 사례도 함께 해결.

### P2. 건의 등록 3-gate (차기 세션)
건의 등록 전 게이트 3종을 `_register_suggestion` 파이프라인에 삽입:
1. **모드 gate** — P1에서 처리됨 (joke/reaction/trend_research skip)
2. **중복 gate** — 제목 토큰이 최근 48h pending/accepted 제목과
   70%+ 겹치면 skip + `suggestion_deduplicated` 이벤트 기록. 오늘
   폐기한 #425896e6와 나란히 존재했던 #d563da5c 같은 사고 방지.
3. **구체성 gate** — 메시지 40자 미만 또는 기술 토큰(파일명/함수명/
   커밋해시/에러코드 패턴) 0개면 skip. 추상 관찰을 건의로 올리지 말 것.

### P3. 반복 경향 관측 (차기)
- `/api/autonomous/stats` — 최근 N시간 autonomous 발화 수, 모드별 분포,
  [PASS] 드롭율, 중복 skip 건수, 반복 키워드 top5, stuck 감지 빈도.
- 대시보드에 소형 패널 노출 → 블록리스트 효과 수치로 관측.

### P4. 건의 파이프라인 안전망 보강 (차기)
- `auto_triage_accept`가 나왔지만 AI 리뷰가 `merge_safe`를 받지 못한
  건의는 해당 제안자 `AgentMemory`에 "triage overshoot" 기록 →
  다음 유사 건의의 auto_triage 가중치 하향.
- 같은 파일 경로를 24h 내 2회 수정한 자가개선은 자동 rollback 후보
  리스트에 추가 (파이프라인 폭주 방지).

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
