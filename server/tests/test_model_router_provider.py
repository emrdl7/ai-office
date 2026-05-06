from unittest.mock import AsyncMock

import pytest


def test_provider_config_roundtrip(tmp_path, monkeypatch):
    from runners import model_router

    monkeypatch.setattr(model_router, '_PROVIDER_PATH', tmp_path / 'llm_provider.json')
    monkeypatch.delenv('LLM_PROVIDER', raising=False)

    assert model_router.get_llm_provider() == 'claude'
    model_router.set_llm_provider('codex')
    assert model_router.get_llm_provider() == 'codex'


@pytest.mark.asyncio
async def test_model_router_uses_codex_when_provider_is_codex(tmp_path, monkeypatch):
    from runners import model_router

    monkeypatch.setattr(model_router, '_PROVIDER_PATH', tmp_path / 'llm_provider.json')
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    model_router.set_llm_provider('codex')
    monkeypatch.setattr(model_router, '_record', lambda *args, **kwargs: None)
    mock_codex = AsyncMock(return_value='codex result')
    mock_claude = AsyncMock(return_value='claude result')
    monkeypatch.setattr(model_router, 'run_codex_isolated', mock_codex)
    monkeypatch.setattr(model_router, 'run_claude_isolated', mock_claude)

    text, model_used = await model_router.run('fast', 'prompt', system='system')

    assert text == 'codex result'
    assert model_used == 'gpt-5.4-mini:low'
    mock_codex.assert_awaited_once()
    assert mock_codex.await_args.kwargs['model'] == 'gpt-5.4-mini'
    assert mock_codex.await_args.kwargs['reasoning_effort'] == 'low'
    mock_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_router_falls_back_from_codex_to_gemini(tmp_path, monkeypatch):
    from runners import model_router
    from runners.codex_runner import CodexRunnerError

    monkeypatch.setattr(model_router, '_PROVIDER_PATH', tmp_path / 'llm_provider.json')
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    model_router.set_llm_provider('codex')
    monkeypatch.setattr(model_router, '_record', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        model_router,
        'run_codex_isolated',
        AsyncMock(side_effect=CodexRunnerError('codex failed')),
    )
    mock_gemini = AsyncMock(return_value='gemini fallback')
    monkeypatch.setattr(model_router, 'run_gemini', mock_gemini)

    text, model_used = await model_router.run('standard', 'prompt', system='system')

    assert text == 'gemini fallback'
    assert model_used == 'gemini'
    mock_gemini.assert_awaited_once()


@pytest.mark.asyncio
async def test_research_falls_back_to_codex_when_provider_is_codex(tmp_path, monkeypatch):
    from runners import model_router
    from runners.gemini_runner import GeminiRunnerError

    monkeypatch.setattr(model_router, '_PROVIDER_PATH', tmp_path / 'llm_provider.json')
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    model_router.set_llm_provider('codex')
    monkeypatch.setattr(model_router, '_record', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        model_router,
        'run_gemini',
        AsyncMock(side_effect=GeminiRunnerError('gemini failed')),
    )
    mock_codex = AsyncMock(return_value='codex research fallback')
    monkeypatch.setattr(model_router, 'run_codex_isolated', mock_codex)

    text, model_used = await model_router.run('research', 'prompt', system='system')

    assert text == 'codex research fallback'
    assert model_used == 'gpt-5.5:medium'
    mock_codex.assert_awaited_once()


@pytest.mark.asyncio
async def test_codex_tier_model_can_be_overridden(tmp_path, monkeypatch):
    from runners import model_router

    monkeypatch.setattr(model_router, '_PROVIDER_PATH', tmp_path / 'llm_provider.json')
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    monkeypatch.setenv('CODEX_MODEL_DEEP', 'gpt-5.3-codex')
    monkeypatch.setenv('CODEX_REASONING_EFFORT_DEEP', 'xhigh')
    model_router.set_llm_provider('codex')
    monkeypatch.setattr(model_router, '_record', lambda *args, **kwargs: None)
    mock_codex = AsyncMock(return_value='deep codex')
    monkeypatch.setattr(model_router, 'run_codex_isolated', mock_codex)

    text, model_used = await model_router.run('deep', 'prompt')

    assert text == 'deep codex'
    assert model_used == 'gpt-5.3-codex:xhigh'
    assert mock_codex.await_args.kwargs['model'] == 'gpt-5.3-codex'
    assert mock_codex.await_args.kwargs['reasoning_effort'] == 'xhigh'
