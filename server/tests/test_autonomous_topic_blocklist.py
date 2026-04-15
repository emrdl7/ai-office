'''자율 루프 반복 방지 보강 — blocklist · team_recent_lines · _choose_topic 주입.'''
from types import SimpleNamespace

from orchestration import autonomous_loop as al


def _mk_log(agent_id: str, message: str, event_type: str = 'autonomous') -> dict:
    return {'agent_id': agent_id, 'event_type': event_type, 'message': message}


def test_gather_recent_topic_blocklist_counts_autonomous_and_suggestions(monkeypatch):
    logs = [
        _mk_log('designer', 'SearchPanel 접근성 테스트 추가해야 합니다'),
        _mk_log('qa', 'SearchPanel 접근성 단언 강화'),
        _mk_log('developer', 'vitest changed 플래그로 CI 속도 개선'),
    ]
    monkeypatch.setattr('db.log_store.load_logs', lambda limit=40: logs)
    monkeypatch.setattr(
        'db.suggestion_store.list_suggestions',
        lambda status=None: [{'title': 'SearchPanel 접근성 추가'}],
    )

    blocklist = al._gather_recent_topic_blocklist(SimpleNamespace())
    # SearchPanel·접근성은 autonomous 2회 + suggestion(가중 2배) → 최상위
    assert 'SearchPanel' in blocklist or 'searchpanel' in [b.lower() for b in blocklist]
    assert any('접근성' in b for b in blocklist)


def test_gather_recent_topic_blocklist_ignores_single_mention(monkeypatch):
    logs = [
        _mk_log('designer', '한번만 등장하는 단어 스파게티스트라이커'),
    ]
    monkeypatch.setattr('db.log_store.load_logs', lambda limit=40: logs)
    monkeypatch.setattr('db.suggestion_store.list_suggestions', lambda status=None: [])
    blocklist = al._gather_recent_topic_blocklist(SimpleNamespace())
    assert not any('스파게티스트라이커' in b for b in blocklist)


def test_team_recent_lines_includes_peer_context():
    logs = [
        _mk_log('designer', '나(스피커) 발언 1'),
        _mk_log('designer', '나 발언 2'),
        _mk_log('qa', '동료 QA 발언 1'),
        _mk_log('qa', '동료 QA 발언 2'),
        _mk_log('developer', '동료 DEV 발언 1'),
    ]
    lines = al._team_recent_lines(logs, speaker_name='designer')
    joined = '\n'.join(lines)
    # 본인 발언은 프리픽스 없이, 동료는 [agent_id] 프리픽스
    assert '나(스피커) 발언 1' in joined
    assert '[qa]' in joined
    assert '[developer]' in joined


def test_choose_topic_includes_blocklist_even_when_not_stuck():
    # stuck=False여도 blocklist가 전달되면 banned_kws가 프롬프트에 들어가야 함
    topic = al._choose_topic(
        stuck=False, repeated=[], concrete_seed='', recent_context='최근 대화',
        project_context='', recent_topic_blocklist=['접근성', 'SearchPanel'],
    )
    assert '절대 금지' in topic
    assert '접근성' in topic
    assert 'SearchPanel' in topic


def test_choose_topic_no_blocklist_when_none():
    topic = al._choose_topic(
        stuck=False, repeated=[], concrete_seed='', recent_context='x',
        project_context='', recent_topic_blocklist=[],
    )
    assert '절대 금지' not in topic
