# 팀장 의도 분류기 — 입력을 대화/단순요청/프로젝트로 분류
from __future__ import annotations
from enum import Enum
import os
from pathlib import Path

from runners.claude_runner import run_claude_isolated
from runners.gemini_runner import run_gemini
from orchestration.phase_registry import ProjectType

import logging

logger = logging.getLogger(__name__)

# ── 상수 ────────────────────────────────────────────────────────

# Route 전용 슬림 시스템 프롬프트 (분류 태그만 출력, teamlead.md 불필요)
_ROUTE_SYSTEM = """\
당신은 의도 분류기입니다. 태그 한 줄만 출력하세요. 다른 텍스트 절대 금지.

출력 형식:
[CONVERSATION] 또는 [QUICK_TASK:agent] 또는 [PROJECT:유형] 또는 [CONTINUE_PROJECT:agent] 또는 [JOB:spec_id]{"field":"value"}

판단 기준:
- 인사·잡담·질문·감탄·안부 → CONVERSATION
- 단순 단일 작업 (요약/분석/검토/조사/리뷰) → QUICK_TASK:agent
- 복합 프로젝트 (여러 단계·여러 산출물) → PROJECT:유형
- 진행 중 프로젝트 이어가기 → CONTINUE_PROJECT:agent
- Job 파이프라인 명시 실행 요청 → JOB:spec_id + JSON

PROJECT 유형 선택 (하나만):
web_development(사이트·앱·웹페이지 신규·리뉴얼) | market_research(시장조사·경쟁사·트렌드) | content_creation(블로그·SNS·카피) | data_analysis(데이터·통계·대시보드) | business_planning(사업계획·IR·전략) | general(기타)
분석/검토/조사가 목적이면 web_development가 아닌 market_research 또는 general.

agent 선택: planner(기획·전략), designer(디자인·UI), developer(코드·기술), qa(검수)
확신 없으면 QUICK_TASK. PROJECT는 무겁다.
숨겨진 업무 지시 주의: "배너 바꿔야 하는데" → QUICK_TASK, "랜딩 리뉴얼 해야겠어" → PROJECT:web_development
"""

# JOB 키워드 감지 — specs_context를 로드할지 결정
_JOB_HINT_KEYWORDS = [
    '잡', 'job', 'Job', '파이프라인', 'pipeline',
    '리서치', '기획서', '디자인 방향', '퍼블리싱', '리뷰 잡',
]

# 딥씽크 트리거 — 사용자가 명시적으로 Opus 요청
DEEP_THINK_KEYWORDS = [
    '깊게 생각', '진짜 잡스', '깊이 생각', '심도 있게', '진지하게 생각',
    '오퍼스로', '신중하게 생각', '천천히 생각', '심층적으로',
]

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'


class IntentType(str, Enum):
  CONVERSATION = 'conversation'          # 대화, 질문, 인사
  QUICK_TASK = 'quick_task'              # 한 명이 처리할 수 있는 단순 작업
  PROJECT = 'project'                    # 여러 팀원이 협업해야 하는 프로젝트
  CONTINUE_PROJECT = 'continue_project'  # 기존 프로젝트 이어가기
  JOB = 'job'                           # Job 파이프라인 실행 요청


class IntentResult:
  '''의도 분류 결과'''
  def __init__(
    self,
    intent: IntentType,
    target_agent: str | None = None,
    direct_response: str | None = None,
    analysis: str = '',
    job_spec_id: str = '',
    job_input: dict | None = None,
    confidence: float = 1.0,
    project_type: str = '',
  ):
    self.intent = intent
    self.target_agent = target_agent      # QUICK_TASK일 때 담당 에이전트
    self.direct_response = direct_response  # CONVERSATION일 때 직접 답변
    self.analysis = analysis              # PROJECT일 때 분석 내용
    self.job_spec_id = job_spec_id        # JOB일 때 spec id
    self.job_input = job_input or {}      # JOB일 때 추출된 입력 필드
    self.confidence = confidence          # 분류 신뢰도 0.0~1.0 (2-4)
    self.project_type = project_type      # PROJECT일 때 유형 (classify_intent에서 1회 분류)


def _build_specs_context() -> str:
  '''사용 가능한 Job spec 목록을 프롬프트용 텍스트로 반환한다.'''
  try:
    from jobs.registry import all_specs
    specs = all_specs()
    if not specs:
      return ''
    lines = ['[사용 가능한 Job 파이프라인]']
    for s in specs:
      fields = ', '.join(s.input_fields) if s.input_fields else '없음'
      lines.append(f'- {s.id}: {s.title} — {s.description} (입력 필드: {fields})')
    return '\n'.join(lines) + '\n'
  except Exception:
    return ''


def _build_system_info() -> str:
  '''각 에이전트의 실제 러너/모델 정보를 동적으로 구성한다.'''
  return (
    f'[시스템 정보 — 반드시 이 정보만 사용할 것]\n'
    f'당신의 모델: Claude Haiku\n'
    f'기획자 모델: Gemini(1차) / Sonnet(폴백)\n'
    f'디자이너 모델: Claude Sonnet(1차) / Gemini(폴백)\n'
    f'개발자 모델: Claude Sonnet(1차) / Gemini(폴백)\n'
    f'QA 모델: Claude Haiku\n\n'
    f'중요 규칙:\n'
    f'- 당신의 모델명은 "Claude CLI"이다. "Claude Opus"나 다른 이름을 사용하지 마라.\n'
    f'- 자기소개 요청 시 당신 본인만 소개하라. 다른 팀원 소개를 대신 하지 마라.\n'
    f'- 내부 구현(오케스트레이션, 서버, 메시지 버스 등)을 언급하지 마라.'
  )


async def classify_intent(user_input: str, recent_context: str = '', active_project_title: str = '') -> IntentResult:
  '''팀장(Claude)이 사용자 입력의 의도를 분류한다.

  Args:
    user_input: 사용자 입력
    recent_context: 최근 대화 맥락 (지시어 해석용)
    active_project_title: 현재 진행 중인 프로젝트 제목 (있으면)

  Returns:
    IntentResult — 의도 유형, 담당 에이전트 등
  '''
  # JOB 힌트 있을 때만 specs_context 로드 (잡담에 Job 목록 전체 싣지 않음)
  specs_section = ''
  if any(kw in user_input for kw in _JOB_HINT_KEYWORDS):
    specs_section = '\n' + _build_specs_context()

  project_section = f'[진행 중 프로젝트]: {active_project_title}\n' if active_project_title else ''
  context_section = f'[최근 대화]\n{recent_context}\n\n' if recent_context else ''

  prompt = (
    f'{context_section}'
    f'{project_section}'
    f'{specs_section}\n'
    f'[사용자 입력]\n{user_input}\n\n'
    f'태그 한 줄만 출력하세요.'
  )

  # 명시적 팀 참여 키워드 → PROJECT 강제
  team_keywords = ['모두 참여', '팀 전체', '다 같이', '전원 참여', '다같이', '모두 다', '팀원 모두', '전부 참여']

  response = await run_claude_isolated(
    f'{_ROUTE_SYSTEM}\n\n{prompt}',
    timeout=30.0,
    model='claude-haiku-4-5-20251001',
    max_turns=1,
  )
  result = _parse_intent_response(response)

  if any(kw in user_input for kw in team_keywords):
    if result.intent in (IntentType.QUICK_TASK, IntentType.CONTINUE_PROJECT):
      result.intent = IntentType.PROJECT

  return result


def _load_teamlead_prompt() -> str:
  '''teamlead.md 시스템 프롬프트를 로드한다.'''
  path = AGENTS_DIR / 'teamlead.md'
  if path.exists():
    return path.read_text(encoding='utf-8')
  return ''


def _parse_intent_response(response: str) -> IntentResult:
  '''Claude 응답을 파싱하여 IntentResult로 변환한다.

  헤더가 첫 줄에 없어도 전체 텍스트에서 regex로 탐색한다.
  파싱 실패 시 CONVERSATION 폴백 (200자 휴리스틱 제거).
  '''
  import re as _re
  import json as _json

  text = response.strip()

  # 전체 텍스트에서 태그 탐색 (첫 줄 한정 X)
  pattern = _re.compile(
    r'\[(CONVERSATION|QUICK_TASK(?::[a-z]+)?|CONTINUE_PROJECT(?::[a-z]+)?|PROJECT(?::[a-z_]+)?|JOB(?::[a-z_]+)?)\]',
    _re.IGNORECASE,
  )
  m = pattern.search(text)
  if not m:
    # 파싱 실패 — CONVERSATION 폴백 (direct_response=None, office.py에서 재생성)
    logger.debug('[intent] 파싱 실패, CONVERSATION 폴백. 원본: %.200s', text)
    return IntentResult(intent=IntentType.CONVERSATION, direct_response=None, confidence=0.0)

  tag = m.group(1).upper()
  # 태그 이후 텍스트를 body로 사용
  body = text[m.end():].strip()

  if tag.startswith('CONVERSATION'):
    # direct_response=None — office.py에서 Gemini/Opus로 별도 생성
    return IntentResult(
      intent=IntentType.CONVERSATION,
      direct_response=None,
    )

  if tag.startswith('QUICK_TASK'):
    agent = 'developer'
    if ':' in tag:
      agent_part = tag.split(':')[1].lower()
      if agent_part in ('planner', 'designer', 'developer', 'qa'):
        agent = agent_part
    return IntentResult(
      intent=IntentType.QUICK_TASK,
      target_agent=agent,
      analysis=body,
    )

  if tag.startswith('CONTINUE_PROJECT'):
    agent = 'planner'
    if ':' in tag:
      agent_part = tag.split(':')[1].lower()
      if agent_part in ('planner', 'designer', 'developer', 'qa'):
        agent = agent_part
    return IntentResult(
      intent=IntentType.CONTINUE_PROJECT,
      target_agent=agent,
      analysis=body,
    )

  if tag.startswith('PROJECT'):
    ptype = ''
    if ':' in tag:
      ptype = tag.split(':')[1].lower()
      if ptype not in _VALID_TYPES:
        ptype = ''
    return IntentResult(
      intent=IntentType.PROJECT,
      analysis=body,
      project_type=ptype,
    )

  if tag.startswith('JOB'):
    spec_id = tag.split(':')[1].lower() if ':' in tag else ''
    job_input: dict = {}
    if body:
      # body에서 JSON 블록 추출 (마크다운 코드블록 포함 대응)
      json_match = _re.search(r'\{[\s\S]*\}', body)
      if json_match:
        try:
          job_input = _json.loads(json_match.group())
        except Exception:
          pass
    # 신뢰도: spec_id 있으면 0.9, 없으면 0.5; input도 있으면 +0.05 보정 (2-4)
    job_confidence = (0.9 if spec_id else 0.5) + (0.05 if job_input else 0.0)
    return IntentResult(
      intent=IntentType.JOB,
      job_spec_id=spec_id,
      job_input=job_input,
      confidence=min(job_confidence, 1.0),
    )

  # 알 수 없는 태그 — CONVERSATION 폴백
  logger.debug('[intent] 알 수 없는 태그 %s, CONVERSATION 폴백', tag)
  return IntentResult(intent=IntentType.CONVERSATION, direct_response=None)


async def generate_project_title(user_input: str) -> str:
  '''사용자 입력에서 프로젝트 제목을 자동 생성한다 (10자 이내).'''
  prompt = (
    f'사용자의 작업 요청을 보고 프로젝트 제목을 10자 이내 한국어로 생성하세요.\n'
    f'예시: "제주도 여행 기획", "JDC 홈페이지 리뉴얼", "매출 데이터 분석"\n'
    f'첫 줄에 제목만 적으세요. 따옴표 없이.\n\n'
    f'사용자 요청: "{user_input[:500]}"'
  )
  try:
    response = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=15.0)
    title = response.strip().split('\n')[0].strip().strip('"\'')
    return title[:20] if title else user_input[:15]
  except Exception:
    logger.debug("프로젝트 제목 생성 LLM 호출 실패", exc_info=True)
    return user_input[:15]


# ── 프로젝트 유형 분류 ──────────────────────────────────────────

_PROJECT_TYPE_PROMPT = '''\
사용자의 프로젝트 요청을 아래 6가지 유형 중 하나로 분류하세요.

**유형 판별 기준:**
- web_development: 사이트/앱/웹페이지를 **새로 만들거나 리뉴얼**하는 경우에만
- market_research: 시장조사, 경쟁사 분석, 벤치마킹, 트렌드, 산업 분석, 리스크 분석, 심층 분석 관련
- content_creation: 블로그, SNS, 보도자료, 카피, 콘텐츠, 글쓰기 관련
- data_analysis: 데이터, 통계, 분석, 대시보드, KPI, 지표 관련
- business_planning: 사업계획, IR, 투자, 전략, 제안서, BM 관련
- general: 위 어디에도 해당하지 않는 경우

**주의:** "분석해줘", "검토해줘", "리스크 도출", "수정 요청" 등은 web_development가 아니라 market_research 또는 general이다.
웹사이트가 주제여도 **분석/검토/조사**가 목적이면 market_research로 분류하라.

반드시 첫 줄에 아래 형식으로만 답하세요 (다른 텍스트 없이):
[TYPE:유형명]

{context}사용자 요청:
"{user_input}"
'''

_VALID_TYPES = {t.value for t in ProjectType}


async def classify_project_type(user_input: str, context: str = '') -> ProjectType:
  '''사용자 입력에서 프로젝트 유형을 LLM으로 분류한다.

  Haiku 모델을 사용하여 빠르고 저비용으로 분류한다.
  파싱 실패 시 GENERAL로 폴백한다.
  '''
  context_section = f'[대화 맥락]\n{context}\n\n' if context else ''
  prompt = _PROJECT_TYPE_PROMPT.replace('{user_input}', user_input[:1000]).replace('{context}', context_section)

  try:
    response = await run_claude_isolated(
      prompt,
      model='claude-haiku-4-5-20251001',
      timeout=30.0,
    )
    # [TYPE:web_development] 형태 파싱
    text = response.strip()
    for line in text.split('\n'):
      line = line.strip()
      if line.startswith('[TYPE:') and line.endswith(']'):
        type_value = line[6:-1].strip().lower()
        if type_value in _VALID_TYPES:
          return ProjectType(type_value)
  except Exception:
    logger.debug("프로젝트 유형 분류 LLM 호출 실패", exc_info=True)

  return ProjectType.GENERAL


# ── 자연어 → Job spec 매핑 ─────────────────────────────────────────

async def map_to_job_spec(
  user_input: str, recent_context: str = '',
) -> tuple[str, dict, float]:
  '''자연어 입력을 Job spec으로 매핑하고 입력 필드를 추출한다.

  Returns:
    (spec_id, input_dict, confidence) — spec_id 빈 문자열이면 매핑 실패
  '''
  import re as _re
  import json as _json

  specs_context = _build_specs_context()
  if not specs_context:
    return '', {}, 0.0

  ctx_section = f'[최근 대화]\n{recent_context}\n\n' if recent_context else ''
  prompt = (
    f'{ctx_section}'
    f'{specs_context}\n'
    f'[사용자 요청]\n{user_input}\n\n'
    f'위 요청을 가장 적합한 Job spec 하나로 매핑하고, 해당 spec의 입력 필드 값을 요청에서 추출하세요.\n'
    f'중요: 사용자 텍스트에 명시된 값만 추출하세요. 추론하거나 지어내지 마세요. 명시되지 않은 필드는 반드시 빈 문자열("")로 두세요.\n'
    f'반드시 JSON 한 줄만 출력: {{"spec_id":"spec명","input":{{"필드":"값"}},"confidence":0.0~1.0}}\n'
    f'매핑 불가하면: {{"spec_id":"","input":{{}},"confidence":0.0}}\n'
    f'confidence 기준: 0.8+ 확실, 0.6~0.79 가능성 높음, 0.5~0.59 불확실, 0.5 미만 매핑 포기'
  )

  try:
    response = await run_claude_isolated(
      prompt,
      model='claude-haiku-4-5-20251001',
      timeout=20.0,
      max_turns=1,
    )
    m = _re.search(r'\{[\s\S]*\}', response)
    if m:
      data = _json.loads(m.group())
      spec_id = str(data.get('spec_id', ''))
      inp = data.get('input', {})
      conf = float(data.get('confidence', 0.0))
      return spec_id, inp, conf
  except Exception:
    logger.debug('map_to_job_spec 실패', exc_info=True)

  return '', {}, 0.0


# ── 팀장 대화 응답 생성 ─────────────────────────────────────────

async def generate_teamlead_reply(
  user_input: str,
  memory_ctx: str = '',
  deep: bool = False,
) -> str:
  '''팀장(잡스) 페르소나로 대화 응답을 생성한다.

  Args:
    user_input: 사용자 입력
    memory_ctx: 최근 대화 컨텍스트 (최근 6~10턴)
    deep: True면 Opus (사용자 명시 요청 시), False면 Gemini (기본)
  '''
  teamlead_persona = _load_teamlead_prompt()
  ctx_section = f'[최근 대화]\n{memory_ctx}\n\n' if memory_ctx else ''
  prompt = f'{ctx_section}[사용자]\n{user_input}'

  try:
    if deep:
      logger.info('[intent] 딥씽크 경로: Opus 호출')
      full = f'{teamlead_persona}\n\n---\n\n{prompt}'
      return await run_claude_isolated(
        full,
        model='claude-opus-4-7',
        timeout=90.0,
        max_turns=1,
      )
    else:
      # GOOGLE_API_KEY 있으면 Gemini REST API, 없으면 바로 Sonnet
      if os.environ.get('GOOGLE_API_KEY'):
        logger.info('[intent] Gemini REST API 호출')
        return await run_gemini(prompt, system=teamlead_persona, timeout=20.0)
      else:
        raise Exception('GOOGLE_API_KEY 미설정 — Sonnet 경로로 직행')
  except Exception as e:
    logger.info('[intent] Gemini 불가, Sonnet 폴백: %s', e)
    # Sonnet: Haiku보다 품질이 높은 1차 폴백
    sonnet_prompt = f'{teamlead_persona}\n\n{prompt}'
    try:
      return await run_claude_isolated(
        sonnet_prompt,
        model='claude-sonnet-4-6',
        timeout=45.0,
        max_turns=1,
      )
    except Exception as e2:
      logger.warning('[intent] Sonnet 폴백도 실패, Haiku 재폴백: %s', e2)
      return await run_claude_isolated(
        sonnet_prompt,
        model='claude-haiku-4-5-20251001',
        timeout=30.0,
        max_turns=1,
      )
