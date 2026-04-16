'''트렌드 리서치 → 프롬프트 강화 + 토론형 외부 동향 공급

두 가지 경로:
  A. 기존 maybe_research (~12%): 검색 → 규칙 등록 → 알림 발화
  B. 신규 research_for_discussion (~45%): 검색/RSS → 토론 주제 반환
     → autonomous_loop에서 일반 체인(반응→클로징)을 태워 토론 유도

B 경로 흐름:
  1. 동적 검색어 생성 (Gemini) 또는 RSS 피드 파싱
  2. DuckDuckGo/RSS → 결과 텍스트
  3. Gemini가 토론할 만한 소식 1건 요약 (규칙 등록 X)
  4. 토론 주제 문자열 반환 → agent.reflect(mode='external_trend')로 전달

같은 일자 동일 검색 키워드는 캐시(스테이트 파일)로 중복 차단.
'''
from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.team import display_name
from log_bus.event_bus import LogEvent
from runners.gemini_runner import run_gemini

logger = logging.getLogger(__name__)

_STATE_PATH = Path(__file__).parent.parent / 'data' / 'trend_research_state.json'

# 에이전트별 검색어 후보 — 각자의 전문 영역에서 최신 트렌드/기법 발굴
_QUERY_BANK: dict[str, list[str]] = {
  'planner': [
    'PM 기획 트렌드 2026',
    'product discovery framework 2026',
    'OKR alternatives 2026',
    'AI product management practices',
    'jobs to be done framework 2026',
  ],
  'designer': [
    'UX design trends 2026',
    'design system 2026 best practices',
    'figma component patterns 2026',
    'accessibility WCAG 3 updates',
    'motion design principles 2026',
  ],
  'developer': [
    'python web framework 2026',
    'fastapi best practices 2026',
    'react 19 patterns',
    'typescript 5.5 patterns 2026',
    'AI coding agent patterns 2026',
  ],
  'qa': [
    'AI test automation trends 2026',
    'playwright best practices 2026',
    'contract testing patterns',
    'visual regression testing 2026',
    'LLM evaluation framework 2026',
  ],
}


# RSS 피드 소스 — 공개 피드에서 업계 동향/기술 트렌드 수집
_RSS_FEEDS: list[dict[str, str]] = [
  {'name': 'Hacker News (Top)', 'url': 'https://hnrss.org/best?count=5'},
  {'name': 'TechCrunch', 'url': 'https://techcrunch.com/feed/'},
  {'name': 'The Verge', 'url': 'https://www.theverge.com/rss/index.xml'},
  {'name': 'AI News (MIT)', 'url': 'https://news.mit.edu/topic/artificial-intelligence2/feed'},
]

# 에이전트별 동적 검색어 생성용 전문 영역 힌트
_DOMAIN_HINTS: dict[str, str] = {
  'planner': '프로덕트 매니지먼트, 기획 방법론, 사용자 리서치, 비즈니스 전략, 스타트업 전략',
  'designer': 'UI/UX 디자인, 디자인 시스템, 접근성, 인터랙션 디자인, 디자인 도구',
  'developer': '웹 개발, Python, React, TypeScript, AI/ML 엔지니어링, DevOps, 아키텍처',
  'qa': '테스트 자동화, QA 프로세스, 성능 테스팅, AI 품질 평가, CI/CD',
}


def _load_state() -> dict[str, Any]:
  try:
    raw = _STATE_PATH.read_text(encoding='utf-8')
    data: dict[str, Any] = json.loads(raw)
    return data
  except Exception:
    return {'queries_today': {}, 'last_run': ''}


def _save_state(state: dict[str, Any]) -> None:
  try:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
  except Exception:
    logger.debug('trend_research state 저장 실패', exc_info=True)


def _pick_query(speaker_name: str, used_today: list[str]) -> str:
  bank = _QUERY_BANK.get(speaker_name, [])
  fresh = [q for q in bank if q not in used_today]
  if not fresh:
    return ''
  return random.choice(fresh)


async def _extract_insight(
  speaker_name: str, query: str, search_text: str,
) -> dict[str, Any] | None:
  '''Gemini로 검색 결과에서 적용 가능한 인사이트 추출. JSON 반환.

  스키마: {target_agent, headline, rule, evidence, source}
  '''
  prompt = (
    f'당신은 {display_name(speaker_name)}({speaker_name})입니다. '
    f'최근 트렌드를 조사해 우리 팀의 프롬프트를 보강하려 합니다.\n\n'
    f'[검색어] {query}\n\n'
    f'[웹 검색 결과 — DuckDuckGo]\n{search_text[:3000]}\n\n'
    f'[과제]\n'
    f'위 결과 중 우리 팀(팀장/기획/디자인/개발/QA — 한국어 AI 사무실)에 '
    f'**즉시 적용 가능한 구체 기법** 1가지를 골라 JSON으로 출력하세요.\n\n'
    f'[엄격 규칙]\n'
    f'- 추상적 일반론(예: "사용자 중심", "협업 강화") 금지 → null 출력\n'
    f'- 구체적 기법/도구/체크리스트만 (예: "WAI-ARIA live region 사용", "OpenTelemetry trace 주입")\n'
    f'- target_agent는 planner/designer/developer/qa 중 하나 (본인이거나 동료)\n'
    f'- rule은 한 문장 명령형, 50~120자\n'
    f'- evidence는 검색 결과의 어느 항목이 근거인지 1문장\n'
    f'- 적합한 인사이트가 없으면 null만 출력\n\n'
    f'[출력 — JSON만]\n'
    f'{{"target_agent":"...","headline":"한 줄 요약","rule":"...","evidence":"...","source":"검색결과 첫 항목 URL"}}\n'
    f'또는 null'
  )
  try:
    raw = await run_gemini(prompt=prompt, timeout=60.0)
  except Exception:
    logger.debug('trend insight LLM 실패', exc_info=True)
    return None
  text = raw.strip()
  if 'null' in text.lower()[:20] and '{' not in text[:20]:
    return None
  m = re.search(r'\{[\s\S]*?\}', text)
  if not m:
    return None
  try:
    parsed: dict[str, Any] = json.loads(m.group())
  except Exception:
    return None
  target = (parsed.get('target_agent') or '').strip()
  rule = (parsed.get('rule') or '').strip()
  if target not in ('planner', 'designer', 'developer', 'qa'):
    return None
  if len(rule) < 30 or len(rule) > 200:
    return None
  return parsed


def _register_rule(insight: dict[str, Any], speaker_name: str, query: str) -> str | None:
  '''PromptEvolver에 규칙 등록. 등록한 rule_id 반환.'''
  try:
    from improvement.prompt_evolver import PromptEvolver, PromptRule, MAX_RULES_PER_AGENT
  except Exception:
    logger.debug('PromptEvolver import 실패', exc_info=True)
    return None

  target = insight['target_agent']
  rule_text = insight['rule']
  evidence = (insight.get('evidence') or '')[:200]
  source = (insight.get('source') or '')[:200]
  now_iso = datetime.now(timezone.utc).isoformat()

  evolver = PromptEvolver()
  rules = evolver.load_rules(target)

  # 동일 본문 중복 차단
  if any(r.rule.strip() == rule_text.strip() for r in rules):
    return None

  rule_id = f'trend-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
  evidence_full = (
    f'트렌드 리서치 — {display_name(speaker_name)}이(가) "{query}" 검색 결과에서 도출. '
    f'근거: {evidence}'
    + (f' (출처: {source})' if source else '')
  )
  rules.append(PromptRule(
    id=rule_id,
    created_at=now_iso,
    source='trend_research',
    category='tech_trend',
    rule=rule_text,
    evidence=evidence_full,
    priority='medium',
    active=True,
  ))

  # 활성 규칙이 한도를 넘으면 hit_count 높은(효과 낮은) 순서로 비활성화
  active = [r for r in rules if r.active]
  inactive = [r for r in rules if not r.active]
  if len(active) > MAX_RULES_PER_AGENT:
    sorted_rules = sorted(active, key=lambda r: (r.hit_count, r.created_at))
    for r in sorted_rules[MAX_RULES_PER_AGENT:]:
      r.active = False
    rules = sorted_rules + inactive
  else:
    rules = active + inactive
  evolver.save_rules(target, rules)
  return rule_id


async def maybe_research(office: Any, speaker_name: str) -> bool:
  '''트렌드 리서치 1회 시도. 성공 시 True.

  - 같은 날 동일 검색어 중복 방지
  - 결과 없거나 인사이트 추출 실패하면 조용히 False
  '''
  if speaker_name not in _QUERY_BANK:
    return False

  state = _load_state()
  today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
  queries_today: dict[str, list[str]] = state.get('queries_today', {})
  if state.get('last_run', '')[:10] != today:
    queries_today = {}  # 날짜 바뀌면 리셋
  used = queries_today.get(speaker_name, [])
  query = _pick_query(speaker_name, used)
  if not query:
    return False

  try:
    from harness.file_reader import web_search
  except Exception:
    return False

  try:
    search_text = await __import__('asyncio').to_thread(web_search, query, 5)
  except Exception:
    logger.debug('web_search 실패: %s', query, exc_info=True)
    return False
  if not search_text or len(search_text) < 80:
    return False

  insight = await _extract_insight(speaker_name, query, search_text)

  # 사용 기록은 인사이트 유무와 무관하게 마킹 (같은 검색어 반복 방지)
  used.append(query)
  queries_today[speaker_name] = used[-10:]
  state['queries_today'] = queries_today
  state['last_run'] = datetime.now(timezone.utc).isoformat()
  _save_state(state)

  if not insight:
    return False

  rule_id = _register_rule(insight, speaker_name, query)
  if not rule_id:
    return False

  target = insight['target_agent']
  headline = (insight.get('headline') or '').strip() or insight['rule'][:60]
  target_label = '본인' if target == speaker_name else display_name(target)
  message = (
    f'🔎 트렌드 리서치 — "{query}" 결과 공유.\n'
    f'적용할 만한 기법: {headline}\n'
    f'→ {target_label} 프롬프트 규칙으로 등록 (rule {rule_id}).'
  )
  try:
    # autonomous_mode='trend_research' 태깅 — suggestion_filer 3종 모두 skip.
    # 이 발화는 이미 PromptEvolver에 규칙을 등록했으므로 다시 건의로 올릴 필요 없음.
    await office.event_bus.publish(LogEvent(
      agent_id=speaker_name, event_type='autonomous', message=message,
      data={'autonomous_mode': 'trend_research', 'rule_id': rule_id, 'target': target},
    ))
  except Exception:
    logger.debug('트렌드 발화 publish 실패', exc_info=True)

  try:
    await office.event_bus.publish(LogEvent(
      agent_id='system', event_type='system_notice',
      message=f'📚 프롬프트 규칙 추가 — {display_name(target)} ({rule_id}, source=trend_research)',
    ))
  except Exception:
    pass

  logger.info(
    'trend_research: %s → %s 규칙 등록 (%s, query="%s")',
    speaker_name, target, rule_id, query,
  )
  return True


# ── 토론형 리서치 (경로 B) ──────────────────────────────────────

def _fetch_rss_items(max_items: int = 8) -> list[dict[str, str]]:
  '''공개 RSS 피드에서 최근 아이템을 가져온다. 네트워크 실패 시 빈 리스트.'''
  import urllib.request
  items: list[dict[str, str]] = []
  feeds = random.sample(_RSS_FEEDS, min(2, len(_RSS_FEEDS)))
  for feed in feeds:
    try:
      req = urllib.request.Request(feed['url'], headers={
        'User-Agent': 'Mozilla/5.0 (compatible; AI-Office/1.0)',
      })
      with urllib.request.urlopen(req, timeout=10) as resp:
        xml = resp.read().decode('utf-8', errors='replace')
      # 간이 XML 파싱 — <item><title>...</title><link>...</link><description>...</description>
      import re as _rss_re
      for m in _rss_re.finditer(
        r'<item[^>]*>.*?<title[^>]*>(.*?)</title>.*?'
        r'<link[^>]*>([^<]*)</link>.*?'
        r'(?:<description[^>]*>(.*?)</description>)?.*?</item>',
        xml, _rss_re.DOTALL,
      ):
        title = _rss_re.sub(r'<!\[CDATA\[|\]\]>|<[^>]+>', '', m.group(1)).strip()
        link = m.group(2).strip()
        desc = _rss_re.sub(r'<!\[CDATA\[|\]\]>|<[^>]+>', '', m.group(3) or '').strip()[:200]
        if title:
          items.append({'title': title, 'link': link, 'desc': desc, 'source': feed['name']})
        if len(items) >= max_items:
          break
    except Exception:
      logger.debug('RSS 피드 실패: %s', feed['name'], exc_info=True)
  return items


async def _generate_dynamic_query(speaker_name: str, used_today: list[str]) -> str:
  '''Gemini에게 오늘 검색할 만한 주제를 동적으로 생성하게 한다.'''
  domain = _DOMAIN_HINTS.get(speaker_name, '기술 전반')
  used_hint = ', '.join(used_today[-5:]) if used_today else '없음'
  try:
    raw = await run_gemini(
      prompt=(
        f'당신은 {display_name(speaker_name)}의 관심 영역을 아는 리서치 봇입니다.\n'
        f'전문 영역: {domain}\n'
        f'오늘 이미 검색한 주제: {used_hint}\n\n'
        f'[과제] 위 영역에서 2026년 현재 가장 화제가 되는 구체적 기술/도구/사건을 '
        f'DuckDuckGo 검색어 1개로 출력하세요.\n\n'
        f'[규칙]\n'
        f'- 영어 또는 한국어 검색어 1개만 (따옴표 없이)\n'
        f'- 추상적 주제("AI trends") 금지. 구체적 도구/사건/기업명 포함\n'
        f'- 이미 검색한 주제와 겹치지 않게\n'
        f'- 10~50자\n\n'
        f'검색어:'
      ),
      timeout=30.0,
    )
    query = raw.strip().split('\n')[0].strip().strip('"\'')
    if 10 <= len(query) <= 80 and query not in used_today:
      return query
  except Exception:
    logger.debug('동적 검색어 생성 실패: %s', speaker_name, exc_info=True)
  return ''


async def _summarize_for_discussion(
  speaker_name: str, raw_material: str, source_type: str,
) -> str | None:
  '''검색/RSS 원본에서 토론할 만한 소식 1건을 요약. 토론 주제 문자열 반환.'''
  prompt = (
    f'당신은 IT/기술 뉴스 큐레이터입니다.\n\n'
    f'[{source_type} 결과]\n{raw_material[:4000]}\n\n'
    f'[과제]\n'
    f'위 내용 중 소프트웨어 개발팀(기획/디자인/개발/QA)이 토론할 만한 '
    f'가장 흥미롭고 구체적인 소식 1건을 골라 요약하세요.\n\n'
    f'[출력 형식 — 이 구조 정확히 따르기]\n'
    f'📰 [소식 제목 — 구체적 도구/기업/기술명 포함]\n'
    f'핵심: (무슨 일이 일어났는지 2-3문장)\n'
    f'출처: (URL 또는 매체명)\n'
    f'토론 포인트: (팀이 논의할 만한 질문 1개)\n\n'
    f'[규칙]\n'
    f'- 추상적 트렌드 요약 금지. 구체적 사건/출시/발표/연구 결과 1건만.\n'
    f'- 흥미로운 소식이 없으면 null만 출력\n'
    f'- 토론 포인트는 "우리 팀에 이걸 적용하면?", "이게 기존 방식을 대체할까?" 같은 실질적 질문'
  )
  try:
    raw = await run_gemini(prompt=prompt, timeout=60.0)
    text = raw.strip()
    if 'null' in text.lower()[:20] and '📰' not in text[:20]:
      return None
    if len(text) < 50:
      return None
    return text
  except Exception:
    logger.debug('토론 주제 요약 실패', exc_info=True)
    return None


async def research_for_discussion(speaker_name: str) -> str | None:
  '''토론용 외부 동향 주제를 가져온다. 성공 시 토론 주제 문자열 반환.

  소스 전략 (랜덤 혼합):
    - 50%: 동적 검색어 생성 → DuckDuckGo 검색
    - 30%: RSS 피드 파싱
    - 20%: 고정 검색어 뱅크 (기존 호환)
  '''
  if speaker_name not in _DOMAIN_HINTS:
    return None

  state = _load_state()
  today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
  queries_today: dict[str, list[str]] = state.get('queries_today', {})
  if state.get('last_run', '')[:10] != today:
    queries_today = {}
  used = queries_today.get(speaker_name, [])

  raw_material = ''
  source_type = ''
  query_used = ''

  roll = random.random()

  if roll < 0.50:
    # 경로 1: 동적 검색어 → DuckDuckGo
    import asyncio as _aio
    query = await _generate_dynamic_query(speaker_name, used)
    if query:
      try:
        from harness.file_reader import web_search
        raw_material = await _aio.to_thread(web_search, query, 5)
        source_type = f'웹 검색 — "{query}"'
        query_used = query
      except Exception:
        logger.debug('동적 검색 실패: %s', query, exc_info=True)

  elif roll < 0.80:
    # 경로 2: RSS 피드
    import asyncio as _aio
    try:
      items = await _aio.to_thread(_fetch_rss_items, 8)
    except Exception:
      logger.debug('RSS 피드 전체 실패', exc_info=True)
      items = []
    if items:
      lines = [f'- [{it["source"]}] {it["title"]}: {it["desc"]}' for it in items]
      raw_material = '\n'.join(lines)
      source_type = 'RSS 피드 (Hacker News, TechCrunch 등)'
      query_used = f'rss-{today}'

  else:
    # 경로 3: 기존 고정 뱅크
    query = _pick_query(speaker_name, used)
    if query:
      try:
        import asyncio as _aio
        from harness.file_reader import web_search
        raw_material = await _aio.to_thread(web_search, query, 5)
        source_type = f'웹 검색 — "{query}"'
        query_used = query
      except Exception:
        logger.debug('고정 뱅크 검색 실패: %s', query, exc_info=True)

  if not raw_material or len(raw_material) < 80:
    return None

  # 사용 기록
  if query_used and query_used not in used:
    used.append(query_used)
    queries_today[speaker_name] = used[-15:]
    state['queries_today'] = queries_today
    state['last_run'] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

  # Gemini로 토론 주제 요약
  try:
    discussion_topic = await _summarize_for_discussion(speaker_name, raw_material, source_type)
  except Exception:
    logger.debug('_summarize_for_discussion 예외', exc_info=True)
    discussion_topic = None
  if not discussion_topic:
    return None

  logger.info('research_for_discussion: %s → 토론 주제 확보 (source=%s)', speaker_name, source_type)
  return discussion_topic
