# 자율 루프 digest state 라운드트립 + 키워드 추출 smoke.
import json
from unittest.mock import MagicMock


def test_digest_state_roundtrip(tmp_path, monkeypatch):
  '''save_digest_state → load_digest_state 라운드트립이 보존된다.'''
  import orchestration.autonomous_loop as al
  monkeypatch.setattr(al, '_DIGEST_PATH', tmp_path / 'digest.json')

  office = MagicMock()
  state = {
    'last_reviewed_ts': '2026-04-15T00:00:00+00:00',
    'last_summary': '팀장 요약 텍스트',
    'history': [{'ts': '2026-04-15T00:00:00+00:00', 'summary': 's1'}],
  }
  al.save_digest_state(office, state)
  loaded = al.load_digest_state(office)
  assert loaded == state


def test_digest_state_default_when_missing(tmp_path, monkeypatch):
  '''파일이 없으면 기본 구조를 반환한다.'''
  import orchestration.autonomous_loop as al
  monkeypatch.setattr(al, '_DIGEST_PATH', tmp_path / 'missing.json')

  office = MagicMock()
  loaded = al.load_digest_state(office)
  assert loaded == {'last_reviewed_ts': '', 'last_summary': '', 'history': []}


def test_digest_state_handles_corrupt_json(tmp_path, monkeypatch):
  '''JSON이 깨져도 예외 없이 기본값 반환.'''
  import orchestration.autonomous_loop as al
  p = tmp_path / 'bad.json'
  p.write_text('{not valid json')
  monkeypatch.setattr(al, '_DIGEST_PATH', p)

  office = MagicMock()
  loaded = al.load_digest_state(office)
  assert loaded['last_reviewed_ts'] == ''


def test_stuck_detection_keyword_repetition():
  '''_extract_keywords가 한글 2자+/영문 3자+ 토큰을 중복 수집한다.'''
  from orchestration.office import _extract_keywords
  text = '테스트 커버리지 테스트 커버리지 테스트 커버리지'
  kws = _extract_keywords(text)
  # 같은 텍스트 반복 → set 변환 후에도 '테스트', '커버리지' 포함
  assert '테스트' in kws
  assert '커버리지' in kws
