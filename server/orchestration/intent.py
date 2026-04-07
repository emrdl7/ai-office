# 팀장 의도 분류기 — 입력을 대화/단순요청/프로젝트로 분류
from __future__ import annotations
from enum import Enum
from pathlib import Path

from runners.claude_runner import run_claude_isolated

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'


class IntentType(str, Enum):
  CONVERSATION = 'conversation'  # 대화, 질문, 인사
  QUICK_TASK = 'quick_task'      # 한 명이 처리할 수 있는 단순 작업
  PROJECT = 'project'            # 여러 팀원이 협업해야 하는 프로젝트


class IntentResult:
  '''의도 분류 결과'''
  def __init__(
    self,
    intent: IntentType,
    target_agent: str | None = None,
    direct_response: str | None = None,
    analysis: str = '',
  ):
    self.intent = intent
    self.target_agent = target_agent      # QUICK_TASK일 때 담당 에이전트
    self.direct_response = direct_response  # CONVERSATION일 때 직접 답변
    self.analysis = analysis              # PROJECT일 때 분석 내용


async def classify_intent(user_input: str) -> IntentResult:
  '''팀장(Claude)이 사용자 입력의 의도를 분류한다.

  Returns:
    IntentResult — 의도 유형, 담당 에이전트, 직접 답변 등
  '''
  teamlead_prompt = _load_teamlead_prompt()

  prompt = (
    f'{teamlead_prompt}\n\n'
    f'---\n\n'
    f'사용자가 다음과 같이 말했습니다:\n\n'
    f'"{user_input}"\n\n'
    f'당신은 팀장입니다. 이 입력을 보고 어떻게 대응할지 판단하세요.\n\n'
    f'반드시 아래 형식으로 첫 줄에 판단을 적고, 그 아래에 내용을 적으세요:\n\n'
    f'[CONVERSATION]\n직접 답변 내용\n\n'
    f'또는:\n\n'
    f'[QUICK_TASK:에이전트명]\n작업 지시 내용\n\n'
    f'또는:\n\n'
    f'[PROJECT]\n프로젝트 분석 내용\n\n'
    f'에이전트명은 planner, designer, developer, qa 중 하나입니다.\n'
    f'간단한 대화나 질문이면 CONVERSATION, '
    f'한 명이 처리할 수 있으면 QUICK_TASK, '
    f'여러 팀원이 필요하면 PROJECT입니다.'
  )

  response = await run_claude_isolated(prompt, timeout=120.0)
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

  if header.startswith('[CONVERSATION]'):
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

  if header.startswith('[PROJECT]'):
    return IntentResult(
      intent=IntentType.PROJECT,
      analysis=body,
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
