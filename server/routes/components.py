"""컴포넌트 라이브러리 API — 비서 실행 자산 레지스트리."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter

router = APIRouter()

_DATA = Path(__file__).parent.parent.parent / 'data'


def _quality_score(kind: str, item: dict[str, Any]) -> int:
    score = 100
    missing_penalty = sum(18 for issue in item.get('issues', []) if issue.startswith('missing_'))
    warning_penalty = sum(
        8 for issue in item.get('issues', [])
        if issue in {'unused', 'recent_execution_failure', 'experimental', 'token_missing'}
    )
    broken_penalty = 25 if item.get('status') == 'error' else 0
    runtime_penalty = min(int(item.get('failure_count', 0)) * 10, 30)
    if kind == 'tools' and item.get('maturity') == 'experimental':
        warning_penalty += 6
    if kind in {'personas', 'skills'} and not item.get('used_by'):
        warning_penalty += 6
    return max(0, min(100, score - missing_penalty - warning_penalty - broken_penalty - runtime_penalty))


def _quality_band(score: int) -> str:
    if score >= 90:
        return 'ready'
    if score >= 70:
        return 'needs_review'
    return 'blocked'


def _load_yaml_dir(path: Path, kind: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items
    for p in sorted(path.glob('*.yaml')):
        issues: list[str] = []
        try:
            d = yaml.safe_load(p.read_text('utf-8')) or {}
        except Exception as exc:
            items.append({
                'id': p.stem,
                'display_name': p.stem,
                'description': '',
                'category': 'general',
                'tags': [],
                'source': str(p.relative_to(_DATA.parent)),
                'used_by': [],
                'usage_count': 0,
                'failure_count': 0,
                'last_used_at': '',
                'last_error': '',
                'issues': [f'yaml_parse_error: {exc}'],
                'status': 'error',
                'quality_score': 0,
                'quality_band': 'blocked',
            })
            continue

        component_id = d.get('id', p.stem)
        if not d.get('display_name'):
            issues.append('missing_display_name')
        if not d.get('description'):
            issues.append('missing_description')
        if not d.get('category'):
            issues.append('missing_category')
        if kind == 'personas' and not d.get('identity'):
            issues.append('missing_identity')
        if kind == 'personas' and not d.get('selection_criteria'):
            issues.append('missing_selection_criteria')
        if kind == 'personas' and not d.get('output_contract'):
            issues.append('missing_output_contract')
        if kind == 'personas' and not d.get('quality_rubric'):
            issues.append('missing_quality_rubric')
        if kind == 'skills' and not (d.get('thinking_frame') or d.get('output_checklist')):
            issues.append('missing_skill_body')
        if kind == 'skills' and not d.get('input_conditions'):
            issues.append('missing_input_conditions')
        if kind == 'skills' and not d.get('output_template'):
            issues.append('missing_output_template')
        if kind == 'skills' and not d.get('quality_rubric'):
            issues.append('missing_quality_rubric')
        if d.get('id') and d.get('id') != p.stem:
            issues.append('id_filename_mismatch')

        items.append({
            'id': component_id,
            'display_name': d.get('display_name', p.stem),
            'description': d.get('description', ''),
            'category': d.get('category', 'general'),
            'tags': d.get('tags', []) or [],
            'source': str(p.relative_to(_DATA.parent)),
            'used_by': [],
            'usage_count': 0,
            'failure_count': 0,
            'last_used_at': '',
            'last_error': '',
            'issues': issues,
            'status': 'warning' if issues else 'ok',
            'quality_score': 0,
            'quality_band': 'blocked',
        })
    return items


def _component_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item['id']): item for item in items}


def _add_usage(
    idx: dict[str, dict[str, Any]],
    component_id: str,
    usage: dict[str, str],
    broken_refs: list[dict[str, str]],
    kind: str,
) -> None:
    if not component_id:
        return
    item = idx.get(component_id)
    if item is None:
        broken_refs.append({**usage, 'kind': kind, 'id': component_id})
        return
    item['used_by'].append(usage)


def _apply_runtime_stats(items: list[dict[str, Any]], stats: dict[str, dict[str, Any]]) -> None:
    for item in items:
        runtime = stats.get(str(item['id']), {})
        item['usage_count'] = int(runtime.get('usage_count', 0))
        item['failure_count'] = int(runtime.get('failure_count', 0))
        item['last_used_at'] = runtime.get('last_used_at', '')
        item['last_error'] = runtime.get('last_error', '')
        if item['failure_count']:
            item['issues'].append('recent_execution_failure')


def _finalize_component_items(items: list[dict[str, Any]]) -> None:
    for item in items:
        if not item['used_by'] and not item['usage_count']:
            item['issues'].append('unused')
        if item['issues']:
            item['status'] = 'error' if any(
                i.startswith('missing_') or i.endswith('_mismatch') or i.startswith('yaml_parse_error')
                for i in item['issues']
            ) else 'warning'
        else:
            item['status'] = 'ok'
        kind = str(item.get('kind', ''))
        score = _quality_score(kind, item)
        item['quality_score'] = score
        item['quality_band'] = _quality_band(score)


def _apply_spec_usage(
    personas: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> list[dict[str, str]]:
    from jobs.registry import all_specs

    persona_idx = _component_index(personas)
    skill_idx = _component_index(skills)
    tool_idx = _component_index(tools)
    broken_refs: list[dict[str, str]] = []

    for spec in all_specs():
        for step in spec.steps:
            usage = {
                'spec_id': spec.id,
                'spec_title': spec.title,
                'step_id': step.id,
            }
            _add_usage(persona_idx, step.persona, usage, broken_refs, 'persona')
            for skill_id in step.skills:
                _add_usage(skill_idx, skill_id, usage, broken_refs, 'skill')
            for tool_id in step.tools:
                _add_usage(tool_idx, tool_id, usage, broken_refs, 'tool')

    return broken_refs


def _summary(
    personas: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    broken_refs: list[dict[str, str]],
) -> dict[str, Any]:
    all_items = personas + skills + tools
    return {
        'total': len(all_items),
        'ok': sum(1 for item in all_items if item['status'] == 'ok'),
        'warning': sum(1 for item in all_items if item['status'] == 'warning'),
        'error': sum(1 for item in all_items if item['status'] == 'error'),
        'ready': sum(1 for item in all_items if item.get('quality_band') == 'ready'),
        'needs_review': sum(1 for item in all_items if item.get('quality_band') == 'needs_review'),
        'blocked': sum(1 for item in all_items if item.get('quality_band') == 'blocked'),
        'avg_quality_score': round(
            sum(int(item.get('quality_score', 0)) for item in all_items) / len(all_items),
            1,
        ) if all_items else 0,
        'unused': sum(1 for item in all_items if 'unused' in item['issues']),
        'broken_refs': broken_refs,
        'broken_ref_count': len(broken_refs),
    }


@router.get('/api/components')
async def get_components() -> dict[str, Any]:
    """페르소나·스킬·도구 카탈로그와 운영 메타데이터를 통합 반환."""
    from jobs.tool_registry import list_tools
    from db.job_store import get_component_usage_stats

    personas = _load_yaml_dir(_DATA / 'personas', 'personas')
    skills = _load_yaml_dir(_DATA / 'skills', 'skills')
    tools = list_tools()

    for tool in tools:
        tool.setdefault('used_by', [])
        tool.setdefault('usage_count', 0)
        tool.setdefault('failure_count', 0)
        tool.setdefault('last_used_at', '')
        tool.setdefault('last_error', '')
        tool['kind'] = 'tools'
        tool['issues'] = []
        if not tool.get('enabled', True):
            tool['issues'].append('disabled')
        if tool.get('env_var') and not tool.get('token_set'):
            tool['issues'].append('token_missing')
        if tool.get('maturity') == 'experimental':
            tool['issues'].append('experimental')
        tool['status'] = 'warning' if tool['issues'] else 'ok'

    broken_refs = _apply_spec_usage(personas, skills, tools)
    runtime_stats = get_component_usage_stats()
    _apply_runtime_stats(personas, runtime_stats.get('personas', {}))
    _apply_runtime_stats(skills, runtime_stats.get('skills', {}))
    _apply_runtime_stats(tools, runtime_stats.get('tools', {}))
    for group in (personas, skills, tools):
        for item in group:
            item.setdefault('kind', 'personas' if group is personas else 'skills' if group is skills else 'tools')
        _finalize_component_items(group)

    return {
        'personas': personas,
        'skills': skills,
        'tools': tools,
        'summary': _summary(personas, skills, tools, broken_refs),
    }
