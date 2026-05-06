"""web_search — 검색 쿼리를 생성해 웹 검색 결과를 반환."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from jobs.tool_registry import ToolSpec
from jobs.tools._common import resolve_token

TOOL_SPEC = ToolSpec(
    id='web_search',
    name='웹 검색',
    description='DuckDuckGo 또는 설정된 검색 엔진으로 웹 검색을 수행한다.',
    category='research',
    params=['topic', 'plan'],
)


def _queries_from_context(context: dict[str, str]) -> list[str]:
    plan_text = context.get('plan', '')
    queries: list[str] = []
    try:
        match = re.search(r'\{[\s\S]*\}', plan_text)
        if match:
            plan_data = json.loads(match.group())
            raw_queries = plan_data.get('queries', [])
            if isinstance(raw_queries, list):
                queries = [str(query) for query in raw_queries]
    except Exception:
        queries = []
    if not queries:
        queries = [context.get('topic', context.get('project', ''))]
    return [query for query in queries[:3] if query]


def _web_search_brave(queries: list[str], api_key: str) -> str:
    results: list[str] = []
    for query in queries:
        encoded = urllib.parse.quote_plus(query)
        req = urllib.request.Request(
            f'https://api.search.brave.com/res/v1/web/search?q={encoded}&count=5',
            headers={'Accept': 'application/json', 'X-Subscription-Token': api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            items = data.get('web', {}).get('results', [])
            parts = [f'## 검색: {query}']
            for item in items:
                title = item.get('title', '')
                url = item.get('url', '')
                desc = item.get('description', '')[:200]
                parts.append(f'- **{title}**\n  {url}\n  {desc}')
            results.append('\n'.join(parts))
        except Exception as exc:
            results.append(f'[Brave 검색 실패: {query} — {exc}]')
    return '\n\n'.join(results)


def execute(context: dict[str, str]) -> str:
    queries = _queries_from_context(context)
    if not queries:
        return '[web_search: query 없음]'

    brave_key = resolve_token('BRAVE_SEARCH_API_KEY')
    if brave_key:
        return _web_search_brave(queries, brave_key)

    from harness.file_reader import web_search

    return '\n\n'.join(web_search(query, max_results=5) for query in queries)
