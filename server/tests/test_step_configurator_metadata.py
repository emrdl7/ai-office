from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_configure_step_static_spec_adds_decision_metadata():
    from jobs.models import StepSpec
    from jobs.step_configurator import configure_step

    step = StepSpec(
        id='review',
        agent='reviewer',
        tier='standard',
        prompt_template='결과물을 검토한다',
        persona='code_reviewer',
        skills=['code_review'],
        tools=['diff_files'],
    )

    configured = await configure_step(step, {})

    assert configured.execution_mode == 'review'
    assert configured.selection_source == 'spec_static'
    assert '업무 스펙' in configured.selection_reason


@pytest.mark.asyncio
async def test_configure_step_llm_selection_adds_reason(monkeypatch):
    from jobs.models import StepSpec
    from jobs.step_configurator import configure_step

    async def fake_run(**kwargs):
        return json.dumps({
            'persona': 'product_manager',
            'skills': ['requirements_definition'],
            'tools': [],
            'execution_mode': 'single',
            'selection_reason': '요구사항 정리가 핵심이라 PM 관점과 요구사항 정의 스킬을 선택합니다.',
        }, ensure_ascii=False), 'fake-model'

    monkeypatch.setattr(
        'runners.model_router.run',
        fake_run,
        raising=False,
    )

    step = StepSpec(
        id='scope',
        agent='planner',
        tier='nano',
        prompt_template='요구사항을 정리한다',
    )

    configured = await configure_step(step, {})

    assert configured.persona == 'product_manager'
    assert configured.skills == ['requirements_definition']
    assert configured.execution_mode == 'single'
    assert configured.selection_source == 'llm_configurator'
    assert '요구사항' in configured.selection_reason


@pytest.mark.asyncio
async def test_configure_step_cleans_internal_role_terms(monkeypatch):
    from jobs.models import StepSpec
    from jobs.step_configurator import configure_step

    async def fake_run(**kwargs):
        return json.dumps({
            'persona': 'product_manager',
            'skills': ['structured_writing'],
            'tools': [],
            'execution_mode': 'single',
            'selection_reason': '팀원 회의 없이 적절한 에이전트가 처리합니다.',
        }, ensure_ascii=False), 'fake-model'

    monkeypatch.setattr('runners.model_router.run', fake_run, raising=False)

    configured = await configure_step(
        StepSpec(id='write', agent='planner', tier='nano', prompt_template='정리한다'),
        {},
    )

    assert '팀원' not in configured.selection_reason
    assert '회의' not in configured.selection_reason
    assert '에이전트' not in configured.selection_reason


@pytest.mark.asyncio
async def test_configure_step_invalid_mode_falls_back_to_inferred(monkeypatch):
    from jobs.models import StepSpec
    from jobs.step_configurator import configure_step

    async def fake_run(**kwargs):
        return json.dumps({
            'persona': 'senior_ux_researcher',
            'skills': ['research_synthesis'],
            'tools': ['web_search'],
            'execution_mode': 'free_agent_swarm',
            'selection_reason': '최신 자료 확인이 필요합니다.',
        }, ensure_ascii=False), 'fake-model'

    monkeypatch.setattr(
        'runners.model_router.run',
        fake_run,
        raising=False,
    )

    step = StepSpec(
        id='research',
        agent='researcher',
        tier='research',
        prompt_template='시장 동향을 조사한다',
    )

    configured = await configure_step(step, {})

    assert configured.execution_mode == 'research'
    assert configured.selection_source == 'llm_configurator'
