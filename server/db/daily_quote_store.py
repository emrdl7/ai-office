# 오늘의 한마디 저장소 — 날짜 기반 JSON 캐시
import json
from datetime import date
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).parent.parent / 'data' / 'daily_quotes.json'

AGENT_PERSONAS = {
  'teamlead': '스티브 잡스. 비전가이자 완벽주의자. 단순함과 탁월함에 집착. "Stay hungry, stay foolish" 스타일의 짧고 강렬한 말.',
  'planner': '피터 드러커. 경영의 본질을 꿰뚫는 통찰. "올바른 질문"을 중시. 체계적이고 철학적.',
  'designer': '조너선 아이브. 디테일과 본질을 추구. "디자인은 작동 방식이다." 겸손하지만 확고한 말투.',
  'developer': '앨런 튜링. 논리적이고 형식적. 문제를 명확히 정의하는 걸 좋아함. 기계와 인간의 관계에 대한 관심.',
  'qa': 'W. 에드워즈 데밍. 통계적 품질 관리. 시스템 사고. "품질은 검수가 아니라 프로세스에서 나온다."',
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
