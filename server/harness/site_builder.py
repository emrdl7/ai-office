# 멀티페이지 사이트 빌더 — IA 구조 기반 멀티페이지 HTML 사이트 생성
from __future__ import annotations
import re
from pathlib import Path

from runners.claude_runner import run_claude_isolated


def extract_pages_from_ia(ia_content: str) -> list[dict[str, str]]:
  '''IA 설계 산출물에서 페이지 목록을 추출한다.

  Returns:
    [{'slug': 'index', 'title': '메인', 'description': '...'}, ...]
  '''
  pages = [{'slug': 'index', 'title': '메인', 'description': '메인 페이지'}]

  # 마크다운에서 GNB/메뉴 구조 추출
  # "- 기관소개" / "1. 기관소개" / "### 기관소개" 패턴
  menu_patterns = [
    r'[-*]\s+(.+?)(?:\s*[→:]\s*(.+))?$',
    r'\d+\.\s+(.+?)(?:\s*[→:]\s*(.+))?$',
  ]

  for line in ia_content.split('\n'):
    stripped = line.strip()
    # GNB, 메뉴, 네비게이션 섹션 내의 항목만
    for pattern in menu_patterns:
      match = re.match(pattern, stripped)
      if match:
        title = match.group(1).strip().rstrip('/')
        desc = match.group(2).strip() if match.group(2) else title
        # 이미 있는 건 스킵, 서브메뉴(들여쓰기)는 제외
        if not line.startswith('  ') and title and len(title) < 20:
          slug = _to_slug(title)
          if slug and slug != 'index' and not any(p['slug'] == slug for p in pages):
            pages.append({'slug': slug, 'title': title, 'description': desc})

  # 최소 2페이지, 최대 8페이지
  return pages[:8] if len(pages) > 1 else pages


def _to_slug(title: str) -> str:
  '''한국어 제목을 URL-safe slug로 변환.'''
  slug_map = {
    '기관소개': 'about', '소개': 'about', '회사소개': 'about',
    '사업안내': 'services', '서비스': 'services', '사업': 'services',
    '공지사항': 'notice', '뉴스': 'news', '소식': 'news',
    '문의': 'contact', '연락처': 'contact', '오시는길': 'contact',
    '갤러리': 'gallery', '자료실': 'resources', '게시판': 'board',
    '채용': 'careers', '인재채용': 'careers',
  }
  for kr, en in slug_map.items():
    if kr in title:
      return en
  # 매핑 없으면 영문 소문자 변환 시도
  ascii_only = re.sub(r'[^a-zA-Z0-9]', '', title.lower())
  return ascii_only if ascii_only else ''


async def build_multipage_site(
  ia_content: str,
  design_specs: str,
  stitch_html: str | None,
  workspace_dir: Path,
  project_brief: str = '',
) -> dict:
  '''IA 구조 기반 멀티페이지 사이트를 생성한다.

  Returns:
    {'pages': ['site/index.html', ...], 'assets': ['site/css/style.css', ...]}
  '''
  pages = extract_pages_from_ia(ia_content)
  site_dir = workspace_dir / 'site'
  site_dir.mkdir(parents=True, exist_ok=True)
  (site_dir / 'css').mkdir(exist_ok=True)
  (site_dir / 'js').mkdir(exist_ok=True)

  # 공통 CSS 생성
  css_content = await _generate_common_css(design_specs)
  css_path = site_dir / 'css' / 'style.css'
  css_path.write_text(css_content, encoding='utf-8')

  # 공통 JS 생성
  js_content = _generate_common_js(pages)
  js_path = site_dir / 'js' / 'main.js'
  js_path.write_text(js_content, encoding='utf-8')

  # 네비게이션 HTML
  nav_html = _build_nav(pages)

  # 각 페이지 생성
  page_paths = []
  for page in pages:
    html = await _generate_page(page, nav_html, design_specs, stitch_html, project_brief)
    page_file = site_dir / f'{page["slug"]}.html'
    page_file.write_text(html, encoding='utf-8')
    page_paths.append(str(page_file.relative_to(workspace_dir)))

  return {
    'pages': page_paths,
    'assets': [
      str(css_path.relative_to(workspace_dir)),
      str(js_path.relative_to(workspace_dir)),
    ],
  }


async def _generate_common_css(design_specs: str) -> str:
  '''디자인 스펙에서 공통 CSS를 생성한다.'''
  prompt = (
    f'아래 디자인 시스템 스펙을 기반으로 CSS 파일을 작성하세요.\n\n'
    f'{design_specs[:4000]}\n\n'
    f'요구사항:\n'
    f'- CSS 변수(:root)로 컬러, 타이포, 간격 정의\n'
    f'- 리셋 CSS 포함\n'
    f'- 반응형 브레이크포인트 (768px, 1024px)\n'
    f'- 헤더, 네비게이션, 메인, 푸터 기본 레이아웃\n'
    f'- CSS 코드만 출력. 설명 없이.'
  )
  try:
    result = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=60.0)
    # 코드블록 제거
    if '```' in result:
      match = re.search(r'```(?:css)?\s*\n([\s\S]*?)\n```', result)
      return match.group(1) if match else result
    return result
  except Exception:
    return ':root { --primary: #2196F3; --text: #333; }\n* { margin: 0; padding: 0; box-sizing: border-box; }\nbody { font-family: sans-serif; }'


def _generate_common_js(pages: list[dict]) -> str:
  '''공통 JS — 모바일 메뉴 토글, 현재 페이지 하이라이트.'''
  return '''// 모바일 메뉴 토글
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.nav-menu');
  if (toggle && nav) {
    toggle.addEventListener('click', () => nav.classList.toggle('active'));
  }
  // 현재 페이지 하이라이트
  const current = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-menu a').forEach(a => {
    if (a.getAttribute('href') === current) a.classList.add('active');
  });
});
'''


def _build_nav(pages: list[dict]) -> str:
  '''네비게이션 HTML을 생성한다.'''
  items = []
  for p in pages:
    href = 'index.html' if p['slug'] == 'index' else f'{p["slug"]}.html'
    items.append(f'      <li><a href="{href}">{p["title"]}</a></li>')
  return (
    '  <nav>\n'
    '    <button class="nav-toggle" aria-label="메뉴">☰</button>\n'
    '    <ul class="nav-menu">\n'
    + '\n'.join(items) + '\n'
    '    </ul>\n'
    '  </nav>'
  )


async def _generate_page(
  page: dict, nav_html: str, design_specs: str,
  stitch_html: str | None, project_brief: str,
) -> str:
  '''개별 페이지 HTML을 생성한다.'''
  stitch_ref = ''
  if stitch_html and page['slug'] == 'index':
    stitch_ref = f'\n[Stitch 시안 참고]\n{stitch_html[:3000]}\n'

  prompt = (
    f'"{page["title"]}" 페이지의 HTML을 작성하세요.\n\n'
    f'[페이지 정보]\n- slug: {page["slug"]}\n- 설명: {page["description"]}\n\n'
    f'[프로젝트]\n{project_brief[:500]}\n\n'
    f'[디자인 스펙]\n{design_specs[:2000]}\n'
    f'{stitch_ref}\n'
    f'요구사항:\n'
    f'- 완전한 HTML5 문서 (<!DOCTYPE html>)\n'
    f'- <link rel="stylesheet" href="css/style.css">\n'
    f'- <script src="js/main.js" defer></script>\n'
    f'- 시맨틱 마크업 (header, main, footer)\n'
    f'- 아래 네비게이션을 header 안에 포함:\n{nav_html}\n'
    f'- HTML 코드만 출력. 설명 없이.'
  )
  try:
    result = await run_claude_isolated(prompt, timeout=120.0)
    if '```' in result:
      match = re.search(r'```(?:html)?\s*\n([\s\S]*?)\n```', result)
      return match.group(1) if match else result
    return result
  except Exception:
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{page["title"]}</title><link rel="stylesheet" href="css/style.css"></head><body><header>{nav_html}</header><main><h1>{page["title"]}</h1></main><footer></footer><script src="js/main.js" defer></script></body></html>'
