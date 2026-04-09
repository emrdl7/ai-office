# 파일 읽기 하네스 — PDF, DOCX, 텍스트 파일을 읽어서 텍스트로 반환
from __future__ import annotations
import re
from pathlib import Path


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
    pass

  return '\n\n'.join(parts) if parts else ''


def resolve_references(instruction: str) -> str:
  '''지시에서 경로/URL을 찾아 내용을 읽어온다.

  Returns:
    읽어온 파일/URL 내용 텍스트. 경로가 없으면 빈 문자열.
  '''
  contents = []

  # GitHub URL 감지 및 내용 가져오기
  github_pattern = r'https?://github\.com/([^/\s]+)/([^/\s#?]+)'
  github_matches = re.findall(github_pattern, instruction)
  for owner, repo in github_matches:
    repo = repo.rstrip('/')
    content = _fetch_github_repo(owner, repo)
    if content:
      contents.append(f'[GitHub: {owner}/{repo}]\n{content}')

  # 로컬 파일 경로 처리
  paths = extract_paths(instruction)
  for path in paths:
    p = Path(path)
    if p.is_dir():
      content = read_folder(path)
      contents.append(f'[참조 폴더: {path}]\n{content}')
    elif p.is_file():
      content = read_file(path)
      if content:
        contents.append(f'[참조 파일: {p.name}]\n{content}')
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
    for page in doc:
      page_text = page.get_text()
      text_parts.append(page_text)
      total += len(page_text)
      if total >= max_chars:
        break
    doc.close()
    return '\n'.join(text_parts)[:max_chars]
  except Exception as e:
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
    return f'(DOCX 읽기 실패: {e})'


def _read_text(path: Path, max_chars: int) -> str | None:
  '''텍스트 파일을 읽는다.'''
  try:
    return path.read_text(encoding='utf-8', errors='replace')[:max_chars]
  except Exception as e:
    return f'(파일 읽기 실패: {e})'
