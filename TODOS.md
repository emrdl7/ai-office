# TODOS

> **현재 상태 (2026-04-15)**: office.py **598 LOC** (시작 4,144 대비 −86%).
> 도메인 6분할 (teamlead_review / autonomous_loop / agent_interactions /
> project_runner / suggestion_filer / user_input). `_execute_project`
> 4 helper 추출 (check_existing / build_prompt / run_with_qa /
> persist_output / collect_metrics). P1·P2 완료, P3 4/4, P4 3/4 완료
> (남은 1건은 forwarder `__getattr__` 트레이드오프 항목).
> 테스트 139 pass + 신규 17 cases (pre-existing fail군 제외).

---

## P1 — 테스트 인프라 (E2E 선결)

`_execute_project` 분할이 막혀 있는 진짜 이유: 행동 변경 없는 대규모 분할을
검증할 E2E가 없다. 먼저 시나리오 테스트를 깔고 그 뒤에 리팩터.

- [x] **`test_project_runner_e2e.py`** — 최소 시나리오 1개 확보
      (2026-04-15). 2-phase 단일 그룹, 그룹 마지막 peer_review(CONCERN) →
      revised content 반영 검증. `Office` 보조 메서드를 `ExitStack`으로
      일괄 no-op 처리, `agent.handle`은 scripted side_effect.
      P2 분할 리팩터 때 이 테스트가 행동 회귀 가드 역할.
      부수 관찰: `_cross_review`가 모듈 상수(`_CROSS_REVIEW_MAP`)를
      `office.` 속성으로 접근하는 pre-existing 버그 — 현재는 stub으로
      우회, P2 후속 정리 대상.
- [x] **PromptEvolver 규칙 주입 검증** — `improvement.auto_apply.apply_prompt_or_rule`
      직접 호출로 patch json 생성·누적·target_agent 폴백·user_comment source
      전환 검증 (`tests/test_auto_apply_prompt_rule.py`, 2026-04-15).
- [x] **`test_pre_existing_orchestration_failure` 정리** —
      `test_quick_task_routes_to_single_agent` 복구 (2026-04-15).
      `project_runner.run_claude_isolated` 패치로 peer 기여 "없음"·팀장
      [PASS] 고정, 어서션을 "담당 에이전트만 라우팅" 의도로 갱신.
      부수: `agent_interactions.py`에 누락된 `classify_intent` import 추가
      (런타임 `NameError` 해결).

---

## P2 — `_execute_project` 분할 (P1 완료 후 착수)

`project_runner._execute_project`는 660 LOC 단일 함수. E2E가 깔린 뒤 단계별
sub-helper로 쪼갠다. 행동 변경 금지.

- [x] `_check_existing_phase_output(office, phase, PHASES, all_results,
      phase_artifacts, user_input)` — 서버 재시작 시 기존 산출물 스킵 로직
      추출 (2026-04-15). 스킵되면 content 반환, 아니면 None.
      E2E + 단위 테스트 6케이스 회귀 없음.
- [x] `_build_phase_prompt(office, phase, all_results, user_input,
      reference_context)` — 프로젝트/단계/동일그룹 전문/타그룹 가이드/포맷
      지침 조립 (2026-04-15). 단위 테스트 5케이스
      (`tests/test_phase_prompt_builder.py`).
- [x] `_run_phase_with_qa(office, agent, phase, filename, all_results,
      user_input)` — QA 게이트 + 1회 보완 루프, `(qa_passed, rev_delta)`
      반환 (2026-04-15).
- [x] `_persist_phase_output(office, phase, content, phase_artifacts,
      all_results, user_input)` — MD 저장 + HTML/PDF/code 추출 + 멀티페이지
      사이트 빌더 (2026-04-15).
- [x] `_collect_project_metrics(office, task_id, project_type, user_input,
      started_at, phase_metrics)` — finished_at·duration 계산 +
      improvement_engine 전달 (2026-04-15).

---

## P3 — 테스트 보강 (병행 가능)

- [x] `_single_agent_chat` 모듈 외부화 + 단위 테스트 (2026-04-15).
      `_team_chat` 내부 중첩함수를 `agent_interactions` 모듈 함수로 승격
      (office, user_input, mentioned_ids 인자화). PASS 판정 / 멘션 강제응답 /
      Round 2 컨텍스트 3케이스 (`tests/test_single_agent_chat.py`).
- [x] `_route_agent_mentions` 라우팅 케이스 — teamlead / 자가멘션 / 최대 3명 /
      commitment 트리거 (`tests/test_mention_routing.py`, 2026-04-15).
- [x] `_maybe_file_relationship_suggestion` 임계치/쿨다운 — 3회 미만 skip /
      3회 도달 등록 / 24h 중복 차단 (`tests/test_team_dynamic_recording.py`,
      2026-04-15).
- [x] `_archive_loop` 복원성 — bus 실패 시 chat_logs 실행 / chat_logs 실패해도
      다음 iteration 지속 (`tests/test_archive_loop_resilience.py`,
      2026-04-15).

---

## P4 — 보조 개선 (기회 되면)

- [ ] office.py forwarder를 `__getattr__` 동적 위임으로 추가 압축
      (~50 LOC 절감, IDE 자동완성 손해 트레이드오프).
- [x] `handle_mid_work_input` → 신규 `orchestration/user_input.py` 이관
      (2026-04-15). office.py forwarder 2라인으로 축소, 총 669 → 598 LOC.
- [ ] MCP 재연결 시 `plugin:telegram` 토큰/정책 재점검 (세션 간 연결 실패
      관찰됨, 환경 점검 위주).
- [x] `_file_reaction_suggestion` / 멘션 응답 호출부에서 source_log_id 실제
      값 전파 (2026-04-15). `Office._emit`가 `LogEvent`를 반환하도록 변경하고
      `_team_reaction`(리액션 건의) / `_route_agent_mentions`(멘션 commitment)
      두 호출부에서 emit event.id를 source_log_id로 주입.
      `tests/test_mention_routing.py`에 전파 어서션 추가.

---

## 🆕 통합 검색 API + 최근 피처 Polish (2026-04-15)

**검색·필터 백엔드 MVP**
- `log_store.search_logs(q, agent_id, include_archive, limit)` —
  chat_logs + archive 통합 검색. message LIKE + agent_id 매치.
- `list_suggestions` 시그니처 확장 — status / category / target_agent /
  q (title+content LIKE) / limit.
- `GET /api/suggestions` — 새 파라미터 노출.
- `GET /api/search?q=&type=logs|suggestions|dynamics|all&agent_id=&...` —
  3 소스 통합 검색 엔드포인트. dynamics는 team_shared.json 필터링.
- 단위 테스트 4 (`tests/test_search.py`): 로그 q/agent_id / suggestion
  카테고리+q / content LIKE.
- `dashboard/src/components/SearchPanel.tsx` — Portal 모달, q 디바운스,
  type 탭(전체/로그/건의/다이내믹), 아카이브 포함 체크박스, 결과별 원본
  점프 (`#log-{id}` 스크롤 + amber ring 강조). Sidebar 하단에 '통합 검색'
  버튼 추가.

**최근 피처 Polish**
- `_auto_export`가 `retrospective.md`도 PDF로 변환 (rglob 패턴 추가).
- 프론트 `CATEGORY_LABEL`에 'QA 규칙', '프로세스 개선', '아이디어',
  'collaboration' 라벨 추가 (`SuggestionModal.tsx`).
- `_peer_review` 진입 시 팀장이 선정된 리뷰어를 공지 emit —
  dynamics 기반 동적 선정이 가시화.

---

## 🆕 프로젝트 회고 유기화 (2026-04-15)

기존 "30자 한 줄" 회고를 실 실행 데이터 기반 구체 회고로 업그레이드 +
팀장 종합 회고록 아티팩트 저장.

- `teamlead_review._build_agent_metrics_context(office, agent)` —
  담당 단계 수 / QA 불합격 / 리비전 / 총 시간 + 최근 받은 피드백
  3건 요약을 생성.
- `run_retrospective`가 각 에이전트 회고 프롬프트에 위 컨텍스트 주입 →
  실제 겪은 일 기반 교훈 유도.
- `_synthesize_and_save_retrospective` — 팀원 회고를 팀장이 종합해
  "핵심 / 관통하는 실마리 / 다음 액션" 3섹션 마크다운 생성 →
  workspace에 `retrospective.md`로 저장. 팀장이 첫 액션을 채팅에도 공유.
- 단위 테스트 3 (`tests/test_retrospective.py`): 메트릭 컨텍스트 QA/리비전 /
  받은 피드백 포함 / artifact+lesson 저장.

---

## 🆕 Dynamics 기반 peer reviewer 자동 선정 (2026-04-15)

하드코딩 `_PEER_REVIEWERS` 대신 팀 다이내믹 점수로 리뷰어 선정 —
과거 peer_approved / committed_to_request가 많은 쌍이 이어지고,
peer_concern 누적 쌍은 배제. 유기적 팀 자기조직화.

- `agent_interactions._select_peer_reviewers(office, worker_id, limit=2)` —
  점수: `peer_approved +1, committed_to_request +0.3, peer_concern -0.5`.
  신호 합계 < 3 이면 기존 매핑 폴백.
- `_peer_review` 가 helper 호출로 대체.
- 단위 테스트 3 (`tests/test_peer_reviewer_selection.py`):
  폴백 / 점수 상위 선정 / concern 많은 쌍 배제.

---

## 🆕 QA 피드백 루프 (2026-04-15)

QA 불합격을 1회성 revision으로 끝내지 않고, 팀원 의견 → 팀장 중재 → 합의된
규칙을 draft 건의로 자동 등록해 PromptEvolver로 승격.

- `agent_interactions._qa_pushback_round` — peer 2명 [지지/반박/보강] 의견
  수집 → 팀장 JSON 중재 (ADOPT/MODIFY/REJECT).
- `suggestion_filer._file_qa_rule_suggestion` — ADOPT/MODIFY 합의 규칙을
  category='QA 규칙', target=offending_agent, status='draft'로 등록.
  source_log_id는 QA 불합격 emit event.id.
- `_run_phase_with_qa` 훅 — QA fail emit → pushback round → draft 등록 →
  기존 revision 루프 유지 (1회). 예외는 삼켜 revision 계속.
- 단위 테스트 3 (`tests/test_qa_pushback_loop.py`): ADOPT / REJECT / MODIFY.

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
