"""잡 플래너 — Haiku가 잡 시작 시 실행할 스텝 목록·순서를 결정한다."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobs.models import JobSpec

logger = logging.getLogger(__name__)


def _build_plan_prompt(spec: JobSpec, input_data: dict) -> str:
    required_steps = [s for s in spec.steps if not s.optional]
    optional_steps = [s for s in spec.steps if s.optional]

    req_lines = '\n'.join(
        f'- {s.id}: {s.prompt_template[:120].strip()}'
        for s in required_steps
    )
    opt_lines = '\n'.join(
        f'- {s.id}: {s.prompt_template[:120].strip()}'
        for s in optional_steps
    )

    # input 요약 (민감 정보 최소화, 200자 이내)
    input_summary = json.dumps(
        {k: str(v)[:150] for k, v in input_data.items() if v},
        ensure_ascii=False,
    )[:400]

    return f"""당신은 AI 잡 오케스트레이터입니다.
아래 잡 요청과 사용 가능한 스텝 목록을 보고, 실제로 실행이 필요한 스텝과 순서를 결정하세요.

[잡 정보]
제목: {spec.title}
설명: {spec.description}

[사용자 입력]
{input_summary}

[필수 스텝 — 항상 포함]
{req_lines}

[선택 스텝 — 필요한 것만 포함]
{opt_lines}

결정 기준:
- 사용자 입력이 이미 충분히 상세하면 분석/계획 단계를 생략해도 됨
- 단순한 요청이면 리뷰/검토 단계를 생략해도 됨
- 시각화(diagram, chart)는 명시적 요청이 있거나 복잡한 구조일 때만 포함
- 결과물 묶음(bundle)이나 summary는 최종 납품용이 아니라면 생략 가능
- 스텝 순서는 의존관계를 반드시 지킬 것 (앞 스텝의 output을 뒤 스텝이 사용)

전체 스텝 ID 목록(순서 포함)을 JSON 배열로만 출력하세요 (설명 없이):
["step_id_1", "step_id_2", ...]"""


async def plan_job(spec: JobSpec, input_data: dict) -> list[str]:
    """Haiku로 실행할 스텝 목록과 순서를 결정한다.

    Returns:
        실행할 step.id 목록 (순서 보장). 실패 시 전체 스텝 순서 반환.
    """
    all_step_ids = [s.id for s in spec.steps]

    # optional 스텝이 하나도 없으면 플래너 호출 불필요
    if not any(s.optional for s in spec.steps):
        return all_step_ids

    try:
        from runners import model_router
        prompt = _build_plan_prompt(spec, input_data)
        raw, _ = await model_router.run(
            tier='nano',
            prompt=prompt,
            system='JSON 배열만 출력하세요. 설명을 절대 추가하지 마세요.',
            agent_id=f'job_planner:{spec.id}',
            timeout=20.0,
        )
        raw = raw.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        selected: list[str] = json.loads(raw.strip())
    except Exception as e:
        logger.warning('[job_planner] Haiku 플랜 실패(%s) — 전체 스텝 실행: %s', spec.id, e)
        return all_step_ids

    # 검증: spec에 존재하는 ID만, 필수 스텝은 반드시 포함
    valid_ids = set(all_step_ids)
    required_ids = {s.id for s in spec.steps if not s.optional}

    cleaned = [sid for sid in selected if sid in valid_ids]

    # 누락된 필수 스텝 보충 (원래 순서 유지)
    cleaned_set = set(cleaned)
    for step in spec.steps:
        if step.id in required_ids and step.id not in cleaned_set:
            # 원래 순서상 앞 스텝 바로 뒤에 삽입
            idx = all_step_ids.index(step.id)
            insert_pos = next(
                (i for i, sid in enumerate(cleaned) if all_step_ids.index(sid) > idx),
                len(cleaned),
            )
            cleaned.insert(insert_pos, step.id)
            cleaned_set.add(step.id)

    if not cleaned:
        return all_step_ids

    logger.info('[job_planner] %s 실행 계획: %s', spec.id, cleaned)
    return cleaned
