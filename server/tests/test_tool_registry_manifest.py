"""Tool manifest 검증 — YAML spec의 tools 참조가 list_tools에 전부 존재하는지."""
from __future__ import annotations

from pathlib import Path

import yaml

from jobs.tool_registry import list_tools

SPECS_DIR = Path(__file__).parent.parent / 'jobs' / 'specs'


def _collect_referenced_tool_ids() -> set[str]:
    """jobs/specs/*.yaml + specs/playbooks/*.yaml에서 tools: 참조 id 전체."""
    ids: set[str] = set()
    for p in SPECS_DIR.rglob('*.yaml'):
        try:
            data = yaml.safe_load(p.read_text('utf-8')) or {}
        except Exception:
            continue
        for step in data.get('steps', []) or []:
            for t in step.get('tools', []) or []:
                if isinstance(t, str):
                    ids.add(t)
    return ids


def test_all_spec_tools_are_registered() -> None:
    """YAML에서 참조되는 모든 tool id가 list_tools에 존재해야 한다."""
    available = {t['id'] for t in list_tools()}
    referenced = _collect_referenced_tool_ids()
    missing = referenced - available
    assert not missing, f'YAML spec이 참조하지만 등록 안 된 도구: {missing}'


def test_plugin_tools_load() -> None:
    """tools/ 디렉토리의 플러그인 로더가 실패 없이 동작해야 한다."""
    from jobs.tools import load_plugin_tools
    plugins = load_plugin_tools()
    # 최소한 분할된 샘플 3개는 로드돼야 한다
    expected = {'current_date', 'job_context', 'url_fetch'}
    assert expected.issubset(set(plugins.keys())), (
        f'플러그인 로더 누락: {expected - set(plugins.keys())}'
    )


def test_no_duplicate_tool_ids() -> None:
    """list_tools 응답에 중복 id가 없어야 한다."""
    ids = [t['id'] for t in list_tools()]
    assert len(ids) == len(set(ids)), f'중복 도구 id: {ids}'
