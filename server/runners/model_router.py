# 모델 Tier 라우터 — tier 이름으로 모델을 추상화하고 자동 폴백을 처리한다.
#
# Fallback 원칙:
#   - Claude 계열 실패 → Gemini 폴백
#   - Gemini 실패 → Claude Sonnet 폴백
#   Claude → Claude 폴백은 사용량 제한 시 의미 없으므로 허용하지 않는다.
from __future__ import annotations

import logging
from typing import Any

from runners.claude_runner import (
  run_claude_isolated,
  ClaudeRunnerError,
  ClaudeTimeoutError,
  PermanentClaudeRunnerError,
)
from runners.gemini_runner import run_gemini, GeminiRunnerError

logger = logging.getLogger(__name__)

# Tier 정의: (primary_runner, primary_model_or_None, fallback_runner)
# fallback_runner: 'gemini' | 'sonnet' | None
_TIER: dict[str, dict[str, Any]] = {
  # 빠른 분류/라우팅/단순 판단
  'nano': {
    'runner': 'claude',
    'model': 'claude-haiku-4-5-20251001',
    'fallback': 'gemini',
  },
  # 빠른 생성 (체크리스트, 요약)
  'fast': {
    'runner': 'claude',
    'model': 'claude-haiku-4-5-20251001',
    'fallback': 'gemini',
  },
  # 본업 (기획·디자인 브리프·코드·리뷰 섹션)
  'standard': {
    'runner': 'claude',
    'model': 'claude-sonnet-4-6',
    'fallback': 'gemini',
  },
  # 크리티컬 판단 (Gate 검수·IA 감사·최종 리뷰) — Job당 최대 2회
  'deep': {
    'runner': 'claude',
    'model': 'claude-opus-4-6',
    'fallback': 'gemini',
  },
  # 리서치·레퍼런스 큐레이션·긴 문서 처리 — Gemini가 primary
  'research': {
    'runner': 'gemini',
    'model': None,
    'fallback': 'sonnet',  # Gemini 실패 시 Claude Sonnet
  },
}


async def run(
  tier: str,
  prompt: str,
  system: str = '',
  timeout: float = 120.0,
  max_turns: int = 3,
  agent_id: str = '',
) -> tuple[str, str]:
  '''Tier 이름으로 LLM을 호출한다. 실패 시 자동 폴백.

  Args:
    tier: 'nano' | 'fast' | 'standard' | 'deep' | 'research'
    prompt: 사용자 프롬프트
    system: 시스템 프롬프트 (Claude용)
    timeout: 타임아웃 (초)
    max_turns: Claude max_turns
    agent_id: 비용 추적용 에이전트 식별자

  Returns:
    (LLM 응답 텍스트, 실제 사용된 모델명)

  Raises:
    RuntimeError: primary + fallback 모두 실패
  '''
  spec = _TIER.get(tier)
  if not spec:
    raise ValueError(f'알 수 없는 tier: {tier!r}. 가능한 값: {list(_TIER)}')

  full_prompt = f'{system}\n\n---\n\n{prompt}' if system else prompt

  # ── Primary 호출 ──────────────────────────────────────────────
  try:
    if spec['runner'] == 'claude':
      text = await run_claude_isolated(
        full_prompt,
        model=spec['model'],
        timeout=timeout,
        max_turns=max_turns,
      )
      model_used = spec['model']
    else:
      text = await run_gemini(prompt=prompt, system=system, timeout=timeout)
      model_used = 'gemini'
    _record(tier, spec, agent_id, prompt, text)
    return text, model_used

  except PermanentClaudeRunnerError:
    # CLI 인수 오류 — 폴백해도 동일 결과이므로 즉시 실패
    raise

  except (ClaudeRunnerError, ClaudeTimeoutError, GeminiRunnerError, Exception) as primary_err:
    fallback = spec.get('fallback')
    logger.warning(
      '[model_router] %s(%s) 실패 → fallback=%s | %s',
      spec['runner'], spec.get('model', ''), fallback, primary_err,
    )

    # 폴백 이벤트 발행 (event_bus는 선택적 — 없으면 생략)
    try:
      from log_bus.event_bus import event_bus, LogEvent
      await event_bus.publish(LogEvent(
        agent_id='system',
        event_type='model_fallback',
        message=(
          f'[모델 폴백] {spec["runner"]}({spec.get("model","")}) 실패 '
          f'→ {fallback} 폴백 | {str(primary_err)[:120]}'
        ),
        data={
          'tier': tier,
          'primary': spec['runner'],
          'primary_model': spec.get('model'),
          'fallback': fallback,
          'reason': str(primary_err)[:300],
        },
      ))
    except Exception:
      pass

  # ── Fallback 호출 ─────────────────────────────────────────────
  if not fallback:
    raise RuntimeError(f'[model_router] {tier} 실패, 폴백 없음')

  try:
    if fallback == 'gemini':
      text = await run_gemini(prompt=prompt, system=system, timeout=timeout)
      fb_model = 'gemini'
    else:
      # 'sonnet' — Gemini primary가 실패할 때 Claude Sonnet으로
      text = await run_claude_isolated(
        full_prompt,
        model='claude-sonnet-4-6',
        timeout=timeout,
        max_turns=max_turns,
      )
      fb_model = 'claude-sonnet-4-6'
    _record(tier, {'runner': fallback, 'model': fallback}, agent_id, prompt, text)
    return text, fb_model

  except Exception as fallback_err:
    raise RuntimeError(
      f'[model_router] {tier} primary+fallback 모두 실패 — '
      f'primary: {primary_err}, fallback: {fallback_err}'  # type: ignore[possibly-undefined]
    ) from fallback_err


def _record(
  tier: str,
  spec: dict[str, Any],
  agent_id: str,
  prompt: str,
  response: str,
) -> None:
  '''비용 추적 기록 (실패해도 무시).'''
  try:
    from runners.cost_tracker import record_call
    record_call(
      runner=spec['runner'],
      model=spec.get('model') or spec['runner'],
      agent_id=agent_id,
      prompt=prompt,
      response=response,
    )
  except Exception:
    pass
