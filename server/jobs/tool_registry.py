"""Tool Registry — Job step에서 사용 가능한 도구 목록과 실행기를 관리한다.

새 도구 추가: tools/ 디렉토리에 <tool_id>.py 파일을 만들거나
              이 파일의 _BUILTIN_TOOLS에 직접 등록한다.

사용법 (YAML spec):
  tools:
    - web_search
    - url_fetch
    - read_file
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).parent / 'tools'


@dataclass
class ToolSpec:
    id: str
    name: str
    description: str
    category: str = 'general'      # general | research | file | code
    is_async: bool = False
    enabled: bool = True
    params: list[str] = field(default_factory=list)  # context key들이 파라미터


# ── 내장 도구 목록 ─────────────────────────────────────────────────────────────

_BUILTIN_TOOLS: dict[str, ToolSpec] = {
    'web_search': ToolSpec(
        id='web_search',
        name='웹 검색',
        description='DuckDuckGo 또는 설정된 검색 엔진으로 웹 검색을 수행한다.',
        category='research',
        params=['topic', 'plan'],
    ),
    'url_fetch': ToolSpec(
        id='url_fetch',
        name='URL 페이지 가져오기',
        description='지정된 URL의 웹 페이지 내용을 가져온다.',
        category='research',
        params=['url'],
    ),
    'read_file': ToolSpec(
        id='read_file',
        name='파일 읽기',
        description='context의 file_path 키에 지정된 파일을 읽는다.',
        category='file',
        params=['file_path'],
    ),
    'list_files': ToolSpec(
        id='list_files',
        name='파일 목록',
        description='context의 dir_path 키에 지정된 디렉토리의 파일 목록을 가져온다.',
        category='file',
        params=['dir_path'],
    ),
    'run_shell': ToolSpec(
        id='run_shell',
        name='셸 명령 실행',
        description='context의 command 키에 지정된 명령을 실행한다. 주의: 보안 검토 필요.',
        category='code',
        enabled=False,  # 기본 비활성화
        params=['command'],
    ),
}


def list_tools() -> list[dict[str, Any]]:
    """등록된 모든 도구 목록 반환."""
    tools = list(_BUILTIN_TOOLS.values())
    # tools/ 디렉토리의 플러그인 도구 로드
    if _TOOLS_DIR.exists():
        for f in sorted(_TOOLS_DIR.glob('*.py')):
            if f.stem.startswith('_'):
                continue
            try:
                mod = importlib.import_module(f'jobs.tools.{f.stem}')
                if hasattr(mod, 'TOOL_SPEC') and isinstance(mod.TOOL_SPEC, ToolSpec):
                    tools.append(mod.TOOL_SPEC)
            except Exception:
                logger.debug('플러그인 도구 로드 실패: %s', f.stem)
    return [
        {
            'id': t.id,
            'name': t.name,
            'description': t.description,
            'category': t.category,
            'enabled': t.enabled,
            'is_async': t.is_async,
            'params': t.params,
        }
        for t in tools
    ]


def execute_tool(tool_id: str, context: dict[str, str]) -> str:
    """동기 도구 실행 — runner의 _execute_tool 대체 가능."""
    # 내장 도구
    if tool_id == 'web_search':
        return _web_search(context)
    if tool_id == 'url_fetch':
        return _url_fetch(context)
    if tool_id == 'read_file':
        return _read_file(context)
    if tool_id == 'list_files':
        return _list_files(context)
    if tool_id == 'run_shell':
        spec = _BUILTIN_TOOLS.get('run_shell')
        if spec and not spec.enabled:
            return '[run_shell 비활성화됨]'
        return _run_shell(context)

    # 플러그인 도구
    if _TOOLS_DIR.exists():
        plugin_path = _TOOLS_DIR / f'{tool_id}.py'
        if plugin_path.exists():
            try:
                mod = importlib.import_module(f'jobs.tools.{tool_id}')
                if hasattr(mod, 'execute'):
                    return mod.execute(context)
            except Exception as e:
                logger.warning('플러그인 도구 실행 실패: %s — %s', tool_id, e)
                return f'[{tool_id} 실행 실패: {e}]'

    logger.warning('알 수 없는 도구: %s', tool_id)
    return ''


# ── 내장 도구 구현 ─────────────────────────────────────────────────────────────

def _web_search(context: dict[str, str]) -> str:
    from harness.file_reader import web_search
    import json as _json
    import re

    plan_text = context.get('plan', '')
    queries: list[str] = []
    try:
        m = re.search(r'\{[\s\S]*\}', plan_text)
        if m:
            plan_data = _json.loads(m.group())
            queries = plan_data.get('queries', [])
    except Exception:
        pass
    if not queries:
        queries = [context.get('topic', context.get('project', ''))]

    parts = []
    for q in queries[:3]:
        if q:
            parts.append(web_search(q, max_results=5))
    return '\n\n'.join(parts)


def _url_fetch(context: dict[str, str]) -> str:
    from harness.file_reader import _fetch_web_page
    url = context.get('url', '')
    if url:
        return _fetch_web_page(url)
    return ''


def _read_file(context: dict[str, str]) -> str:
    file_path = context.get('file_path', '')
    if not file_path:
        return ''
    try:
        p = Path(file_path)
        if not p.exists():
            return f'[파일 없음: {file_path}]'
        content = p.read_text(encoding='utf-8')
        # 너무 크면 앞부분만
        if len(content) > 20000:
            content = content[:20000] + f'\n\n[이후 {len(content) - 20000}자 생략]'
        return content
    except Exception as e:
        return f'[파일 읽기 실패: {e}]'


def _list_files(context: dict[str, str]) -> str:
    dir_path = context.get('dir_path', '.')
    try:
        p = Path(dir_path)
        if not p.is_dir():
            return f'[디렉토리 없음: {dir_path}]'
        files = [str(f.relative_to(p)) for f in sorted(p.rglob('*')) if f.is_file()][:100]
        return '\n'.join(files)
    except Exception as e:
        return f'[목록 실패: {e}]'


def _run_shell(context: dict[str, str]) -> str:
    import subprocess
    command = context.get('command', '')
    if not command:
        return ''
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        return output[:5000]
    except subprocess.TimeoutExpired:
        return '[명령 타임아웃 (30초)]'
    except Exception as e:
        return f'[명령 실행 실패: {e}]'
