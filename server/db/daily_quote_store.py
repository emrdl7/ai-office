# 오늘의 한마디 저장소 — 날짜 기반 JSON 캐시
import json
from datetime import date
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).parent.parent / 'data' / 'daily_quotes.json'

# config/team.py에서 페르소나 가져옴 — 팀원 교체 시 그 쪽만 수정하면 됨
from config.team import TEAM
AGENT_PERSONAS = {m.agent_id: f'{m.full_name}. {m.persona}' for m in TEAM}


def _today() -> str:
  return date.today().isoformat()


def load() -> dict:
  if STORE_PATH.exists():
    try:
      return json.loads(STORE_PATH.read_text(encoding='utf-8'))
    except Exception:
      logger.debug("오늘의 한마디 JSON 로드 실패", exc_info=True)
  return {}


def save(data: dict):
  STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
  STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def get_quotes() -> dict[str, str]:
  '''오늘의 한마디를 반환한다. 저장된 오늘 날짜 데이터가 있으면 그대로, 없으면 빈 dict.'''
  data = load()
  if data.get('date') == _today():
    return data.get('quotes', {})
  return {}


def save_quotes(quotes: dict[str, str]):
  '''오늘 날짜로 한마디를 저장한다.'''
  save({'date': _today(), 'quotes': quotes})
