# 파일 읽기 하네스 — PDF, DOCX, 텍스트 파일을 읽어서 텍스트로 반환
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


def resolve_references(instruction: str) -> str:
  '''지시에서 경로를 찾아 파일 내용을 읽어온다.

  Returns:
    읽어온 파일 내용 텍스트. 경로가 없으면 빈 문자열.
  '''
  paths = extract_paths(instruction)
  if not paths:
    return ''

  contents = []
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
