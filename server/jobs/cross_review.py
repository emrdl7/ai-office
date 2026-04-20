"""교차 리뷰 엔진 — Job 완료 후 다른 모델이 산출물을 검수한다.

설계: Job 주 모델의 반대쪽 모델이 리뷰한다.
 - 주 산출물이 Claude 계열이면 Gemini가 리뷰
 - 주 산출물이 Gemini면 Opus(deep tier)가 리뷰 — Opus 잔여 여유 있을 때만
일일 한도(`DAILY_LIMIT`)를 넘으면 skip.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from jobs.models import JobRun

logger = logging.getLogger(__name__)

DAILY_LIMIT = 5

_DATA_DIR = Path(__file__).parent.parent / 'data'
_review_count_file = _DATA_DIR / 'cross_review_count.json'

# 리뷰 대상 artifact 키 우선순위
_REVIEW_ARTIFACT_KEYS = ['report', 'brief', 'findings', 'insights', 'final_markup', 'plan']

_OPUS_SYSTEM = (
    '당신은 최고 수준의 AI 산출물 검토 전문가입니다. '
    'Gemini가 생성한 산출물을 비판적으로 검토하고, '
    '품질·정확성·완성도·실용성을 엄격하게 평가하세요.\n\n'
    '다음 형식으로 반드시 응답하세요:\n'
    'SCORE: [0-100 정수]\n'
    'FEEDBACK: [전체 평가 (3-5문장)]\n'
    'IMPROVEMENTS:\n'
    '- [개선 제안 1]\n'
    '- [개선 제안 2]\n'
    '- [개선 제안 3]\n'
)

_GEMINI_SYSTEM = (
    '당신은 최고 수준의 AI 산출물 검토 전문가입니다. '
    'Claude가 생성한 산출물을 비판적으로 검토하고, '
    '품질·정확성·완성도·실용성을 엄격하게 평가하세요.\n\n'
    '다음 형식으로 반드시 응답하세요:\n'
    'SCORE: [0-100 정수]\n'
    'FEEDBACK: [전체 평가 (3-5문장)]\n'
    'IMPROVEMENTS:\n'
    '- [개선 제안 1]\n'
    '- [개선 제안 2]\n'
    '- [개선 제안 3]\n'
)


def _get_today_count() -> int:
    today = date.today().isoformat()
    if not _review_count_file.exists():
        return 0
    try:
        data = json.loads(_review_count_file.read_text('utf-8'))
        return int(data.get(today, 0))
    except Exception:
        return 0


def _bump_today_count() -> None:
    today = date.today().isoformat()
    data: dict[str, int] = {}
    if _review_count_file.exists():
        try:
            data = json.loads(_review_count_file.read_text('utf-8'))
        except Exception:
            data = {}
    data[today] = int(data.get(today, 0)) + 1
    # 30일 초과 항목 정리
    try:
        from datetime import timedelta, datetime as _dt
        cutoff = (_dt.fromisoformat(today) - timedelta(days=30)).date().isoformat()
        data = {k: v for k, v in data.items() if k >= cutoff}
    except Exception:
        pass
    _review_count_file.parent.mkdir(parents=True, exist_ok=True)
    _review_count_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8',
    )


def _pick_artifact(artifacts: dict[str, str]) -> tuple[str, str]:
    """리뷰 대상 산출물 선택 — 우선순위 키 순회, 없으면 최장 텍스트."""
    for k in _REVIEW_ARTIFACT_KEYS:
        v = artifacts.get(k)
        if v and len(str(v)) >= 200:
            return k, str(v)
    # fallback: 가장 긴 텍스트 artifact
    best = ('', '')
    for k, v in artifacts.items():
        s = str(v or '')
        if len(s) > len(best[1]):
            best = (k, s)
    return best


def _detect_primary_model(artifacts: dict[str, str]) -> str:
    """Job 주 모델 추정. artifacts에는 모델 정보 없음 → step 이력에서 추론.

    단순화: 반환값 'claude' 또는 'gemini'. 기본은 'claude'.
    """
    return 'claude'


def _opus_has_room() -> bool:
    try:
        from runners.cost_tracker import get_today_stats
        from runners.model_router import _DEEP_TIER_DAILY_LIMIT
        stats = get_today_stats()
        opus_calls = sum(
            m.get('calls', 0) for m in stats.get('by_model', [])
            if 'opus' in (m.get('model') or '').lower()
        )
        return opus_calls + 2 <= _DEEP_TIER_DAILY_LIMIT
    except Exception:
        return False


def _parse_review(raw: str) -> dict[str, Any]:
    """SCORE / FEEDBACK / IMPROVEMENTS 블록 파싱."""
    score = 0
    m = re.search(r'SCORE:\s*(\d{1,3})', raw)
    if m:
        try:
            score = max(0, min(100, int(m.group(1))))
        except Exception:
            score = 0
    fb_m = re.search(r'FEEDBACK:\s*(.+?)(?=\n\s*IMPROVEMENTS:|\Z)', raw, re.S)
    feedback = (fb_m.group(1).strip() if fb_m else '')[:1200]
    imp_m = re.search(r'IMPROVEMENTS:\s*(.+)$', raw, re.S)
    improvements: list[str] = []
    if imp_m:
        for line in imp_m.group(1).splitlines():
            line = line.strip().lstrip('-').strip()
            if line:
                improvements.append(line[:300])
    return {'score': score, 'feedback': feedback, 'improvements': improvements[:5]}


async def cross_review_job(
    job: 'JobRun', artifacts: dict[str, str],
) -> dict[str, Any] | None:
    """Job 완료 직후 교차 리뷰 수행. 실패/한도초과/짧은 산출물 → None.

    반환 dict 키: reviewer, score, feedback, improvements, artifact_key, model
    """
    if _get_today_count() >= DAILY_LIMIT:
        logger.debug('[cross_review] 일일 한도 도달(%d), skip', DAILY_LIMIT)
        return None

    key, body = _pick_artifact(artifacts)
    if not body or len(body) < 200:
        return None

    primary = _detect_primary_model(artifacts)

    # reviewer 결정
    if primary == 'claude':
        reviewer = 'gemini'
        tier = 'research'
        system = _GEMINI_SYSTEM
    else:
        if not _opus_has_room():
            return None
        reviewer = 'opus'
        tier = 'deep'
        system = _OPUS_SYSTEM

    try:
        from runners import model_router
        prompt = (
            f'[Job 제목]\n{job.title}\n\n'
            f'[검토 대상 산출물 key={key}]\n{body[:6000]}\n\n'
            '지정된 형식(SCORE/FEEDBACK/IMPROVEMENTS)으로만 응답하세요.'
        )
        raw, model_used = await model_router.run(
            tier=tier, prompt=prompt, system=system,
            agent_id=f'cross_review:{job.id}', timeout=60.0,
        )
    except Exception as e:
        logger.debug('[cross_review] LLM 호출 실패: %s', e)
        return None

    parsed = _parse_review(raw)
    _bump_today_count()
    return {
        'reviewer': reviewer,
        'score': parsed['score'],
        'feedback': parsed['feedback'],
        'improvements': parsed['improvements'],
        'artifact_key': key,
        'model': model_used,
    }


def format_cross_review_markdown(review: dict[str, Any]) -> str:
    """리뷰 결과를 cross_review artifact용 Markdown으로 포맷."""
    score = review.get('score', 0)
    reviewer = review.get('reviewer', '')
    badge = '🟢' if score >= 80 else '🟡' if score >= 60 else '🔴'
    lines = [
        f'# 교차 리뷰 ({reviewer})',
        '',
        f'**점수**: {badge} {score} / 100',
        f'**검토 대상**: `{review.get("artifact_key", "")}`',
        f'**모델**: `{review.get("model", "")}`',
        '',
        '## 총평',
        review.get('feedback', '') or '(평가 없음)',
        '',
        '## 개선 제안',
    ]
    for imp in review.get('improvements') or []:
        lines.append(f'- {imp}')
    if not review.get('improvements'):
        lines.append('- (제안 없음)')
    return '\n'.join(lines)
