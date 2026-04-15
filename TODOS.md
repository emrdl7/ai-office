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

### P2. 건의 등록 3-gate ✅ (2026-04-16 완료)
건의 등록 전 게이트 3종 구현 완료:
1. **모드 gate** — P1에서 처리됨 (joke/reaction/trend_research skip)
2. **중복 gate** — `is_title_duplicate_48h()` 신설. 최근 48h pending/accepted
   제목 토큰 70%+ 겹치면 skip + `suggestion_deduplicated` 이벤트.
   `_auto_file_suggestion` / `_file_commitment_suggestion` /
   `_file_capability_gap_suggestion` 세 경로 모두 적용.
3. **구체성 gate** — `_has_tech_token()` 신설 (파일명/함수명/커밋해시/에러코드).
   메시지 40자 미만 OR 기술 토큰 0개면 skip.
   `_auto_file_suggestion` / `_file_capability_gap_suggestion` 에 적용
   (다짐 경로는 적용 안 함 — 약속 문장에 파일명 없어도 됨).
- 기존 dedup 이벤트명 `dedup_skipped` → `suggestion_deduplicated` 통일.
- 테스트 7종 신규 추가 (gate2/gate3/tech_token 패턴 검증). 206 pass.

### P3. 반복 경향 관측 ✅ (2026-04-16 완료)
- `/api/autonomous/stats?hours=N` — 발화 수·모드 분포·PASS 드롭율·
  중복 skip·반복 키워드 top5·stuck 빈도 반환.
- `autonomous_loop.py` — PASS 드롭 시 `autonomous_pass` 이벤트,
  stuck 감지 시 `autonomous_stuck` 이벤트 발행.
- `AutonomousStatsPanel.tsx` — 사이드바 "자율 대화 관측" 버튼으로 열리는
  소형 패널 (6/24/48h/7일 선택, 30초 갱신).

### P4. 건의 파이프라인 안전망 보강 ✅ (2026-04-16 완료)
- **triage overshoot**: `_auto_merge_pipeline` finally 블록에서
  `auto_triage_accept`는 있었지만 병합에 실패한 경우 제안자
  `AgentMemory`에 `triage_overshoot` 태그로 기록.
  `auto_triage_new_suggestion`이 프롬프트를 생성할 때 overshoot 이력이
  있으면 hold 편향 경고문을 삽입 → 가중치 하향.
- **rollback 후보 탐지**: `branch_merged` 이벤트 payload에 수정 파일 목록
  포함. 병합 직후 24h 내 다른 병합에서 동일 파일 경로가 있으면
  `rollback_candidate` 이벤트 + `system_notice` 발행.

### P5. 구성원 성격/능력 프롬프트 검증 체계 ✅

> **맥락**: 시스템 프롬프트는 6계층이 동적 누적됨 — `agents/*.md`(기본
> persona) + `expertise.py`(task 전문지식) + `rejection_analyzer`(과거
> 불합격) + `AgentMemory`(개인 경험) + `PromptEvolver`(학습 규칙 —
> trend_research + 건의 수용으로 매일 누적) + `TeamMemory`(팀 공유).
> 현재 이들 상호 정합성 검증 수단이 전혀 없음. 누적 규칙이 persona와
> 모순되거나, 선언된 능력을 실제로 쓰지 않거나, 실제 하는 일이 선언에
> 없을 수 있음.

#### 5-1. 정적 스키마 린트 (즉시 가능, CI 부담 無) ✅
- `scripts/lint_persona.py` — `agents/*.md` 섹션 표준 강제:
  `# {이름} ({역할})` → `## 성격` → `## 판단력` → `## 대화 스타일` →
  `## 역할` → `## 품질 기준` 순서와 존재 검증.
- 각 섹션 최소 bullet 수·최대 길이·빈 섹션 금지.
- `ruff` 전후 CI에 추가.

#### 5-2. 누적 규칙 ↔ persona 충돌 감사 (주간 배치) ✅
- `improvement/persona_guard.py` 신설. 각 agent별로:
  1. `PromptEvolver.load_rules` 활성 규칙 + persona 섹션 로드
  2. Claude Haiku 1회 호출 — "아래 규칙 N개가 이 페르소나와 모순되는
     쌍을 JSON으로 출력":
     `{conflicts:[{rule_id, persona_clause, reason}]}`
  3. 충돌 규칙은 `active=False`로 자동 비활성화 + `PromptRule.evidence`에
     "persona_guard deactivated: ..." 기록
  4. teamlead에게 `system_notice` — "아이브 규칙 3건이 '겸손' 페르소나와
     충돌로 비활성화" 같은 감사 로그 공개
- 실행 주기: teamlead batch review 끝에 1회 (주 1회 수준). LLM 비용 예측
  가능.

#### 5-3. 페르소나 드리프트 상시 감사 (샘플링) ✅
- `/api/team/persona-drift` 엔드포인트 — 최근 48h `autonomous`+`response`
  로그에서 agent별 무작위 10건 추출 → LLM-as-judge 호출 (Haiku):
  "이 발화가 `agents/{name}.md`의 성격·대화스타일과 일치하는가?" 0~10점
  + 이탈 근거 1문장.
- 6점 미만이 10건 중 3회 이상이면 `drift_detected` 이벤트 발행.
- 대시보드에 agent별 평균 점수 + 최근 이탈 사례 3건 표시.
- trigger: 팀장 batch review 주기와 동일.

#### 5-4. 능력 선언 ↔ 실제 사용 교차 검증 (월간) ✅
- `scripts/capability_audit.py`:
  1. `agents/*.md`의 `## 역할` bullet에서 능력 키워드 추출 (예:
     아이브 → "와이어프레임", "디자인 시스템", "WCAG 2.1 AA", "접근성")
  2. 최근 30일 `chat_logs` + `workspace/*/*` artifacts에서 각 키워드 등장
     빈도 집계.
  3. 분류:
     - **dead capability** (30일 0회) → 선언 제거 후보
     - **implicit creep** (빈도 상위인데 md에 없음) → 선언 추가 후보
  4. 결과 보고서를 teamlead에게 제안으로 (`suggestion_type='prompt'`).
- 자동 merge 아님 — 사람 결정.

#### 5-5. 프롬프트 골든셋 회귀 테스트 (선택적)
- `tests/golden/persona/{agent}/scenario_{n}.json` — agent별 5~10개 대표
  입력 + 평가 rubric:
  ```json
  {"input":"...","must_contain":["hex","px"],"must_avoid":["대강","아마"],
   "persona_match_expected":true}
  ```
- `pytest -m golden_persona` — LLM 호출 후 rubric 통과율 평가.
- nightly CI 또는 `make check-persona` 수동 실행. PR gate 아님 (비용 때문).
- 통과율 시계열 트래킹 → 학습 규칙 누적으로 persona 일관성 떨어지는
  추세 조기 감지.

**우선순위 제안**: 5-1(CI) → 5-2(주간 배치) → 5-3(샘플링) → 5-4(월간)
→ 5-5(선택적). 5-1·5-2가 가장 비용 대비 가치 큼.

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
