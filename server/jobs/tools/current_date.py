"""current_date — 오늘 날짜 반환."""
from __future__ import annotations

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='current_date',
    name='현재 날짜',
    description='오늘 날짜와 현재 시각을 반환한다. 시의성 있는 리서치/기획 step에 추가하면 좋다.',
    category='general',
    params=[],
)


def execute(context: dict[str, str]) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return f'오늘 날짜: {now.strftime("%Y년 %m월 %d일")} ({now.strftime("%A")}, UTC 기준)'
