from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_components_catalog_exposes_registry_metadata():
    from routes.components import get_components

    data = await get_components()

    assert data['summary']['total'] > 0
    assert data['summary']['broken_ref_count'] == len(data['summary']['broken_refs'])

    persona = data['personas'][0]
    assert {'used_by', 'usage_count', 'issues', 'status', 'source', 'quality_score', 'quality_band'} <= set(persona)
    assert not any('missing_' in issue for p in data['personas'] for issue in p['issues'])
    assert not any('missing_' in issue for s in data['skills'] for issue in s['issues'])

    tool = data['tools'][0]
    assert {'used_by', 'usage_count', 'issues', 'status', 'enabled', 'input_contract', 'failure_policy'} <= set(tool)
    assert 'maturity' in tool
    assert 'avg_quality_score' in data['summary']


def test_component_catalog_detects_broken_spec_refs(monkeypatch):
    from routes import components

    step = SimpleNamespace(
        id='draft',
        persona='missing_persona',
        skills=['missing_skill'],
        tools=['missing_tool'],
    )
    spec = SimpleNamespace(id='sample', title='Sample Spec', steps=[step])
    monkeypatch.setattr('jobs.registry.all_specs', lambda: [spec])

    broken = components._apply_spec_usage(
        personas=[],
        skills=[],
        tools=[],
    )

    assert {item['kind'] for item in broken} == {'persona', 'skill', 'tool'}
    assert {item['id'] for item in broken} == {'missing_persona', 'missing_skill', 'missing_tool'}


def test_prompt_composer_includes_tool_contracts():
    from jobs.prompt_composer import compose_system_prompt

    step = SimpleNamespace(
        persona='',
        skills=[],
        tools=['read_file', 'missing_tool'],
        system_prompt='본문만 작성하세요.',
    )

    prompt = compose_system_prompt(step)

    assert '## 툴 사용 계약' in prompt
    assert '필수 입력: file_path' in prompt
    assert '등록되지 않은 도구' in prompt
    assert '본문만 작성하세요.' in prompt
