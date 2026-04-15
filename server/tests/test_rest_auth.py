# REST_AUTH_TOKEN 미들웨어 동작 검증
# - 토큰 미설정 시 현재 동작(무제한) 유지
# - 토큰 설정 시 /api/* 401, /health 면제
# - Bearer 와 ?token= 둘 다 인정
# - 잘못된 토큰 거부

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


def _reload_main():
  # main 모듈은 import 시 REST_AUTH_TOKEN을 읽으므로 환경 바꾼 뒤 재로드
  if 'main' in sys.modules:
    del sys.modules['main']
  return importlib.import_module('main')


@pytest.fixture
def client_no_token(monkeypatch):
  monkeypatch.delenv('REST_AUTH_TOKEN', raising=False)
  m = _reload_main()
  with TestClient(m.app) as c:
    yield c


@pytest.fixture
def client_with_token(monkeypatch):
  monkeypatch.setenv('REST_AUTH_TOKEN', 'secret-xyz')
  m = _reload_main()
  with TestClient(m.app) as c:
    yield c


def test_health_always_exempt(client_no_token, client_with_token):
  assert client_no_token.get('/health').status_code == 200
  assert client_with_token.get('/health').status_code == 200


def test_no_token_mode_passes_through(client_no_token):
  # 토큰 미설정 시 미들웨어 우회 (기존 동작 보존)
  # 인증 단계는 통과, 이후 실제 핸들러 결과는 별개
  r = client_no_token.get('/api/agents')
  assert r.status_code != 401


def test_api_rejects_missing_token(client_with_token):
  r = client_with_token.get('/api/agents')
  assert r.status_code == 401
  assert r.json()['detail'] == 'Unauthorized'


def test_api_rejects_wrong_bearer(client_with_token):
  r = client_with_token.get('/api/agents', headers={'Authorization': 'Bearer nope'})
  assert r.status_code == 401


def test_api_accepts_correct_bearer(client_with_token):
  r = client_with_token.get('/api/agents', headers={'Authorization': 'Bearer secret-xyz'})
  # 인증 통과 (이후 핸들러 에러 여부와 무관)
  assert r.status_code != 401


def test_api_accepts_query_token(client_with_token):
  r = client_with_token.get('/api/agents?token=secret-xyz')
  assert r.status_code != 401


def test_ws_token_endpoint_is_protected(client_with_token):
  # /api/ws-token은 면제 대상이 아님 — 토큰 탈취 방지
  r = client_with_token.get('/api/ws-token')
  assert r.status_code == 401
