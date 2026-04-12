# 오늘의 한마디 저장소 — 날짜 기반 JSON 캐시
import json
from datetime import date
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).parent.parent / 'data' / 'daily_quotes.json'

AGENT_PERSONAS = {
  'teamlead': '오상식 팀장. 과묵하고 날카로운 통찰력. 짧고 무게감 있는 말투. 인생과 일에 대한 깊은 관찰자.',
  'planner': '장그래. 바둑처럼 수를 읽고 전략을 짠다. 진지하고 성실하며 세상을 배워가는 중. 약간 문학적.',
  'designer': '안영이. 타협을 모르는 완벽주의 디자이너. 직설적이고 자신감 넘침. 미적 감각에 대한 자부심.',
  'developer': '김동식. 묵묵하고 실용적. 말보다 코드로 말하는 스타일. 솔직담백하고 가끔 위트.',
  'qa': '한석율. 냉철하고 꼼꼼한 검수 전문가. 완벽을 추구하되 현실적. 날카로운 한 마디로 핵심을 찌름.',
}


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
