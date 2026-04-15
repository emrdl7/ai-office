# log_store.search_logs / list_suggestions 필터 확장 단위 테스트.
import pytest


@pytest.fixture
def fresh_dbs(tmp_path, monkeypatch):
  import db.log_store as ls
  import db.suggestion_store as ss
  monkeypatch.setattr(ls, 'DB_PATH', tmp_path / 'logs.db')
  monkeypatch.setattr(ss, 'DB_PATH', tmp_path / 'sugg.db')
  return ls, ss


def _save_log(ls, idx, agent, message):
  from datetime import datetime, timezone, timedelta
  ts = (datetime.now(timezone.utc) - timedelta(minutes=100 - idx)).isoformat()
  ls.save_log({
    'id': f'log-{idx}',
    'agent_id': agent,
    'event_type': 'response',
    'message': message,
    'data': {},
    'timestamp': ts,
  })


def test_search_logs_by_query(fresh_dbs):
  ls, _ = fresh_dbs
  _save_log(ls, 1, 'planner', '일정 조율이 필요합니다')
  _save_log(ls, 2, 'developer', '버그 수정했습니다')
  _save_log(ls, 3, 'designer', '일정 관련 의견 드립니다')
  results = ls.search_logs(q='일정')
  messages = [r['message'] for r in results]
  assert len(results) == 2
  assert all('일정' in m for m in messages)


def test_search_logs_by_agent(fresh_dbs):
  ls, _ = fresh_dbs
  _save_log(ls, 1, 'planner', 'A')
  _save_log(ls, 2, 'developer', 'B')
  _save_log(ls, 3, 'planner', 'C')
  results = ls.search_logs(agent_id='planner')
  assert len(results) == 2
  assert all(r['agent_id'] == 'planner' for r in results)


def test_suggestions_filter_by_category_and_q(fresh_dbs):
  _, ss = fresh_dbs
  ss.create_suggestion(agent_id='teamlead', title='QA규칙 섹션 누락',
                       content='필수 섹션', category='QA 규칙', target_agent='developer')
  ss.create_suggestion(agent_id='planner', title='일정 단축',
                       content='스프린트 축소', category='프로세스 개선')
  ss.create_suggestion(agent_id='teamlead', title='다른 QA',
                       content='무관', category='QA 규칙')

  qa_only = ss.list_suggestions(category='QA 규칙')
  assert len(qa_only) == 2

  qa_and_q = ss.list_suggestions(category='QA 규칙', q='섹션')
  assert len(qa_and_q) == 1
  assert '섹션' in qa_and_q[0]['title']

  target_filter = ss.list_suggestions(target_agent='developer')
  assert len(target_filter) == 1
  assert target_filter[0]['target_agent'] == 'developer'


def test_suggestions_q_matches_content(fresh_dbs):
  _, ss = fresh_dbs
  ss.create_suggestion(agent_id='teamlead', title='제목',
                       content='본문에 레이아웃 키워드', category='아이디어')
  ss.create_suggestion(agent_id='teamlead', title='다른 건',
                       content='무관 내용', category='아이디어')
  results = ss.list_suggestions(q='레이아웃')
  assert len(results) == 1
  assert '레이아웃' in results[0]['content']
