'''LLM 비용/호출 모니터링 — 호출 횟수, 추정 토큰, 일별 한도

각 runner(claude/gemini)가 호출 시 record_call()을 호출하여
일별 누적 통계를 SQLite에 기록한다.
'''
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / 'data' / 'cost.db'

# 모델별 입력/출력 1K 토큰당 USD (대략) — Claude Haiku, Sonnet, Opus 기준
# Gemini는 무료 티어 가정
_PRICE_TABLE: dict[str, tuple[float, float]] = {
  'claude-haiku-4-5-20251001': (0.0008, 0.004),
  'claude-haiku': (0.0008, 0.004),
  'claude-sonnet-4-6': (0.003, 0.015),
  'claude-sonnet': (0.003, 0.015),
  'claude-opus-4-7': (0.015, 0.075),
  'claude-opus-4-6': (0.015, 0.075),
  'claude-opus': (0.015, 0.075),
  'gemini': (0.0, 0.0),
}

# 일 한도 (USD)
DAILY_BUDGET_USD = 15.0


_db_conn: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
  global _db_conn
  if _db_conn is not None:
    return _db_conn
  _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
  c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
  c.execute('''
    CREATE TABLE IF NOT EXISTS llm_calls (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      runner TEXT NOT NULL,
      model TEXT,
      agent_id TEXT,
      prompt_chars INTEGER,
      response_chars INTEGER,
      est_input_tokens INTEGER,
      est_output_tokens INTEGER,
      est_cost_usd REAL
    )
  ''')
  c.execute('CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts)')
  c.commit()
  _db_conn = c
  return c


def _estimate_tokens(text: str) -> int:
  '''매우 단순한 추정 — 4자당 1토큰 (영어 기준), 한국어는 보정.'''
  if not text:
    return 0
  # 한글이 많으면 토큰 더 잡힘 — 보정 계수 1.5
  korean_ratio = sum(1 for c in text if '\uac00' <= c <= '\ud7a3') / max(len(text), 1)
  base = len(text) / 4
  return int(base * (1 + korean_ratio * 0.5))


def _estimate_cost(model: str, in_toks: int, out_toks: int) -> float:
  for key, (in_price, out_price) in _PRICE_TABLE.items():
    if key in model:
      return round(in_toks * in_price / 1000 + out_toks * out_price / 1000, 6)
  return 0.0


def record_call(
  runner: str,
  model: str = '',
  agent_id: str = '',
  prompt: str = '',
  response: str = '',
) -> None:
  '''LLM 호출 기록. 비동기 안전하지 않으므로 짧게 finishes.'''
  try:
    in_toks = _estimate_tokens(prompt)
    out_toks = _estimate_tokens(response)
    cost = _estimate_cost(model, in_toks, out_toks)
    c = _conn()
    c.execute(
      'INSERT INTO llm_calls (ts, runner, model, agent_id, prompt_chars, response_chars, '
      'est_input_tokens, est_output_tokens, est_cost_usd) VALUES (?,?,?,?,?,?,?,?,?)',
      (datetime.now(timezone.utc).isoformat(), runner, model, agent_id,
       len(prompt or ''), len(response or ''), in_toks, out_toks, cost),
    )
    c.commit()
  except Exception:
    logger.debug('LLM 호출 기록 실패', exc_info=True)


def get_today_stats() -> dict[str, Any]:
  '''오늘 누적 통계.'''
  today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
  c = _conn()
  c.row_factory = sqlite3.Row
  rows = c.execute(
    "SELECT runner, model, count(*) AS calls, "
    "sum(est_input_tokens) AS in_toks, sum(est_output_tokens) AS out_toks, "
    "sum(est_cost_usd) AS cost "
    "FROM llm_calls WHERE ts LIKE ? GROUP BY runner, model",
    (f'{today}%',),
  ).fetchall()
  total_cost = 0.0
  by_model: list[dict[str, Any]] = []
  for r in rows:
    cost = float(r['cost'] or 0)
    total_cost += cost
    by_model.append({
      'runner': r['runner'],
      'model': r['model'],
      'calls': r['calls'],
      'input_tokens': r['in_toks'] or 0,
      'output_tokens': r['out_toks'] or 0,
      'cost_usd': round(cost, 4),
    })
  return {
    'date': today,
    'total_cost_usd': round(total_cost, 4),
    'budget_usd': DAILY_BUDGET_USD,
    'budget_remaining': round(DAILY_BUDGET_USD - total_cost, 4),
    'budget_exceeded': total_cost >= DAILY_BUDGET_USD,
    'by_model': by_model,
  }


def is_budget_exceeded() -> bool:
  '''자율 루프에서 호출 — 한도 초과 시 True 반환.'''
  return get_today_stats().get('budget_exceeded', False)


def get_daily_costs(days: int = 7) -> list[dict[str, Any]]:
  '''최근 N일 일별 비용·호출 수. 스파크라인용.'''
  from datetime import timedelta, datetime as _dt
  days = max(1, min(days, 90))
  c = _conn()
  c.row_factory = sqlite3.Row
  end = _dt.now(timezone.utc)
  start = end - timedelta(days=days - 1)
  rows = c.execute(
    "SELECT substr(ts,1,10) AS d, sum(est_cost_usd) AS cost, count(*) AS calls "
    "FROM llm_calls WHERE ts >= ? GROUP BY d ORDER BY d",
    (start.strftime('%Y-%m-%dT00:00:00'),),
  ).fetchall()
  by_date = {r['d']: {'cost': float(r['cost'] or 0.0), 'calls': int(r['calls'] or 0)} for r in rows}
  # 날짜 범위 채우기 (비어있어도 0으로)
  out: list[dict[str, Any]] = []
  for i in range(days):
    d = (start + timedelta(days=i)).strftime('%Y-%m-%d')
    slot = by_date.get(d, {'cost': 0.0, 'calls': 0})
    out.append({'date': d, 'total_cost_usd': round(slot['cost'], 4), 'calls': slot['calls']})
  return out
