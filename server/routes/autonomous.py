# 자율 대화 관측 통계 엔드포인트 — P3 로드맵
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get('/api/autonomous/stats')
async def autonomous_stats(hours: int = 24) -> dict:
  '''최근 N시간 자율 대화 관측 지표.

  - total_count: autonomous 발화 수
  - mode_distribution: 모드별 분포 (joke/improvement/reaction/closing/trend_research)
  - pass_drop_count: [PASS] 드롭 건수
  - pass_drop_rate: PASS 드롭율 (dropped / (published + dropped))
  - dedup_skip_count: 중복 게이트로 skip된 건의 수
  - top_keywords: 반복 키워드 top5
  - stuck_count: 주제 고착 감지 횟수
  '''
  from db.log_store import DB_PATH as LOG_DB
  from db.suggestion_store import DB_PATH as SUGG_DB

  cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

  # ── 로그 DB 쿼리 ───────────────────────────────────────────────
  log_conn = sqlite3.connect(str(LOG_DB))
  log_conn.row_factory = sqlite3.Row

  # autonomous 발화
  rows = log_conn.execute(
    'SELECT agent_id, message, data FROM chat_logs '
    "WHERE event_type='autonomous' AND timestamp >= ? ORDER BY timestamp DESC LIMIT 500",
    (cutoff,),
  ).fetchall()

  # PASS 드롭 건수
  pass_row = log_conn.execute(
    'SELECT count(*) AS n FROM chat_logs '
    "WHERE event_type='autonomous_pass' AND timestamp >= ?",
    (cutoff,),
  ).fetchone()
  pass_count: int = pass_row['n'] if pass_row else 0

  # stuck 감지 건수
  stuck_row = log_conn.execute(
    'SELECT count(*) AS n FROM chat_logs '
    "WHERE event_type='autonomous_stuck' AND timestamp >= ?",
    (cutoff,),
  ).fetchone()
  stuck_count: int = stuck_row['n'] if stuck_row else 0

  log_conn.close()

  # ── 집계 ────────────────────────────────────────────────────────
  total = len(rows)
  mode_dist: dict[str, int] = {}
  keyword_bag: Counter[str] = Counter()
  thread_counts: Counter[str] = Counter()  # thread_id별 메시지 수

  for r in rows:
    data = json.loads(r['data']) if r['data'] else {}
    mode = (data.get('autonomous_mode') or 'unknown').strip()
    mode_dist[mode] = mode_dist.get(mode, 0) + 1
    tid = (data.get('thread_id') or '').strip()
    if tid:
      thread_counts[tid] += 1
    try:
      from orchestration.office import _extract_keywords
      for kw in _extract_keywords(r['message'] or ''):
        if len(kw) >= 3:
          keyword_bag[kw] += 1
    except Exception:
      pass

  top_keywords = [kw for kw, _ in keyword_bag.most_common(5)]

  # 스레드 깊이 통계
  thread_depths = list(thread_counts.values()) if thread_counts else []
  avg_thread_depth = round(sum(thread_depths) / len(thread_depths), 2) if thread_depths else 0.0
  max_thread_depth = max(thread_depths) if thread_depths else 0
  pass_total = total + pass_count
  pass_drop_rate = round(pass_count / pass_total, 3) if pass_total > 0 else 0.0

  # ── 건의 이벤트 DB — 중복 skip 건수 ───────────────────────────
  dedup_count = 0
  try:
    sugg_conn = sqlite3.connect(str(SUGG_DB))
    sugg_conn.row_factory = sqlite3.Row
    dedup_row = sugg_conn.execute(
      "SELECT count(*) AS n FROM suggestion_events "
      "WHERE kind='suggestion_deduplicated' AND ts >= ?",
      (cutoff,),
    ).fetchone()
    dedup_count = dedup_row['n'] if dedup_row else 0
    sugg_conn.close()
  except Exception:
    pass

  # 실질 PASS율 — pass_drop_rate는 tracked 발화만 기준이므로
  # pass_rate_effective로 전체 기준 실질율도 제공
  pass_rate_effective = round(pass_count / (pass_count + total) , 3) if (pass_count + total) > 0 else 0.0

  return {
    'period_hours': hours,
    'total_count': total,
    'mode_distribution': mode_dist,
    'pass_drop_count': pass_count,
    'pass_drop_rate': pass_drop_rate,
    'pass_rate_effective': pass_rate_effective,
    'dedup_skip_count': dedup_count,
    'top_keywords': top_keywords,
    'stuck_count': stuck_count,
    'avg_thread_depth': avg_thread_depth,
    'max_thread_depth': max_thread_depth,
    'thread_count': len(thread_depths),
    'quality': _load_quality_cache(),
    'persona_drift': _load_drift_cache(),
    'cost_today': _load_cost_today(),
  }


def _load_cost_today() -> dict:
  try:
    from runners.cost_tracker import get_today_stats
    return get_today_stats()
  except Exception:
    return {}


def _load_drift_cache() -> dict:
  try:
    from orchestration.persona_drift import load_drift_cache
    cache = load_drift_cache()
    if cache:
      return {
        'evaluated_at': cache.get('evaluated_at', ''),
        'drifting': cache.get('drifting', []),
        'agents': {
          aid: {'density': r.get('density', 0.0), 'drifting': r.get('drifting', False)}
          for aid, r in (cache.get('agents') or {}).items()
        },
      }
  except Exception:
    pass
  return {'evaluated_at': '', 'drifting': [], 'agents': {}}


def _load_quality_cache() -> dict:
  try:
    from orchestration.conversation_quality import load_quality_cache
    cache = load_quality_cache()
    if cache:
      return {
        'evaluated_at': cache.get('evaluated_at', ''),
        'insight_density': cache.get('insight_density', 0.0),
        'consensus_rate': cache.get('consensus_rate', 0.0),
        'synergy_score': cache.get('synergy_score', 0.0),
        'evaluated_threads': cache.get('evaluated_threads', 0),
      }
  except Exception:
    pass
  return {'evaluated_at': '', 'insight_density': 0.0, 'consensus_rate': 0.0, 'synergy_score': 0.0, 'evaluated_threads': 0}
