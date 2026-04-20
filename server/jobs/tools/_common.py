"""tools/ 모듈 공용 헬퍼."""
from __future__ import annotations

import os
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / 'data' / 'tool_config.json'


def resolve_token(key: str) -> str:
    """환경변수 → data/tool_config.json 순으로 토큰 조회."""
    env = os.environ.get(key)
    if env:
        return env
    try:
        import json
        if _CONFIG_PATH.exists():
            cfg = json.loads(_CONFIG_PATH.read_text('utf-8'))
            return str(cfg.get(key, ''))
    except Exception:
        pass
    return ''
