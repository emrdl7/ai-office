"""Tool 플러그인 디렉토리.

각 도구는 <tool_id>.py 파일에 다음 두 가지를 노출한다:
  - TOOL_SPEC: ToolSpec  (ID, 이름, 설명, 카테고리 등)
  - execute(context: dict[str, str]) -> str  (실행 본체)

load_plugin_tools()로 전체 로드. tool_registry가 이 결과를 legacy _BUILTIN_TOOLS와 병합해 사용한다.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).parent


def load_plugin_tools() -> dict[str, tuple[Any, Callable[[dict[str, str]], str]]]:
    """tools/ 디렉토리의 모든 플러그인 도구를 로드.

    반환: {tool_id: (TOOL_SPEC, execute_fn)}
    """
    result: dict[str, tuple[Any, Callable[[dict[str, str]], str]]] = {}
    for f in sorted(_TOOLS_DIR.glob('*.py')):
        if f.stem.startswith('_'):
            continue
        try:
            mod = importlib.import_module(f'jobs.tools.{f.stem}')
        except Exception as e:
            logger.debug('tool 로드 실패 %s: %s', f.stem, e)
            continue
        spec = getattr(mod, 'TOOL_SPEC', None)
        exec_fn = getattr(mod, 'execute', None)
        if spec is None or exec_fn is None:
            continue
        result[spec.id] = (spec, exec_fn)
    return result
