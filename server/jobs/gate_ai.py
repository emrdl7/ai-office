"""Gate AI 대리 판단 — Opus 여유 시 Gate 도달 시점에 자동 판단을 제안한다.

사용자는 제안을 보고 1-탭으로 confirm만 하면 된다.
실패·한도초과·타임아웃은 조용히 skip (사용자 판단 흐름 방해 금지).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_DEEP_SOFT_RESERVE = 2  # Opus 일일 한도에서 최소 이만큼 남아있을 때만 사용


def _opus_has_room() -> bool:
    """deep tier 호출 가능 여부 — 소프트 예약분 이상 남아있어야 True."""
    try:
        from runners.cost_tracker import get_today_stats
        from runners.model_router import _DEEP_TIER_DAILY_LIMIT
        stats = get_today_stats()
        opus_calls = sum(
            m.get('calls', 0) for m in stats.get('by_model', [])
            if 'opus' in (m.get('model') or '').lower()
        )
        return opus_calls + _DEEP_SOFT_RESERVE <= _DEEP_TIER_DAILY_LIMIT
    except Exception:
        return False


_SYSTEM = (
    '당신은 AI Job 파이프라인의 Gate 검수자입니다. '
    '산출물을 비판적으로 평가하고 다음 중 하나를 권고하세요:\n'
    '- approve: 그대로 통과 가능 (명백히 목표 달성)\n'
    '- revise: 부분 수정 필요 (구체 근거 제시)\n'
    '- reject: 재작업 필요 (핵심 결함)\n\n'
    'JSON만 출력:\n'
    '{"decision":"approve|revise|reject","confidence":0-100,'
    '"reason":"1-2문장","concerns":["항목1","항목2"]}'
)


def _build_prompt(gate_prompt: str, step_output: str, job_title: str) -> str:
    out = step_output[:4000] if step_output else '(빈 출력)'
    return (
        f'[Job 제목]\n{job_title}\n\n'
        f'[Gate 목적]\n{gate_prompt}\n\n'
        f'[검수 대상 산출물]\n{out}\n\n'
        '평가 후 JSON으로만 응답하세요.'
    )


async def suggest_gate_decision(
    job_id: str,
    job_title: str,
    gate_id: str,
    gate_prompt: str,
    step_output: str,
    emit: Any,
) -> None:
    """Gate 도달 시 비동기로 호출 — AI 대리 판단을 event로 발행.

    - Opus 여유 있으면 deep, 없으면 standard tier 사용
    - 어떤 실패도 Gate 흐름을 중단시키지 않음
    """
    from runners import model_router

    tier = 'deep' if _opus_has_room() else 'standard'
    try:
        raw, model_used = await model_router.run(
            tier=tier,
            prompt=_build_prompt(gate_prompt, step_output, job_title),
            system=_SYSTEM,
            agent_id=f'gate_ai:{gate_id}',
            timeout=60.0,
        )
    except Exception as e:
        logger.debug('[gate_ai] LLM 호출 실패 (%s): %s', gate_id, e)
        return

    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        logger.debug('[gate_ai] JSON 파싱 실패: %s', raw[:120])
        return
    try:
        result = json.loads(m.group())
    except Exception:
        return

    decision = (result.get('decision') or '').strip().lower()
    if decision not in ('approve', 'revise', 'reject'):
        return

    payload = {
        'job_id': job_id,
        'gate_id': gate_id,
        'decision': decision,
        'confidence': int(result.get('confidence') or 0),
        'reason': (result.get('reason') or '')[:300],
        'concerns': [str(c)[:120] for c in (result.get('concerns') or [])][:5],
        'model': model_used,
        'tier': tier,
    }
    icon = {'approve': '👍', 'revise': '✏️', 'reject': '🚫'}.get(decision, '❓')
    msg = (
        f'{icon} Gate AI 제안 ({decision}, conf={payload["confidence"]}): '
        f'{payload["reason"]}'
    )
    await emit(msg, 'job_gate_ai_suggestion', payload)

    # DB 영속화 — 이후 사람 결정과 일치율 집계용
    try:
        from db.job_store import update_gate_ai
        update_gate_ai(
            job_id=job_id, gate_id=gate_id,
            suggestion=decision, confidence=payload['confidence'],
            model=model_used, reason=payload['reason'],
        )
    except Exception as _e:
        logger.debug('[gate_ai] DB 저장 실패: %s', _e)


def fire_and_forget(
    job_id: str,
    job_title: str,
    gate_id: str,
    gate_prompt: str,
    step_output: str,
    emit: Any,
) -> asyncio.Task:
    """Gate 등록 직후 호출 — task 반환하지만 결과는 기다리지 않는다."""
    return asyncio.create_task(
        suggest_gate_decision(job_id, job_title, gate_id, gate_prompt, step_output, emit)
    )
