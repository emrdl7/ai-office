# 팀장 의도 분류기 — 입력을 대화/단순요청/프로젝트로 분류
from __future__ import annotations
from enum import Enum
from pathlib import Path

from runners.claude_runner import run_claude_isolated
from orchestration.phase_registry import ProjectType

import logging

logger = logging.getLogger(__name__)

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
  ):
    self.intent = intent
    self.target_agent = target_agent      # QUICK_TASK일 때 담당 에이전트
    self.direct_response = direct_response  # CONVERSATION일 때 직접 답변
    self.analysis = analysis              # PROJECT일 때 분석 내용
    self.job_spec_id = job_spec_id        # JOB일 때 spec id
    self.job_input = job_input or {}      # JOB일 때 추출된 입력 필드


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
    IntentResult — 의도 유형, 담당 에이전트, 직접 답변 등
  '''
  teamlead_prompt = _load_teamlead_prompt()
  system_info = _build_system_info()
  specs_context = _build_specs_context()

  context_section = ''
  if recent_context:
    context_section = (
      f'[최근 대화 맥락]\n{recent_context}\n\n'
      f'위 맥락을 고려하여 판단하세요:\n'
      f'- 이전 작업 결과에 대한 후속 질문/수정 요청 → QUICK_TASK (예: "아까 거 수정해줘", "그거 다시 해봐")\n'
      f'- 대화 중 주제가 업무로 전환됨 → QUICK_TASK 또는 PROJECT (예: "아 그건 그렇고, 사이트 색상 바꿔줘")\n'
      f'- 이전 대화의 연장선상 잡담/안부 → CONVERSATION\n'
      f'- 완전히 새로운 큰 주제 요청 → PROJECT\n\n'
    )
  if active_project_title:
    context_section += f'[현재 진행 중인 프로젝트: {active_project_title}]\n\n'

  prompt = (
    f'{teamlead_prompt}\n\n'
    f'{system_info}\n\n'
    f'{specs_context}\n'
    f'---\n\n'
    f'{context_section}'
    f'사용자가 다음과 같이 말했습니다:\n\n'
    f'"{user_input}"\n\n'
    f'당신은 팀장입니다. 이 입력을 보고 어떻게 대응할지 판단하세요.\n\n'
    f'반드시 아래 형식으로 첫 줄에 판단을 적고, 그 아래에 내용을 적으세요:\n\n'
    f'[CONVERSATION]\n직접 답변 내용\n\n'
    f'또는:\n\n'
    f'[QUICK_TASK:에이전트명]\n작업 지시 내용\n\n'
    f'또는:\n\n'
    f'[PROJECT]\n프로젝트 분석 내용\n\n'
    f'또는 (진행 중인 프로젝트와 연관된 추가 작업 요청일 때):\n\n'
    f'[CONTINUE_PROJECT:에이전트명]\n이어서 할 작업 내용\n\n'
    f'또는 (Job 파이프라인 실행 요청일 때):\n\n'
    f'[JOB:spec_id]\n{{"field1":"값1","field2":"값2"}}\n\n'
    f'에이전트명은 planner, designer, developer, qa 중 하나입니다.\n'
    f'간단한 대화나 질문이면 CONVERSATION, '
    f'한 명이 처리할 수 있는 새 작업이면 QUICK_TASK, '
    f'여러 팀원이 협업하여 산출물을 만들어야 하는 새 프로젝트면 PROJECT, '
    f'진행 중인 프로젝트에 대한 추가 지시이면 CONTINUE_PROJECT, '
    f'Job 파이프라인 실행 요청이면 JOB입니다.\n\n'
    f'**JOB 판단 기준:**\n'
    f'- "잡 만들어줘", "잡 돌려줘", "파이프라인 실행해", "Job 생성해줘" 등 명시적 요청\n'
    f'- 위 Job 파이프라인 목록 중 하나와 정확히 맞아떨어지는 작업\n'
    f'- JOB 선택 시 spec_id는 목록의 id 값 그대로, body는 입력 필드를 JSON으로\n'
    f'- 필수 필드(topic 등)는 사용자 메시지에서 추출, 선택 필드는 적절히 추론\n\n'
    f'**QUICK_TASK vs PROJECT 판단 기준:**\n'
    f'- 리뷰, 분석, 조사, 검토, 평가, 요약 → QUICK_TASK (산출물이 문서 1개)\n'
    f'- 코드 리뷰, GitHub 저장소 분석, 기술 검토 → QUICK_TASK:developer\n'
    f'- 기획 리뷰, 전략 분석, 시장 조사 → QUICK_TASK:planner\n'
    f'- 디자인 리뷰, UI/UX 분석 → QUICK_TASK:designer\n'
    f'- 잘 모르겠으면 내용을 보고 가장 적합한 에이전트를 선택하라\n'
    f'- 사이트 제작, 리뉴얼, 여러 산출물이 필요한 작업 → PROJECT\n'
    f'- 확신이 안 서면 QUICK_TASK를 선택하라. PROJECT는 무겁다.\n\n'
    f'**중요: 일상 대화 속 숨겨진 업무 지시를 놓치지 마라**\n'
    f'- "아 맞다 그 사이트 배너 좀 바꿔야 하는데" → QUICK_TASK\n'
    f'- "점심 먹으면서 생각했는데 랜딩페이지 리뉴얼 해야 할 것 같아" → PROJECT\n'
    f'- "그거 조사 좀 해봐" → QUICK_TASK\n'
    f'- "~해줘/해주세요/만들어/수정해/바꿔/분석해/검토해" 등 동사가 있으면 업무 가능성이 높다\n'
    f'- 반대로, 감탄/인사/질문/잡담만 있으면 CONVERSATION이다'
  )

  # 명시적 팀 참여 키워드 → 무조건 PROJECT (LLM 판단보다 우선)
  team_keywords = ['모두 참여', '팀 전체', '다 같이', '전원 참여', '다같이', '모두 다', '팀원 모두', '전부 참여']
  if any(kw in user_input for kw in team_keywords):
    response = await run_claude_isolated(prompt, timeout=60.0, model='claude-haiku-4-5-20251001')
    result = _parse_intent_response(response)
    # QUICK_TASK였어도 PROJECT로 강제 승격
    if result.intent in (IntentType.QUICK_TASK, IntentType.CONTINUE_PROJECT):
      result.intent = IntentType.PROJECT
    return result

  response = await run_claude_isolated(prompt, timeout=60.0, model='claude-haiku-4-5-20251001')
  return _parse_intent_response(response)


def _load_teamlead_prompt() -> str:
  '''teamlead.md 시스템 프롬프트를 로드한다.'''
  path = AGENTS_DIR / 'teamlead.md'
  if path.exists():
    return path.read_text(encoding='utf-8')
  return ''


def _parse_intent_response(response: str) -> IntentResult:
  '''Claude 응답을 파싱하여 IntentResult로 변환한다.'''
  text = response.strip()
  lines = text.split('\n', 1)
  header = lines[0].strip()
  body = lines[1].strip() if len(lines) > 1 else ''

  if header.startswith('[CONVERSATION'):
    return IntentResult(
      intent=IntentType.CONVERSATION,
      direct_response=body or text,
    )

  if header.startswith('[QUICK_TASK'):
    # [QUICK_TASK:developer] 형태에서 에이전트명 추출
    agent = 'developer'
    if ':' in header:
      agent_part = header.split(':')[1].strip().rstrip(']')
      if agent_part in ('planner', 'designer', 'developer', 'qa'):
        agent = agent_part
    return IntentResult(
      intent=IntentType.QUICK_TASK,
      target_agent=agent,
      analysis=body,
    )

  if header.startswith('[CONTINUE_PROJECT'):
    agent = 'planner'
    if ':' in header:
      agent_part = header.split(':')[1].strip().rstrip(']')
      if agent_part in ('planner', 'designer', 'developer', 'qa'):
        agent = agent_part
    return IntentResult(
      intent=IntentType.CONTINUE_PROJECT,
      target_agent=agent,
      analysis=body,
    )

  if header.startswith('[PROJECT]'):
    return IntentResult(
      intent=IntentType.PROJECT,
      analysis=body,
    )

  if header.startswith('[JOB'):
    import json as _json
    spec_id = ''
    if ':' in header:
      spec_id = header.split(':')[1].strip().rstrip(']').strip()
    job_input: dict = {}
    if body:
      try:
        job_input = _json.loads(body)
      except Exception:
        pass
    return IntentResult(
      intent=IntentType.JOB,
      job_spec_id=spec_id,
      job_input=job_input,
    )


  # 파싱 실패 시 기본값: 내용이 짧으면 대화, 길면 프로젝트
  if len(text) < 200:
    return IntentResult(
      intent=IntentType.CONVERSATION,
      direct_response=text,
    )
  return IntentResult(
    intent=IntentType.PROJECT,
    analysis=text,
  )


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
