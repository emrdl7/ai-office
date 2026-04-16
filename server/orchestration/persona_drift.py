'''에이전트 페르소나 드리프트 감지

각 에이전트의 핵심 페르소나 키워드 (성격/가치관 단어)가 최근 N건 발화에
얼마나 등장하는지 추적한다. 임계 미달 시 시스템 알림 + 시스템 프롬프트
재주입 강도를 높인다.

페르소나 키워드는 agents/{name}.md를 그대로 따라간다 — 하드코딩 없이
프롬프트에서 자주 등장하는 명사를 자동 추출하면 좋지만, 단순함을 위해
agent_id별 손수 정의 (8일 운영 데이터로 검증된 키워드).
'''
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / 'data' / 'persona_drift.json'

# 에이전트별 페르소나 핵심 키워드 — 발화에 자주 등장해야 함
_PERSONA_KEYWORDS: dict[str, list[str]] = {
  'teamlead': ['단순', '본질', '명확', '결정', '비전', '집중', '핵심', '미친', '완벽'],
  'planner': ['측정', '관리', '체계', '구조', '지식', '효율', '근거', '전략', '결과'],
  'designer': ['디테일', '본질', '재료', '물성', '경험', '단순', '정수', '소재', '완성'],
  'developer': ['논리', '형식', '정확', '알고리즘', '자동화', '계산', '증명', '추상', '명세'],
  'qa': ['통계', '시스템', '프로세스', 'PDCA', '근본', '개선', '데이터', '품질', '변동'],
}

# 임계값: 최근 20건 발화에서 페르소나 키워드 등장률
DRIFT_THRESHOLD = 0.15  # 발화당 평균 0.15개 미만이면 드리프트


def get_persona_keywords(agent_id: str) -> list[str]:
  return _PERSONA_KEYWORDS.get(agent_id, [])


def measure_persona_strength(agent_id: str, sample_size: int = 20) -> dict[str, Any]:
  '''최근 sample_size건 발화에서 페르소나 키워드 밀도 측정.'''
  import sqlite3
  from db.log_store import DB_PATH

  keywords = get_persona_keywords(agent_id)
  if not keywords:
    return {'agent_id': agent_id, 'sampled': 0, 'density': 0.0, 'drifting': False}

  conn = sqlite3.connect(str(DB_PATH))
  conn.row_factory = sqlite3.Row
  rows = conn.execute(
    "SELECT message FROM chat_logs "
    "WHERE agent_id=? AND event_type IN ('autonomous','response') "
    "AND length(message) > 30 "
    "ORDER BY timestamp DESC LIMIT ?",
    (agent_id, sample_size),
  ).fetchall()
  conn.close()

  if not rows:
    return {'agent_id': agent_id, 'sampled': 0, 'density': 0.0, 'drifting': False}

  hit_total = 0
  per_keyword: Counter[str] = Counter()
  for r in rows:
    msg = r['message'] or ''
    for kw in keywords:
      if kw in msg:
        hit_total += 1
        per_keyword[kw] += 1

  density = round(hit_total / len(rows), 3)
  drifting = density < DRIFT_THRESHOLD

  return {
    'agent_id': agent_id,
    'sampled': len(rows),
    'density': density,
    'drifting': drifting,
    'threshold': DRIFT_THRESHOLD,
    'top_keywords': per_keyword.most_common(5),
    'missing_keywords': [k for k in keywords if k not in per_keyword][:5],
  }


def evaluate_all_agents() -> dict[str, Any]:
  '''전체 에이전트 페르소나 강도 측정 + 캐시 저장.'''
  results: dict[str, Any] = {}
  drifting_agents: list[str] = []
  for agent_id in _PERSONA_KEYWORDS:
    r = measure_persona_strength(agent_id)
    results[agent_id] = r
    if r.get('drifting'):
      drifting_agents.append(agent_id)

  cache = {
    'evaluated_at': datetime.now(timezone.utc).isoformat(),
    'agents': results,
    'drifting': drifting_agents,
  }
  try:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
  except Exception:
    logger.debug('드리프트 캐시 저장 실패', exc_info=True)
  if drifting_agents:
    logger.warning('페르소나 드리프트 감지: %s', drifting_agents)
  return cache


def load_drift_cache() -> dict[str, Any]:
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
