# 자기 다짐 건의 흐름 — draft 생성 → 승격 → pending
import pytest
from pathlib import Path
from unittest.mock import AsyncMock


@pytest.fixture
def isolated_suggestion_db(tmp_path, monkeypatch):
  '''suggestion_store의 DB를 tmp_path로 격리.'''
  import db.suggestion_store as store
  monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'suggestions.db')
  yield store


@pytest.mark.asyncio
async def test_commitment_creates_pending(isolated_suggestion_db, tmp_path):
  '''다짐 감지 발화는 pending 상태로 등록되어 게시판 전면에 즉시 노출된다.

  (2026-04-15 업데이트: draft → pending. auto_triage는 [다짐] 접두어로 스킵.)
  '''
  from orchestration import suggestion_filer
  from db.suggestion_store import list_suggestions

  office = AsyncMock()
  office._emit = AsyncMock()
  office._record_dynamic = lambda **kw: None

  await suggestion_filer._file_commitment_suggestion(
    office,
    committer_id='developer',
    message='네, 앞으로 테스트 커버리지 꼼꼼히 챙기겠습니다. 반영하겠습니다.',
    source_speaker='planner',
    source_message='QA 보강 부탁',
    source_log_id='log-xyz',
  )

  all_s = list_suggestions(status='')
  assert len(all_s) == 1
  s = all_s[0]
  assert s['status'] == 'pending'
  assert s['title'].startswith('[다짐]')
  assert s['source_log_id'] == 'log-xyz'
  assert s['target_agent'] == 'developer'


@pytest.mark.asyncio
async def test_repeated_commitment_dedupes(isolated_suggestion_db):
  '''같은 committer가 같은 주제로 두 번 약속해도 중복 등록되지 않는다.

  (이전: draft→pending 승격 테스트였으나, pending이 기본이 되어 중복 스킵으로 동작.)
  '''
  from orchestration import suggestion_filer
  from db.suggestion_store import list_suggestions

  office = AsyncMock()
  office._emit = AsyncMock()
  office._record_dynamic = lambda **kw: None

  msg = '테스트 커버리지 반드시 챙기겠습니다. 이번엔 꼭 반영하겠습니다.'
  await suggestion_filer._file_commitment_suggestion(office, committer_id='developer', message=msg)
  assert [s['status'] for s in list_suggestions(status='')] == ['pending']

  await suggestion_filer._file_commitment_suggestion(office, committer_id='developer', message=msg + ' (재다짐)')
  all_s = list_suggestions(status='')
  assert len(all_s) == 1
  assert all_s[0]['status'] == 'pending'


def test_promote_draft_transition(isolated_suggestion_db):
  '''promote_draft는 draft → pending으로 정확히 1번 전이.'''
  from db.suggestion_store import create_suggestion, promote_draft, get_suggestion

  s = create_suggestion(agent_id='planner', title='t', content='c', status='draft')
  assert promote_draft(s['id']) is True
  assert get_suggestion(s['id'])['status'] == 'pending'
  # 이미 pending이면 False
  assert promote_draft(s['id']) is False


def test_auto_promote_drafts_stale(isolated_suggestion_db, monkeypatch):
  '''24h 경과 draft만 일괄 승격.'''
  from db.suggestion_store import create_suggestion, auto_promote_drafts, list_suggestions, _conn
  from datetime import datetime, timezone, timedelta

  fresh = create_suggestion(agent_id='a', title='fresh', content='c', status='draft')
  stale = create_suggestion(agent_id='a', title='stale', content='c', status='draft')
  # stale의 created_at을 과거로 조작
  old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
  c = _conn()
  c.execute('UPDATE suggestions SET created_at=? WHERE id=?', (old_ts, stale['id']))
  c.commit(); c.close()

  n = auto_promote_drafts(stale_hours=24)
  assert n == 1
  statuses = {s['id']: s['status'] for s in list_suggestions(status='')}
  assert statuses[fresh['id']] == 'draft'
  assert statuses[stale['id']] == 'pending'
