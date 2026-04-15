'''suggestion_filer의 mode 게이트 + P2 구체성/중복 게이트 테스트.'''
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

    # gate 3 통과를 위해 파일명(tech token) 포함 + 40자 이상
    msg = (
        '이 작업을 자동화하려는데, 필요한 deploy.sh 배포 스크립트가 없네요. '
        '수동으로 커밋 해시 일일이 확인해야 해서 비효율적입니다.'
    )
    await sf._file_capability_gap_suggestion(
        _mk_office(), 'developer', msg,  # mode 미지정
    )
    assert len(created) == 1
    assert created[0].get('category') in ('도구 부족', '정보 부족')


# ──────────────────────────────────────────────
# P2 gate 3: 구체성 (specificity) gate
# ──────────────────────────────────────────────

def _patch_no_dup(monkeypatch):
    '''중복/DB 호출을 모두 패스-스루로 패치.'''
    monkeypatch.setattr('db.suggestion_store.is_duplicate', lambda t, c, **kw: (False, ''))
    monkeypatch.setattr('db.suggestion_store.is_title_duplicate_48h', lambda t: (False, ''))
    monkeypatch.setattr('db.suggestion_store.list_suggestions', lambda **kw: [])
    monkeypatch.setattr('db.suggestion_store.log_event', lambda *a, **kw: None)
    monkeypatch.setattr('db.suggestion_store.detect_target_agent', lambda msg, speaker='': '')


@pytest.mark.asyncio
async def test_auto_file_suggestion_blocked_short_message(monkeypatch):
    '''40자 미만 메시지는 gate 3로 차단.'''
    _patch_no_dup(monkeypatch)
    called = {'n': 0}
    monkeypatch.setattr('db.suggestion_store.create_suggestion', lambda **kw: called.__setitem__('n', called['n'] + 1) or {'id': 'x'})

    # 강한 제안 시그널 있지만 짧은 메시지
    msg = '이 부분 규칙으로 정하자.'  # < 40자, 기술 토큰 없음
    await sf._auto_file_suggestion(_mk_office(), 'developer', msg)
    assert called['n'] == 0, 'gate 3 (짧은 메시지)로 차단되어야 함'


@pytest.mark.asyncio
async def test_auto_file_suggestion_blocked_no_tech_token(monkeypatch):
    '''기술 토큰 없는 추상 관찰은 gate 3로 차단.'''
    _patch_no_dup(monkeypatch)
    called = {'n': 0}
    monkeypatch.setattr('db.suggestion_store.create_suggestion', lambda **kw: called.__setitem__('n', called['n'] + 1) or {'id': 'x'})

    # 40자 이상이지만 파일명/함수명/해시/에러코드 없음
    msg = '이 프로세스를 반드시 개선해야 합니다. 현재 방식이 비효율적이어서 팀 생산성에 악영향을 줍니다.'
    await sf._auto_file_suggestion(_mk_office(), 'developer', msg)
    assert called['n'] == 0, 'gate 3 (기술 토큰 없음)로 차단되어야 함'


@pytest.mark.asyncio
async def test_auto_file_suggestion_passes_with_tech_token(monkeypatch):
    '''40자 이상 + 기술 토큰 있으면 gate 3 통과.'''
    _patch_no_dup(monkeypatch)
    created = []
    monkeypatch.setattr('db.suggestion_store.create_suggestion', lambda **kw: created.append(kw) or {'id': 'x'})

    # deploy.sh = tech token, 자동화가 필요 = 도구 부족 카테고리 키워드,
    # 규칙으로 정하자 = strong_proposal 마커
    msg = (
        'deploy.sh 배포 스크립트가 없어서 자동화가 필요합니다. '
        '이 도구를 도입하자는 의견을 규칙으로 정하자.'
    )
    await sf._auto_file_suggestion(_mk_office(), 'developer', msg)
    assert len(created) == 1, 'gate 3 통과 후 등록되어야 함'


# ──────────────────────────────────────────────
# P2 gate 2: 제목 48h 중복 gate
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_file_suggestion_blocked_title_48h_dup(monkeypatch):
    '''48h 이내 동일 제목이 pending에 있으면 gate 2로 차단.'''
    monkeypatch.setattr('db.suggestion_store.is_title_duplicate_48h', lambda t: (True, 'abc123(pending) title_dedup_48h=0.80'))
    monkeypatch.setattr('db.suggestion_store.is_duplicate', lambda t, c, **kw: (False, ''))
    monkeypatch.setattr('db.suggestion_store.list_suggestions', lambda **kw: [])
    monkeypatch.setattr('db.suggestion_store.log_event', lambda *a, **kw: None)
    monkeypatch.setattr('db.suggestion_store.detect_target_agent', lambda msg, speaker='': '')
    called = {'n': 0}
    monkeypatch.setattr('db.suggestion_store.create_suggestion', lambda **kw: called.__setitem__('n', called['n'] + 1) or {'id': 'x'})

    msg = (
        'deploy.sh 배포 스크립트가 없어서 자동화 도구를 도입해야 합니다. '
        '규칙으로 정하자.'
    )
    await sf._auto_file_suggestion(_mk_office(), 'developer', msg)
    assert called['n'] == 0, 'gate 2 (48h title 중복)로 차단되어야 함'


@pytest.mark.asyncio
async def test_commitment_suggestion_blocked_title_48h_dup(monkeypatch):
    '''다짐도 gate 2 적용 — 같은 제목이 48h 내 있으면 차단.'''
    monkeypatch.setattr('db.suggestion_store.is_title_duplicate_48h', lambda t: (True, 'def456(pending) title_dedup_48h=0.75'))
    monkeypatch.setattr('db.suggestion_store.is_duplicate', lambda t, c, **kw: (False, ''))
    monkeypatch.setattr('db.suggestion_store.list_suggestions', lambda **kw: [])
    monkeypatch.setattr('db.suggestion_store.log_event', lambda *a, **kw: None)
    monkeypatch.setattr('db.suggestion_store.promote_draft', lambda sid: False)
    called = {'n': 0}
    monkeypatch.setattr('db.suggestion_store.create_suggestion', lambda **kw: called.__setitem__('n', called['n'] + 1) or {'id': 'x'})

    msg = '다음 주까지 review.py 코드 리뷰 프로세스를 개선하겠습니다.'
    await sf._file_commitment_suggestion(_mk_office(), 'developer', msg)
    assert called['n'] == 0, 'gate 2 (48h title 중복)로 차단되어야 함'


@pytest.mark.asyncio
async def test_has_tech_token_patterns():
    '''_has_tech_token 패턴 검증.'''
    assert sf._has_tech_token('deploy.sh 파일을 추가해야 합니다')
    assert sf._has_tech_token('create_suggestion 함수를 수정하자')
    assert sf._has_tech_token('커밋 abc1234 기준으로')
    assert sf._has_tech_token('404 에러가 발생합니다')
    assert sf._has_tech_token('ValueError가 발생합니다')
    assert sf._has_tech_token('/api/suggestions 엔드포인트')
    assert sf._has_tech_token('`is_duplicate` 함수')
    assert not sf._has_tech_token('프로세스를 개선해야 합니다')
    assert not sf._has_tech_token('팀원 간 소통이 부족합니다')
