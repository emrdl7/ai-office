"""페르소나 드리프트 상시 감사 — P5-3

최근 48h autonomous+response 로그에서 agent별 10건 랜덤 샘플링 후
Haiku LLM-as-judge로 페르소나 일치도(0-10)를 채점한다.

6점 미만이 10건 중 3회 이상이면 `drift_detected` 이벤트를 발행한다.
"""
from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'
DRIFT_AGENTS = ['designer', 'developer', 'planner', 'qa', 'teamlead']
SAMPLE_SIZE = 10
LOW_THRESHOLD = 6  # 점수 6점 미만이면 저득점
MIN_LOW_TO_FLAG = 3  # 저득점 3건+이면 drift_detected


def _load_persona_summary(agent_name: str) -> str:
    """성격 / 대화 스타일 섹션만 로드 (간결하게)."""
    path = AGENTS_DIR / f'{agent_name}.md'
    if not path.exists():
        return ''
    text = path.read_text(encoding='utf-8')
    target_sections = {'성격', '대화 스타일'}
    out: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
        elif current in target_sections:
            out.append(line)
    return '\n'.join(out).strip()[:1200]


def _sample_recent_utterances(
    agent_id: str, hours: int = 48, size: int = SAMPLE_SIZE,
) -> list[dict]:
    """최근 hours 동안 agent의 autonomous+response 발화를 size개 무작위 추출."""
    from db.log_store import DB_PATH
    if not DB_PATH.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, message, timestamp FROM chat_logs "
            "WHERE agent_id=? AND event_type IN ('autonomous','response') "
            "AND timestamp >= ? AND length(message) >= 20 "
            "ORDER BY timestamp DESC LIMIT ?",
            (agent_id, cutoff, size * 4),
        ).fetchall()
    finally:
        conn.close()
    pool = [{'id': r['id'], 'message': r['message'], 'timestamp': r['timestamp']}
            for r in rows]
    if len(pool) <= size:
        return pool
    return random.sample(pool, size)


async def _score_utterance(
    persona: str, agent_name: str, message: str,
) -> tuple[int, str]:
    """Haiku로 페르소나 일치도 0-10 채점. 반환: (score, reason). 실패 시 (-1, err)."""
    from runners import model_router
    prompt = (
        f'에이전트 "{agent_name}"의 페르소나:\n{persona}\n\n'
        f'아래 발화가 위 페르소나(성격·대화 스타일)와 얼마나 일치하는지 0-10으로 채점하세요.\n'
        f'[발화]\n{message[:800]}\n\n'
        'JSON만 출력: {"score":0-10,"reason":"1문장"}'
    )
    try:
        raw, _ = await model_router.run(
            tier='nano', prompt=prompt,
            system='JSON만 출력. 설명 금지.',
            agent_id=f'persona_drift:{agent_name}', timeout=20.0,
        )
    except Exception as e:
        return -1, str(e)[:120]
    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        return -1, 'parse_fail'
    try:
        data = json.loads(m.group())
    except Exception:
        return -1, 'json_fail'
    try:
        score = int(data.get('score'))
    except Exception:
        return -1, 'score_fail'
    score = max(0, min(10, score))
    return score, str(data.get('reason') or '')[:200]


async def audit_agent(agent_id: str, hours: int = 48) -> dict[str, Any]:
    """단일 agent의 페르소나 드리프트 감사."""
    persona = _load_persona_summary(agent_id)
    if not persona:
        return {'agent': agent_id, 'error': 'persona 파일 없음'}

    samples = _sample_recent_utterances(agent_id, hours=hours)
    if not samples:
        return {'agent': agent_id, 'sampled': 0, 'avg_score': None,
                'low_count': 0, 'drift': False, 'examples': []}

    scored: list[dict] = []
    for s in samples:
        score, reason = await _score_utterance(persona, agent_id, s['message'])
        if score < 0:
            continue
        scored.append({
            'id': s['id'],
            'message': s['message'][:200],
            'timestamp': s['timestamp'],
            'score': score,
            'reason': reason,
        })

    if not scored:
        return {'agent': agent_id, 'sampled': len(samples), 'avg_score': None,
                'low_count': 0, 'drift': False, 'examples': [],
                'error': 'LLM 채점 전부 실패'}

    avg = sum(x['score'] for x in scored) / len(scored)
    low = [x for x in scored if x['score'] < LOW_THRESHOLD]
    drift = len(low) >= MIN_LOW_TO_FLAG

    return {
        'agent': agent_id,
        'sampled': len(scored),
        'avg_score': round(avg, 2),
        'low_count': len(low),
        'drift': drift,
        'examples': sorted(scored, key=lambda x: x['score'])[:3],  # 최저 3건
    }


async def run_persona_drift_audit(hours: int = 48) -> dict[str, Any]:
    """모든 DRIFT_AGENTS 감사 후 drift_detected 이벤트 발행."""
    results: list[dict] = []
    for agent_id in DRIFT_AGENTS:
        try:
            r = await audit_agent(agent_id, hours=hours)
            results.append(r)
        except Exception as e:
            logger.warning('[persona_drift] %s 감사 실패: %s', agent_id, e)
            results.append({'agent': agent_id, 'error': str(e)[:120]})

    # drift 발견 시 이벤트 발행
    drift_agents = [r['agent'] for r in results if r.get('drift')]
    if drift_agents:
        try:
            from log_bus.event_bus import event_bus, LogEvent
            for r in results:
                if not r.get('drift'):
                    continue
                await event_bus.publish(LogEvent(
                    agent_id='system',
                    event_type='drift_detected',
                    message=(
                        f'⚠ 페르소나 드리프트 감지 — {r["agent"]}: '
                        f'저득점 {r["low_count"]}/{r["sampled"]}, '
                        f'평균 {r["avg_score"]}'
                    ),
                    data={'agent': r['agent'], 'avg_score': r['avg_score'],
                          'low_count': r['low_count'], 'examples': r['examples']},
                ))
        except Exception as _e:
            logger.debug('[persona_drift] 이벤트 발행 실패: %s', _e)

    return {
        'hours': hours,
        'agents': results,
        'drift_agents': drift_agents,
        'ran_at': datetime.now(timezone.utc).isoformat(),
    }
