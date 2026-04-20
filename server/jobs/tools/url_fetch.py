"""url_fetch — URL 페이지 가져오기."""
from __future__ import annotations

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='url_fetch',
    name='URL 가져오기',
    description='context.url을 HTTP로 가져와 텍스트로 반환한다.',
    category='research',
    params=['url'],
)


def execute(context: dict[str, str]) -> str:
    from harness.file_reader import _fetch_web_page
    url = context.get('url', '')
    if url:
        return _fetch_web_page(url)
    return ''
