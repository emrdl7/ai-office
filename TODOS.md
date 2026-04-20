# TODOS

> **현재 상태 (2026-04-20 기준)**
> - UX Studio 피벗 완료 — 자율 대화/teamlead_review/autonomous_loop 삭제, Job 파이프라인 + Playbook 중심.
> - Job Spec 6종: research / design_direction / planning / review / publishing / coding.
> - Playbook 2종: research_to_planning(선형), full_campaign(DAG).
> - `model_router` 5-tier (nano/fast/standard/deep/research). Opus 일일 10회 제한.
> - Haiku 동적 설정: `step_configurator`(persona/skills/tools 자동 선택) + `job_planner`(optional 스텝 순서 결정).
> - Gate: 인간 판단 + Gate AI 대리 판단(`gate_ai.py`) + 일치율 측정(`gate_agreement_stats`).
> - DAG: `PlaybookStepSpec.after` 기반 레벨별 `asyncio.gather`.
> - 품질 관측: 페르소나 드리프트 감사 + 능력 감사 주간 자동 실행(`_weekly_audit_loop`).
> - 경로: `core/paths.py` 단일 출처(WORKSPACE_ROOT/MEMORY_ROOT, env 주입).

---

## 🚧 Week 1~2 스프린트 (2026-04-20)

### W1-1. StepSpec.parallel 그룹 실행 ✅
- `runner._execute` — 연속 `parallel=True` step을 `asyncio.gather`로 실행
- 이벤트: `job_step_group_started` / `job_step_group_done`
- `registry._parse` — 그룹 내부(마지막 제외) gate 걸림 시 WARNING

### W1-2. StepSpec.when 조건부 skip ✅
- `StepSpec.when` 필드 추가. `_eval_gate_condition` 재사용(contains/equals/not_empty)
- skip 시 `job_step_skipped` 이벤트

### W1-3. Gate AI 일치율 측정 ✅
- `job_gates`에 `ai_suggestion`/`ai_confidence`/`ai_model`/`ai_reason` 컬럼 추가(ALTER)
- `gate_ai.suggest_gate_decision` 말미에 `update_gate_ai` 저장
- `runner.resolve_gate` — AI 제안 vs Human 결정 비교 `gate_ai_agreement` 이벤트
- API: `GET /api/jobs/gates/agreement_stats?days=7`

### W2-1. Playbook DAG ✅
- `PlaybookStepSpec.id`(미지정 시 spec_id) / `after: list[str]` 추가
- `_execute_playbook` — 레벨별 의존 해결 gather, `_effective_deps`로 하위 호환
- `full_campaign.yaml` — research 이후 design_direction ∥ planning DAG 예시

### W2-2. Tool Registry 분할 (부분 완료, 점진 이동) 🔄
- `jobs/tools/__init__.py` — `load_plugin_tools()` 자동 로더
- `jobs/tools/_common.py` — `resolve_token` 공용 헬퍼
- 샘플 3개 이동 완료: `current_date.py` / `job_context.py` / `url_fetch.py`
- `tool_registry.py` — 플러그인 우선, legacy builtin fallback
- 테스트: `tests/test_tool_registry_manifest.py` — YAML 참조 id / 플러그인 로더 / 중복 id 검증
- **점진 이동 필요**: 남은 26개 도구(web_search, read_file, slack_post 등)를 차례로 `tools/<id>.py`로 이동

### W2-3. CI/mypy/TODOS 정합 ✅
- `server-tests.yml` mypy 경로 — 삭제된 `teamlead_review`/`autonomous_loop` 제거, `suggestion_filer`/`office` 추가
- `server/mypy.ini` — 해당 두 섹션 삭제
- `TODOS.md` — 현 아키텍처 기준으로 전면 재작성 (본 문서)

---

## 📦 백로그

### tool_registry 점진 이동 (W2-2 후속)
남은 26개 도구를 `jobs/tools/<id>.py`로 하나씩 이동. 각 단계에서 manifest 테스트가 회귀 방지.
우선순위: 외부 API 의존 있는 것부터 (slack_post, notion_write, pdf_generate → 파라미터 검증 단위 테스트 동반).

### 병렬 그룹 정적 검증
현재는 그룹 내 step이 서로의 output_key를 의존하면 런타임 빈 값. 정적 체크(스펙 로드 시 검사):
- 그룹 step의 prompt_template/inputs에서 `{other_group_step_output_key}` 패턴 감지 시 WARNING/ERROR.

### Gate AI agreement 대시보드
`GET /api/jobs/gates/agreement_stats` 응답을 InsightPanel에 시계열 그래프로 표시.
match_rate 추세가 하락하면 규칙/프롬프트 점검 시그널.

### Playbook DAG 시각화
Playbook 상세 UI에 `after` 의존 그래프를 Mermaid 또는 간단한 트리로 표시.

### P5-5 프롬프트 골든셋 회귀 테스트 (선택)
agent별 5~10개 대표 입력 + rubric으로 nightly CI. 기존 `persona_drift` 샘플링과 보완.

---

## 🧭 운영 가이드

### 주간 감사
`_weekly_audit_loop` — 부팅 10분 뒤 1회 + 7일 주기로 자동 실행.
- 페르소나 드리프트: 최근 48h 발화 10건 LLM-as-judge 채점
- 능력 감사: `scripts/capability_audit.py --register` (unused 있으면 팀장 건의 자동 등록)

수동 트리거: `POST /api/improvement/capability-audit?register=true` / `GET /api/team/persona-drift?hours=48`.

### Opus 잔여 관리
`/api/cost/today` → Opus 호출 수 + tier별 분포. Gate AI는 잔여 `_DEEP_SOFT_RESERVE=2` 이상일 때만 deep tier, 이하면 standard로 자동 전환.

### 도구 추가
1. `jobs/tools/<tool_id>.py` 생성 (TOOL_SPEC + execute)
2. `jobs/specs/*.yaml`에서 참조
3. `test_tool_registry_manifest.py`가 통과하는지 확인
