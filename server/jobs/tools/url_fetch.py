"""url_fetch — URL 페이지 가져오기.

context.url 우선. 없으면 topic/scope/notes/project 등 텍스트 필드에서
URL 패턴(절대/상대 도메인 모두)을 자동 추출해 fetch.
"""
from __future__ import annotations

import re

from jobs.tool_registry import ToolSpec

TOOL_SPEC = ToolSpec(
    id='url_fetch',
    name='URL 가져오기',
    description='context.url을 HTTP로 가져와 텍스트로 반환. url이 비어있으면 다른 텍스트 필드에서 URL을 자동 추출한다.',
    category='research',
    params=['url'],
)

# 절대 URL 먼저 매치, 없으면 도메인 형태 (예: jdcenter.com) 추출
_ABSOLUTE = re.compile(r'https?://[^\s<>"\'()]+', re.IGNORECASE)
_DOMAIN = re.compile(
    r'\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
    r'(?:com|net|org|io|co|kr|ai|dev|app|xyz|tech|site|page|me|info|biz|cloud|store|shop))'
    r'(?:/[^\s<>"\'()]*)?', re.IGNORECASE,
)


def _extract_url(context: dict[str, str]) -> str:
    url = (context.get('url') or '').strip()
    if url:
        return url
    # 우선 탐색 필드 (짧고 명시적일 가능성 높은 순)
    priority = ('url', 'site', 'page', 'link', 'topic', 'project', 'scope', 'notes', 'brief')
    seen: list[str] = []
    for k in priority:
        v = context.get(k)
        if isinstance(v, str) and v.strip():
            seen.append(v)
    # 남은 필드도 fallback
    for k, v in context.items():
        if k.startswith('_') or k in priority:
            continue
        if isinstance(v, str) and v.strip():
            seen.append(v)
    for text in seen:
        m = _ABSOLUTE.search(text)
        if m:
            return m.group(0).rstrip(').,;:!?')
        m = _DOMAIN.search(text)
        if m:
            return m.group(0).rstrip(').,;:!?')
    return ''


def _follow_client_redirect(url: str, max_hops: int = 2) -> tuple[str, str]:
    """짧은 응답이면 raw HTML에서 JS/meta 리다이렉트를 추적해 최종 URL+본문 반환."""
    import urllib.request
    from urllib.parse import urljoin
    from harness.file_reader import _fetch_web_page

    current = url
    for _ in range(max_hops):
        try:
            req = urllib.request.Request(current, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; AI-Office/1.0)',
                'Accept': 'text/html,application/xhtml+xml',
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
        except Exception:
            return current, ''

        # 본문 길이 충분하면 그대로 반환
        if len(raw) > 800 and '<body' in raw.lower():
            body = _fetch_web_page(current)
            if body:
                return current, body

        # JS 리다이렉트
        m = re.search(
            r'''location\.(?:href|replace)\s*=\s*['"]([^'"]+)''',
            raw,
        )
        # meta refresh
        if not m:
            m = re.search(
                r'''<meta\s+http-equiv=["']refresh["']\s+content=["']\d+\s*;\s*url=([^"']+)''',
                raw, re.IGNORECASE,
            )
        if not m:
            # 더이상 리다이렉트 없음 — 현재 본문(짧더라도) 반환
            body = _fetch_web_page(current)
            return current, body

        target = m.group(1).strip()
        if target.startswith('/') or not target.startswith(('http://', 'https://')):
            target = urljoin(current, target)
        current = target

    # max hops 도달
    body = _fetch_web_page(current)
    return current, body


def execute(context: dict[str, str]) -> str:
    url = _extract_url(context)
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        from harness.file_reader import _fetch_web_page
        body = _fetch_web_page(url)
        # 본문이 너무 짧으면 JS/meta 리다이렉트 추적 시도
        if len(body) < 300:
            final_url, redirected_body = _follow_client_redirect(url)
            if redirected_body and final_url != url:
                return f'[fetched (redirected): {final_url} ← {url}]\n{redirected_body}'
            if redirected_body:
                body = redirected_body
                url = final_url
        if body:
            return f'[fetched: {url}]\n{body}'
        return f'[url_fetch: {url} — 응답 없음 (JS 렌더링 SPA일 수 있음)]'
    except Exception as e:
        return f'[url_fetch 실패: {url} — {e!s:.160}]'
