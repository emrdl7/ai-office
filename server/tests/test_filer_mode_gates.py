'''suggestion_filer의 mode 게이트 — 농담/리액션/트렌드 공유 오탐 차단.'''
from types import SimpleNamespace
import pytest

from orchestration import suggestion_filer as sf


class _StubBus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


def _mk_office():
    return SimpleNamespace(event_bus=_StubBus())


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['joke', 'reaction', 'trend_research'])
async def test_auto_file_suggestion_skipped_for_joke_reaction_trend(monkeypatch, mode):
    called = {'n': 0}

    def fake_create_suggestion(**kw):
        called['n'] += 1
        return {'id': 'x'}

    monkeypatch.setattr(
        'db.suggestion_store.create_suggestion', fake_create_suggestion,
    )
    monkeypatch.setattr(
        'db.suggestion_store.list_suggestions', lambda **kw: [],
    )

    # 강한 제안 시그널을 가진 메시지 — 원래는 건의로 등록될 것
    msg = '이 부분은 반드시 도입해야 합니다. 체크리스트로 규칙으로 정하자.'
    await sf._auto_file_suggestion(_mk_office(), 'developer', msg, mode=mode)
    assert called['n'] == 0  # mode 게이트로 차단


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['joke', 'trend_research'])
async def test_commitment_suggestion_skipped_for_joke_trend(monkeypatch, mode):
    called = {'n': 0}

    def fake_create_suggestion(**kw):
        called['n'] += 1
        return {'id': 'x'}

    monkeypatch.setattr(
        'db.suggestion_store.create_suggestion', fake_create_suggestion,
    )
    monkeypatch.setattr(
        'db.suggestion_store.list_suggestions', lambda **kw: [],
    )

    msg = '앞으로는 제가 직접 반영하겠습니다. 다음 주까지 적용하겠어요.'
    await sf._file_commitment_suggestion(
        _mk_office(), 'designer', msg, mode=mode,
    )
    assert called['n'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['joke', 'reaction', 'trend_research'])
async def test_capability_gap_skipped_for_non_improvement(monkeypatch, mode):
    called = {'n': 0}

    def fake_create_suggestion(**kw):
        called['n'] += 1
        return {'id': 'x'}

    monkeypatch.setattr(
        'db.suggestion_store.create_suggestion', fake_create_suggestion,
    )
    monkeypatch.setattr(
        'db.suggestion_store.list_suggestions', lambda **kw: [],
    )

    # 능력 부족 마커 포함 — 정상 모드면 건의될 메시지
    msg = '이 회의 kill -9 하고 싶은데 권한이 없네요. ㅎㅎ'
    await sf._file_capability_gap_suggestion(
        _mk_office(), 'developer', msg, mode=mode,
    )
    assert called['n'] == 0


@pytest.mark.asyncio
async def test_capability_gap_fires_when_mode_blank(monkeypatch):
    '''mode가 명시되지 않으면(비어있으면) 기존 휴리스틱대로 동작.'''
    created = []

    def fake_create_suggestion(**kw):
        created.append(kw)
        return {'id': 'gap-1'}

    monkeypatch.setattr(
        'db.suggestion_store.create_suggestion', fake_create_suggestion,
    )
    monkeypatch.setattr(
        'db.suggestion_store.list_suggestions', lambda **kw: [],
    )

    msg = (
        '이 작업을 자동화하려는데, 필요한 배포 스크립트가 없네요. '
        '수동으로 커밋 해시 일일이 확인해야 해서 비효율적입니다.'
    )
    await sf._file_capability_gap_suggestion(
        _mk_office(), 'developer', msg,  # mode 미지정
    )
    assert len(created) == 1
    assert created[0].get('category') in ('도구 부족', '정보 부족')
