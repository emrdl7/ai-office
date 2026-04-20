"""컴포넌트 라이브러리 API — Job 파이프라인에서 선택 가능한 페르소나·스킬·도구 카탈로그."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

router = APIRouter()

_DATA = Path(__file__).parent.parent.parent / 'data'


def _load_yaml_dir(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items
    for p in sorted(path.glob('*.yaml')):
        try:
            d = yaml.safe_load(p.read_text('utf-8')) or {}
        except Exception:
            continue
        items.append({
            'id': d.get('id', p.stem),
            'display_name': d.get('display_name', p.stem),
            'description': d.get('description', ''),
            'category': d.get('category', 'general'),
            'tags': d.get('tags', []) or [],
        })
    return items


@router.get('/api/components')
async def get_components() -> dict[str, Any]:
    """페르소나·스킬·도구 카탈로그 통합 반환."""
    from jobs.tool_registry import list_tools
    return {
        'personas': _load_yaml_dir(_DATA / 'personas'),
        'skills': _load_yaml_dir(_DATA / 'skills'),
        'tools': list_tools(),
    }
