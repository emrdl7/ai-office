"""HTML 정적 검증 + 스크린샷 도구.

- validate_html: Python html.parser 기반 구조 검증 + Node axe-core(html_validator.mjs) 선택 호출
- screenshot_html: Node puppeteer(screenshot.mjs) 호출 — Node 환경 필수
두 함수 모두 Node 환경 없으면 error를 담은 dict로 fallback.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HARNESS_DIR = Path(__file__).parent
_VALIDATOR_JS = _HARNESS_DIR / 'html_validator.mjs'
_SCREENSHOT_JS = _HARNESS_DIR / 'screenshot.mjs'


class _StructureChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_doctype = False
        self.has_lang = False
        self.has_viewport = False
        self.has_title = False
        self.has_h1 = False
        self.empty_alt_count = 0
        self._in_title = False

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith('doctype'):
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or '') for k, v in attrs}
        if tag == 'html' and ad.get('lang'):
            self.has_lang = True
        elif tag == 'meta':
            if ad.get('name', '').lower() == 'viewport':
                self.has_viewport = True
        elif tag == 'title':
            self._in_title = True
        elif tag == 'h1':
            self.has_h1 = True
        elif tag == 'img':
            if 'alt' not in ad or ad.get('alt') is None:
                # alt 속성 누락 — empty alt는 장식 이미지로 OK
                self.empty_alt_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.has_title = True


def _check_structure(html: str) -> dict[str, Any]:
    checker = _StructureChecker()
    try:
        checker.feed(html)
    except Exception as e:
        logger.debug('[html_tools] 구조 파서 예외: %s', e)
    return {
        'has_doctype': checker.has_doctype,
        'has_lang': checker.has_lang,
        'has_viewport': checker.has_viewport,
        'has_title': checker.has_title,
        'has_h1': checker.has_h1,
        'empty_alt_count': checker.empty_alt_count,
    }


def _structure_score(structure: dict[str, Any]) -> int:
    """구조 체크 5개 + alt 이슈 감점으로 0-100."""
    base = sum(1 for k in (
        'has_doctype', 'has_lang', 'has_viewport', 'has_title', 'has_h1',
    ) if structure.get(k)) * 15  # 최대 75
    penalty = min(structure.get('empty_alt_count', 0) * 5, 15)
    return max(0, min(100, base + 25 - penalty))  # 기본 25 + base(75) - penalty


async def _run_node(script: Path, stdin_text: str, timeout: float = 60.0) -> dict[str, Any]:
    """Node 스크립트 실행. stdin으로 html 전달, stdout에서 JSON 파싱."""
    node = shutil.which('node')
    if not node:
        return {'error': 'Node.js가 설치돼 있지 않습니다 (node 명령 없음)'}
    if not script.exists():
        return {'error': f'스크립트 없음: {script.name}'}
    try:
        proc = await asyncio.create_subprocess_exec(
            node, str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_text.encode('utf-8')), timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {'error': f'{script.name} 타임아웃 ({timeout}s)'}
    except Exception as e:
        return {'error': f'{script.name} 실행 실패: {e}'}
    if proc.returncode != 0:
        err_msg = stderr.decode('utf-8', errors='ignore')[:400]
        return {'error': f'{script.name} 종료 {proc.returncode}: {err_msg}'}
    try:
        return json.loads(stdout.decode('utf-8', errors='ignore') or '{}')
    except Exception as e:
        return {'error': f'{script.name} 출력 JSON 파싱 실패: {e}'}


async def validate_html(html: str) -> dict[str, Any]:
    """HTML 구조 + (선택) axe-core 접근성 검증.

    반환: {structure, a11y, score, error?}
    """
    structure = _check_structure(html)
    base_score = _structure_score(structure)

    a11y: dict[str, Any] | None = None
    node_err = None
    if _VALIDATOR_JS.exists() and shutil.which('node'):
        result = await _run_node(_VALIDATOR_JS, html, timeout=45.0)
        if 'error' in result:
            node_err = result['error']
        else:
            a11y = result.get('a11y') or result

    # a11y 감점
    score = base_score
    if a11y and isinstance(a11y, dict):
        vc = int(a11y.get('violation_count', 0) or 0)
        score = max(0, score - min(vc * 5, 40))

    out: dict[str, Any] = {
        'structure': structure,
        'a11y': a11y,
        'score': score,
    }
    if node_err and not a11y:
        out['error'] = node_err
    return out


async def screenshot_html(
    html: str, output_dir: str, job_id: str,
) -> dict[str, Any]:
    """3-viewport(mobile/tablet/desktop) 스크린샷 촬영. Node + puppeteer 필요.

    반환: {screenshots: {mobile, tablet, desktop: path}, error?}
    """
    os.makedirs(output_dir, exist_ok=True)
    payload = json.dumps({
        'html': html,
        'output_dir': output_dir,
        'job_id': job_id,
        'viewports': {
            'mobile':  {'width': 375,  'height': 812},
            'tablet':  {'width': 768,  'height': 1024},
            'desktop': {'width': 1280, 'height': 900},
        },
    }, ensure_ascii=False)
    result = await _run_node(_SCREENSHOT_JS, payload, timeout=90.0)
    if 'error' in result:
        return {'screenshots': None, 'error': result['error']}
    return {'screenshots': result.get('screenshots') or {}, 'error': result.get('error')}
