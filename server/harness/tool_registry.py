# 에이전트 도구 레지스트리 — 역할별 사용 가능 도구 정의 + 실행 중앙 관리
from __future__ import annotations
import re
import time
from typing import Any

from harness.file_reader import web_search, _fetch_web_page, _fetch_github_repo

# 에이전트별 사용 가능 도구
AGENT_TOOLS: dict[str, list[str]] = {
  'planner':   ['web_search', 'url_fetch'],
  'designer':  ['web_search', 'url_fetch'],
  'developer': ['web_search', 'url_fetch'],
  'qa':        [],
}

# 도구 필요 판단 키워드
_SEARCH_KEYWORDS = (
  '벤치마킹', '경쟁사', '사례', '트렌드', '시장', '업계', '최신',
  '비교', '레퍼런스', '참고할', '찾아봐', '검색',
)


class ToolRegistry:
  '''에이전트 도구 실행기. rate limit 포함.'''

  def __init__(self, rate_limit: int = 10):
    self._rate_limit = rate_limit  # 분당 최대 호출
    self._call_log: list[float] = []

  def get_tools(self, agent_name: str) -> list[str]:
    return AGENT_TOOLS.get(agent_name, [])

  def _check_rate(self) -> bool:
    now = time.time()
    self._call_log = [t for t in self._call_log if now - t < 60]
    if len(self._call_log) >= self._rate_limit:
      return False
    self._call_log.append(now)
    return True

  async def execute(self, agent_name: str, tool_name: str, **params: Any) -> str:
    '''도구를 실행하고 결과를 반환한다.'''
    available = self.get_tools(agent_name)
    if tool_name not in available:
      return ''
    if not self._check_rate():
      return '[도구 호출 제한 초과]'

    if tool_name == 'web_search':
      query = params.get('query', '')
      return web_search(query) if query else ''

    if tool_name == 'url_fetch':
      url = params.get('url', '')
      if not url:
        return ''
      gh_match = re.match(r'https?://github\.com/([^/\s]+)/([^/\s#?]+)', url)
      if gh_match:
        return _fetch_github_repo(gh_match.group(1), gh_match.group(2).rstrip('/'))
      return _fetch_web_page(url)

    return ''


def analyze_tool_needs(prompt: str, agent_name: str) -> list[dict[str, str]]:
  '''프롬프트에서 도구 사용 필요성을 키워드 기반으로 판단한다 (LLM 호출 없음).

  Returns:
    [{'tool': 'web_search', 'query': '...'}, {'tool': 'url_fetch', 'url': '...'}]
  '''
  available = AGENT_TOOLS.get(agent_name, [])
  needs: list[dict[str, str]] = []

  # URL 감지 → url_fetch
  if 'url_fetch' in available:
    urls = re.findall(r'(https?://[^\s<\'"]+)', prompt)
    for url in urls[:3]:  # 최대 3개
      needs.append({'tool': 'url_fetch', 'url': url})

  # 검색 키워드 감지 → web_search
  if 'web_search' in available:
    for kw in _SEARCH_KEYWORDS:
      if kw in prompt:
        # 키워드 주변 문맥을 검색어로 사용
        # 프롬프트의 첫 200자에서 핵심 추출
        search_query = prompt[:200].replace('\n', ' ').strip()
        needs.append({'tool': 'web_search', 'query': search_query})
        break

  return needs
