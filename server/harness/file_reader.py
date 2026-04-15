# 파일 읽기 하네스 — PDF, DOCX, 텍스트 파일을 읽어서 텍스트로 반환
from __future__ import annotations
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# 경로 패턴 매칭 (~/Downloads, /Users/..., ./folder 등)
PATH_PATTERNS = [
  r'~/[^\s,\'"]+',
  r'/Users/[^\s,\'"]+',
  r'/tmp/[^\s,\'"]+',
  r'\./[^\s,\'"]+',
]


def extract_paths(text: str) -> list[str]:
  '''텍스트에서 파일/폴더 경로를 추출한다.'''
  paths = []
  for pattern in PATH_PATTERNS:
    matches = re.findall(pattern, text)
    paths.extend(matches)
  # ~ 확장
  return [str(Path(p).expanduser()) for p in paths]


def read_file(path: str, max_chars: int = 8000) -> str | None:
  '''파일을 읽어서 텍스트로 반환한다. PDF/DOCX/텍스트 지원.'''
  p = Path(path)
  if not p.exists():
    return None

  suffix = p.suffix.lower()

  if suffix == '.pdf':
    return _read_pdf(p, max_chars)
  elif suffix in ('.docx', '.doc'):
    return _read_docx(p, max_chars)
  elif suffix in ('.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.html', '.css', '.js', '.py', '.ts', '.tsx'):
    return _read_text(p, max_chars)
  else:
    return _read_text(p, max_chars)  # 기본은 텍스트로 시도


def read_folder(path: str, max_chars: int = 8000) -> str:
  '''폴더 내 모든 지원 파일을 읽어서 합친다.'''
  p = Path(path)
  if not p.is_dir():
    return f'(폴더를 찾을 수 없음: {path})'

  results = []
  total = 0
  for f in sorted(p.iterdir()):
    if f.is_file() and not f.name.startswith('.'):
      content = read_file(str(f), max_chars=max_chars - total)
      if content:
        results.append(f'=== {f.name} ===\n{content}')
        total += len(content)
        if total >= max_chars:
          break

  return '\n\n'.join(results) if results else f'(폴더에 읽을 수 있는 파일 없음: {path})'


def web_search(query: str, max_results: int = 5) -> str:
  '''DuckDuckGo로 웹 검색하여 결과를 텍스트로 반환한다 (API 키 불필요).'''
  import urllib.request, urllib.parse

  try:
    url = f'https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}'
    req = urllib.request.Request(url, headers={
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
      html = resp.read().decode('utf-8', errors='replace')

    # 결과 추출: 제목 + URL + 스니펫
    results = re.findall(
      r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
      r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
      html, re.DOTALL,
    )

    if not results:
      return ''

    lines = []
    for i, (raw_url, raw_title, raw_snippet) in enumerate(results[:max_results]):
      title = re.sub(r'<[^>]+>', '', raw_title).strip()
      snippet = re.sub(r'<[^>]+>', '', raw_snippet).strip()
      # DuckDuckGo redirect URL에서 실제 URL 추출
      actual_url = raw_url
      url_match = re.search(r'uddg=([^&]+)', raw_url)
      if url_match:
        actual_url = urllib.parse.unquote(url_match.group(1))
      lines.append(f'{i+1}. {title}\n   {actual_url}\n   {snippet}')

    return '\n\n'.join(lines)
  except Exception:
    logger.debug("웹 검색 실패: query=%s", query, exc_info=True)
    return ''


def _fetch_web_page(url: str, max_chars: int = 8000) -> str:
  '''웹 페이지의 텍스트 콘텐츠를 가져온다 (HTML → 텍스트).'''
  import urllib.request

  try:
    req = urllib.request.Request(url, headers={
      'User-Agent': 'Mozilla/5.0 (compatible; AI-Office/1.0)',
      'Accept': 'text/html,application/xhtml+xml,text/plain',
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
      content_type = resp.headers.get('Content-Type', '')
      if 'image' in content_type or 'pdf' in content_type or 'octet-stream' in content_type:
        return ''
      raw = resp.read().decode('utf-8', errors='replace')

    # HTML 태그 제거 → 텍스트 추출
    if '<html' in raw.lower() or '<body' in raw.lower():
      # script/style 제거
      cleaned = re.sub(r'<(script|style)[^>]*>[\s\S]*?</\1>', '', raw, flags=re.IGNORECASE)
      # 태그 제거
      cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
      # 공백 정리
      cleaned = re.sub(r'\s+', ' ', cleaned).strip()
      return cleaned[:max_chars]
    return raw[:max_chars]
  except Exception:
    logger.debug("웹 페이지 가져오기 실패: url=%s", url, exc_info=True)
    return ''


def _fetch_github_repo(owner: str, repo: str) -> str:
  '''GitHub 저장소의 파일 구조 + README를 가져온다.'''
  import urllib.request, json as _json

  parts = []

  # 1) 파일 트리 (최상위)
  try:
    req = urllib.request.Request(
      f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1',
      headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'AI-Office'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
      tree = _json.loads(resp.read())
    files = [n['path'] for n in tree.get('tree', []) if n['type'] == 'blob']
    parts.append(f'[파일 구조 ({len(files)}개)]\n' + '\n'.join(files[:200]))
  except Exception:
    logger.debug("GitHub 파일 트리 가져오기 실패: %s/%s", owner, repo, exc_info=True)
    parts.append('[파일 구조 가져오기 실패]')

  # 2) README
  for readme_name in ('README.md', 'readme.md', 'README.rst', 'README'):
    try:
      req = urllib.request.Request(
        f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}',
        headers={'User-Agent': 'AI-Office'},
      )
      with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode('utf-8', errors='replace')
      if content.strip():
        parts.append(f'[README]\n{content[:8000]}')
        break
    except Exception:
      logger.debug("GitHub README 가져오기 실패: %s/%s/%s", owner, repo, readme_name, exc_info=True)
      continue

  # 3) package.json (있으면)
  try:
    req = urllib.request.Request(
      f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/package.json',
      headers={'User-Agent': 'AI-Office'},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
      content = resp.read().decode('utf-8', errors='replace')
    if content.strip():
      parts.append(f'[package.json]\n{content[:3000]}')
  except Exception:
    logger.debug("GitHub package.json 가져오기 실패: %s/%s", owner, repo, exc_info=True)

  return '\n\n'.join(parts) if parts else ''


def resolve_references(instruction: str) -> str:
  '''지시에서 경로/URL을 찾아 내용을 읽어온다.

  Returns:
    읽어온 파일/URL 내용 텍스트. 경로가 없으면 빈 문자열.
  '''
  contents = []

  # 검색 요청 감지: "~에 대해 검색해", "~을 검색해줘", "~ 찾아봐" 등
  search_patterns = [
    r'["\']?(.+?)["\']?\s*(?:에 대해|에대해|을|를)?\s*(?:검색|서치|search)해',
    r'(.+?)\s*(?:검색|서치|search)해\s*(?:줘|주세요|봐)?',
    r'(.+?)\s*(?:찾아|알아)\s*(?:봐|줘|주세요)',
  ]
  for sp in search_patterns:
    match = re.search(sp, instruction)
    if match:
      query = match.group(1).strip()
      if len(query) > 2:
        result = web_search(query)
        if result:
          contents.append(f'[웹 검색: {query}]\n{result}')
        break

  # URL 감지
  url_pattern = r'(https?://[^\s<\'"]+)'
  urls = re.findall(url_pattern, instruction)
  github_pattern = r'https?://github\.com/([^/\s]+)/([^/\s#?]+)'

  for url in urls:
    # GitHub 저장소 → 전용 API로 처리
    gh_match = re.match(github_pattern, url)
    if gh_match:
      owner, repo = gh_match.group(1), gh_match.group(2).rstrip('/')
      content = _fetch_github_repo(owner, repo)
      if content:
        contents.append(f'[GitHub: {owner}/{repo}]\n{content}')
      continue

    # 일반 웹 URL → 페이지 내용 가져오기
    content = _fetch_web_page(url)
    if content:
      contents.append(f'[웹: {url[:80]}]\n{content}')

  # 로컬 파일 경로 처리
  paths = extract_paths(instruction)
  for path in paths:
    p = Path(path)
    if p.is_dir():
      content = read_folder(path)
      contents.append(f'[참조 폴더: {path}]\n{content}')
    elif p.is_file():
      file_content = read_file(path)
      if file_content:
        contents.append(f'[참조 파일: {p.name}]\n{file_content}')
      else:
        contents.append(f'[참조 파일: {path} — 읽기 실패]')
    else:
      contents.append(f'[경로를 찾을 수 없음: {path}]')

  return '\n\n'.join(contents)


def _read_pdf(path: Path, max_chars: int) -> str | None:
  '''PDF 파일을 텍스트로 변환한다.'''
  try:
    import pymupdf
    doc = pymupdf.open(str(path))
    text_parts = []
    total = 0
    for page in doc:  # type: ignore[attr-defined]  # pymupdf.Document는 런타임에 iterable
      page_text = page.get_text()
      text_parts.append(page_text)
      total += len(page_text)
      if total >= max_chars:
        break
    doc.close()
    return '\n'.join(text_parts)[:max_chars]
  except Exception as e:
    logger.warning("PDF 읽기 실패: %s", path, exc_info=True)
    return f'(PDF 읽기 실패: {e})'


def _read_docx(path: Path, max_chars: int) -> str | None:
  '''DOCX 파일을 텍스트로 변환한다.'''
  try:
    from docx import Document
    doc = Document(str(path))
    text_parts = []
    total = 0
    for para in doc.paragraphs:
      text_parts.append(para.text)
      total += len(para.text)
      if total >= max_chars:
        break
    return '\n'.join(text_parts)[:max_chars]
  except Exception as e:
    logger.warning("DOCX 읽기 실패: %s", path, exc_info=True)
    return f'(DOCX 읽기 실패: {e})'


def _read_text(path: Path, max_chars: int) -> str | None:
  '''텍스트 파일을 읽는다.'''
  try:
    return path.read_text(encoding='utf-8', errors='replace')[:max_chars]
  except Exception as e:
    logger.warning("텍스트 파일 읽기 실패: %s", path, exc_info=True)
    return f'(파일 읽기 실패: {e})'
