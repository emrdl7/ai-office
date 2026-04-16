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

# deep tier (Opus) 일일 호출 한도
_DEEP_TIER_DAILY_LIMIT = 10

# 에이전트별 허용 tier 목록 (meta-router가 이 범위 내에서 선택)
AGENT_ALLOWED_TIERS: dict[str, list[str]] = {
  'qa':        ['nano', 'fast', 'standard'],
  'planner':   ['standard', 'deep', 'research'],
  'developer': ['standard', 'deep', 'research'],
  'designer':  ['fast', 'standard', 'deep'],
}
_DEFAULT_ALLOWED = ['fast', 'standard', 'deep']

_CLASSIFY_SYSTEM = (
  'You are a routing classifier. '
  'Given a task prompt, output exactly ONE tier name from this list: '
  'nano, fast, standard, deep, research\n\n'
  'Definitions:\n'
  '- nano: simple yes/no, single-fact lookup, trivial classification\n'
  '- fast: short list, brief summary, quick generation (< 1 paragraph)\n'
  '- standard: typical analysis, code writing, document section, design brief\n'
  '- deep: critical judgment, final gate review, complex architectural decision\n'
  '- research: multi-source research, long document processing, reference curation\n\n'
  'Output the tier name only. No explanation.'
)

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
    'model': 'claude-opus-4-7',
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

  # deep tier 일일 한도 초과 시 standard로 강등
  if tier == 'deep':
    try:
      from runners.cost_tracker import get_today_stats
      stats = get_today_stats()
      opus_calls = sum(m['calls'] for m in stats['by_model'] if 'opus' in (m.get('model') or ''))
      if opus_calls >= _DEEP_TIER_DAILY_LIMIT:
        logger.warning(
          '[model_router] deep tier 일일 한도 초과 (%d/%d) → standard 강등',
          opus_calls, _DEEP_TIER_DAILY_LIMIT,
        )
        tier = 'standard'
        spec = _TIER['standard']
    except Exception:
      pass

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

  except (ClaudeRunnerError, ClaudeTimeoutError, GeminiRunnerError) as primary_err:
    _primary_err_str = str(primary_err)  # except 블록 종료 후 primary_err는 삭제되므로 미리 저장
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
          f'→ {fallback} 폴백 | {_primary_err_str[:120]}'
        ),
        data={
          'tier': tier,
          'primary': spec['runner'],
          'primary_model': spec.get('model'),
          'fallback': fallback,
          'reason': _primary_err_str[:300],
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
      f'primary: {_primary_err_str}, fallback: {fallback_err}'
    ) from fallback_err


async def classify_tier(prompt: str, agent_id: str = '') -> str:
  '''Haiku로 프롬프트 복잡도를 분류해 에이전트 허용 범위 내 tier를 반환한다.

  분류 실패 시 에이전트 allowed 목록의 첫 번째 tier(가장 낮은 비용)로 폴백.
  '''
  allowed = AGENT_ALLOWED_TIERS.get(agent_id, _DEFAULT_ALLOWED)
  preview = prompt[:600]
  try:
    raw = await run_claude_isolated(
      f'{_CLASSIFY_SYSTEM}\n\n---\n\n{preview}',
      model='claude-haiku-4-5-20251001',
      timeout=15.0,
      max_turns=1,
    )
    candidate = raw.strip().lower().split()[0]
    if candidate in allowed:
      return candidate
    # 허용 범위 밖이면 allowed 목록에서 가장 가까운 tier로 조정
    _ORDER = ['nano', 'fast', 'standard', 'deep', 'research']
    c_idx = _ORDER.index(candidate) if candidate in _ORDER else 2
    closest = min(allowed, key=lambda t: abs(_ORDER.index(t) - c_idx))
    logger.debug('[classify_tier] %s → %s (조정: %s)', agent_id, closest, candidate)
    return closest
  except Exception as e:
    logger.debug('[classify_tier] 분류 실패 → 폴백 | %s', e)
    return allowed[0]


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
