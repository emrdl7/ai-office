'''자율 대화 품질 자동 평가 — insight density / consensus / synergy

24h 1회 백그라운드로 최근 자율 대화 50건을 Haiku로 평가:
  - insight_yes: 새로운 인사이트가 있었는가? (YES/NO)
  - consensus_yes: 구체적 액션 합의가 있었는가? (YES/NO)
  - synergy_yes: 동료 의견을 발전시켰는가? (YES/NO)

결과는 JSON 캐시로 저장 → /api/autonomous/stats가 읽어 노출.
'''
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / 'data' / 'conversation_quality.json'


def load_quality_cache() -> dict[str, Any]:
  '''최근 평가 결과 로드. 24h 초과면 빈 dict.'''
  try:
    raw = _CACHE_PATH.read_text(encoding='utf-8')
    data = json.loads(raw)
    last_at = data.get('evaluated_at', '')
    if last_at:
      last_dt = datetime.fromisoformat(last_at.replace('Z', '+00:00'))
      if (datetime.now(timezone.utc) - last_dt) < timedelta(hours=26):
        return data
  except Exception:
    pass
  return {}


def _save_cache(data: dict[str, Any]) -> None:
  try:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
  except Exception:
    logger.debug('품질 캐시 저장 실패', exc_info=True)


async def evaluate_recent_conversations(office: Any, sample_size: int = 50) -> dict[str, Any]:
  '''최근 자율 대화 sample_size건을 평가.

  thread_id 단위로 묶어서 평가 (한 토론 = 한 평가 단위).
  '''
  from db.log_store import load_logs
  from runners.claude_runner import run_claude_isolated

  logs = load_logs(limit=200)
  threads: dict[str, list[dict]] = defaultdict(list)
  for log in logs:
    if log.get('event_type') != 'autonomous':
      continue
    data = log.get('data') or {}
    tid = data.get('thread_id', '')
    if tid:
      threads[tid].append(log)

  # 최소 2개 이상 메시지가 있는 thread만 평가 (단발 발화는 제외)
  evaluable = [(tid, msgs) for tid, msgs in threads.items() if len(msgs) >= 2]
  evaluable.sort(key=lambda x: x[1][0].get('id', ''), reverse=True)
  evaluable = evaluable[:sample_size]

  if not evaluable:
    return {
      'evaluated_at': datetime.now(timezone.utc).isoformat(),
      'sample_size': 0,
      'insight_density': 0.0,
      'consensus_rate': 0.0,
      'synergy_score': 0.0,
      'evaluated_threads': 0,
    }

  insight_count = 0
  consensus_count = 0
  synergy_count = 0
  evaluated = 0

  for tid, msgs in evaluable:
    chain_text = '\n'.join(
      f'[{m.get("agent_id", "")}] {(m.get("message", "") or "")[:200]}'
      for m in msgs
    )
    if len(chain_text) < 100:
      continue
    try:
      raw = await run_claude_isolated(
        prompt=(
          f'다음은 AI 팀의 자율 대화입니다:\n\n{chain_text}\n\n'
          f'[평가 — JSON으로만 출력]\n'
          f'1. insight: 새로운 구체적 인사이트(도구명/수치/사례)가 있는가? YES/NO\n'
          f'2. consensus: 2명 이상이 동의한 구체적 액션이 있는가? YES/NO\n'
          f'3. synergy: 동료 의견을 발전시키거나 보완했는가? (단순 동의/반복 X) YES/NO\n\n'
          f'출력: {{"insight":"YES","consensus":"NO","synergy":"YES"}}'
        ),
        timeout=20.0, model='claude-haiku-4-5-20251001',
      )
      m = re.search(r'\{[\s\S]*?\}', raw)
      if not m:
        continue
      parsed = json.loads(m.group())
      evaluated += 1
      if str(parsed.get('insight', '')).upper() == 'YES':
        insight_count += 1
      if str(parsed.get('consensus', '')).upper() == 'YES':
        consensus_count += 1
      if str(parsed.get('synergy', '')).upper() == 'YES':
        synergy_count += 1
    except Exception:
      logger.debug('thread 평가 실패: %s', tid, exc_info=True)

  result = {
    'evaluated_at': datetime.now(timezone.utc).isoformat(),
    'sample_size': len(evaluable),
    'evaluated_threads': evaluated,
    'insight_density': round(insight_count / evaluated, 3) if evaluated else 0.0,
    'consensus_rate': round(consensus_count / evaluated, 3) if evaluated else 0.0,
    'synergy_score': round(synergy_count / evaluated, 3) if evaluated else 0.0,
  }
  _save_cache(result)
  logger.info(
    '대화 품질 평가 완료: insight=%.2f, consensus=%.2f, synergy=%.2f (n=%d)',
    result['insight_density'], result['consensus_rate'], result['synergy_score'], evaluated,
  )
  return result


async def quality_eval_loop(office: Any) -> None:
  '''24h 주기로 평가 실행 — main.py에서 background task로 시작.

  대화 품질 평가 + 페르소나 드리프트 감지를 함께 실행한다.
  '''
  await asyncio.sleep(300)  # 시작 후 5분 대기
  while True:
    try:
      cache = load_quality_cache()
      if not cache:
        await evaluate_recent_conversations(office)
      # 페르소나 드리프트 평가 — 동기 실행 (DB만 조회, LLM 미사용)
      from orchestration.persona_drift import evaluate_all_agents, load_drift_cache
      from log_bus.event_bus import LogEvent
      drift_cache = load_drift_cache()
      if not drift_cache:
        result = evaluate_all_agents()
        drifting = result.get('drifting', [])
        if drifting:
          try:
            await office.event_bus.publish(LogEvent(
              agent_id='system', event_type='system_notice',
              message=f'⚠️ 페르소나 드리프트 감지: {", ".join(drifting)} — 시스템 프롬프트 재주입 검토 필요',
            ))
          except Exception:
            pass
    except Exception:
      logger.debug('품질 평가 루프 오류', exc_info=True)
    await asyncio.sleep(86400)  # 24h
