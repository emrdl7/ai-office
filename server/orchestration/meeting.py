# 회의 시스템 — 실제 대화처럼 주고받는 회의
import re
from dataclasses import dataclass

from orchestration.agent import Agent
from log_bus.event_bus import EventBus, LogEvent
from runners.claude_runner import run_claude_isolated
import logging

logger = logging.getLogger(__name__)


@dataclass
class MeetingRecord:
  '''회의 발언 기록'''
  speaker: str
  content: str
  round: int


# 에이전트 멘션 매핑 — 한국어/영어/미생 캐릭터명 모두 인식
MENTION_MAP: dict[str, str] = {
  # 팀장 — 스티브 잡스
  'teamlead': 'teamlead', '팀장': 'teamlead', '팀장님': 'teamlead',
  '잡스': 'teamlead', '잡스님': 'teamlead', 'Jobs': 'teamlead', 'jobs': 'teamlead',
  # 기획자 — 피터 드러커
  'planner': 'planner', '기획자': 'planner', '기획자님': 'planner',
  '드러커': 'planner', '드러커님': 'planner', 'Drucker': 'planner', 'drucker': 'planner',
  'Planner': 'planner', 'PM': 'planner',
  # 디자이너 — 조너선 아이브
  'designer': 'designer', '디자이너': 'designer', '디자이너님': 'designer',
  '아이브': 'designer', '아이브님': 'designer', 'Ive': 'designer', 'ive': 'designer',
  'Designer': 'designer',
  # 개발자 — 앨런 튜링
  'developer': 'developer', '개발자': 'developer', '개발자님': 'developer',
  '튜링': 'developer', '튜링님': 'developer', 'Turing': 'developer', 'turing': 'developer',
  'Developer': 'developer',
  # QA — W. 에드워즈 데밍
  'qa': 'qa', 'QA': 'qa',
  '데밍': 'qa', '데밍님': 'qa', 'Deming': 'qa', 'deming': 'qa',
  # 사용자(마스터)
  '마스터': 'user', '사장': 'user', '사장님': 'user', 'master': 'user',
  'Master': 'user', '보스': 'user', '대표': 'user', '대표님': 'user',
}


class Meeting:
  '''팀 회의 — 라운드별 의견 + 반박 + 합의 도출.

  라운드 1: 각자 의견 제시 (이전 발언 참고)
  라운드 2: 반박 라운드 — 전문적으로 동의하지 않는 부분 지적
  라운드 3: @멘션 답변 + 추가 토론
  라운드 4: 팀장이 합의 정리
  '''

  MAX_ROUNDS = 4

  def __init__(
    self,
    topic: str,
    briefing: str,
    agents: dict[str, Agent],
    participants: list[str],
    event_bus: EventBus,
  ):
    self.topic = topic
    self.briefing = briefing
    self.agents = agents
    self.participants = participants
    self.event_bus = event_bus
    self.records: list[MeetingRecord] = []

  async def run(self) -> list[MeetingRecord]:
    '''회의를 진행한다.'''
    import asyncio

    # 라운드 1: 각자 의견
    context = f'[팀장 브리핑]\n{self.briefing}\n'

    for name in self.participants:
      agent = self.agents.get(name)
      if not agent:
        continue

      opinion = await agent.speak(self.topic, context=context)
      self.records.append(MeetingRecord(speaker=name, content=opinion, round=1))
      await self._emit(name, opinion, 'response')
      context += f'\n[{name}의 의견]\n{opinion}\n'

    # 라운드 2: 반박 라운드 — 이전 발언에서 전문적으로 동의하지 않는 부분 지적
    round1_summary = '\n'.join(
      f'[{r.speaker}] {r.content}' for r in self.records if r.round == 1
    )

    async def _challenge(name: str) -> tuple[str, str]:
      agent = self.agents.get(name)
      if not agent:
        return name, ''
      system = agent._build_system_prompt(task_hint=self.topic)
      prompt = (
        f'팀 회의 라운드 1이 끝났습니다. 아래는 모든 팀원의 의견입니다:\n\n'
        f'{round1_summary}\n\n'
        f'---\n\n'
        f'당신은 {name}입니다. 위 의견 중 당신의 전문 관점에서 동의하지 않거나 우려되는 부분이 있습니까?\n\n'
        f'[반박 규칙]\n'
        f'- 전문적 근거가 있는 반박만 하세요 (개인 선호 X)\n'
        f'- "@이름 반박 내용" 형태로, 누구의 어떤 주장에 반박하는지 명확히\n'
        f'- 대안을 반드시 제시하세요\n'
        f'- 진심으로 동의한다면 [AGREE]만 출력 — 억지 반박 금지\n'
        f'- 1~3문장, 메신저 톤, 마크다운 금지'
      )
      try:
        result = await run_claude_isolated(
          f'{system}\n\n---\n\n{prompt}',
          model='claude-haiku-4-5-20251001', timeout=30.0,
        )
        text = result.strip()
        if '[AGREE]' in text.upper() or text.upper() == 'AGREE':
          return name, ''
        return name, text.split('\n')[0][:200]
      except Exception:
        logger.debug("반박 라운드 실패: %s", name, exc_info=True)
        return name, ''

    challenge_results = await asyncio.gather(
      *[_challenge(n) for n in self.participants],
      return_exceptions=False,
    )

    has_challenges = False
    for name, challenge_text in challenge_results:
      if challenge_text:
        has_challenges = True
        self.records.append(MeetingRecord(speaker=name, content=challenge_text, round=2))
        await self._emit(name, challenge_text, 'response')

    # 라운드 3: @멘션 답변 (라운드 1+2에서 발생한 @멘션)
    for from_round in (1, 2):
      questions = self._extract_mentions(from_round)
      if not questions:
        continue

      for target, sender, question_context in questions:
        if target == 'teamlead':
          answer = await self._teamlead_answer(sender, question_context)
        else:
          agent = self.agents.get(target)
          if not agent:
            continue
          answer = await agent.respond_to(sender, question_context)

        self.records.append(MeetingRecord(
          speaker=target, content=answer, round=3,
        ))
        await self._emit(target, answer, 'response')

    # 라운드 4: 팀장 합의 정리 — 반박이 있었으면 결론을 정리
    if has_challenges:
      consensus = await self._build_consensus()
      if consensus:
        self.records.append(MeetingRecord(speaker='teamlead', content=consensus, round=4))
        await self._emit('teamlead', consensus, 'response')

    return self.records

  async def _build_consensus(self) -> str:
    '''팀장이 회의 내용을 정리하고 합의사항을 도출한다.'''
    all_opinions = '\n'.join(
      f'[{r.speaker}, 라운드{r.round}] {r.content}' for r in self.records
    )
    prompt = (
      f'당신은 팀장입니다. 팀 회의가 끝났습니다.\n\n'
      f'[회의 주제]\n{self.topic}\n\n'
      f'[전체 발언]\n{all_opinions}\n\n'
      f'팀장으로서 회의를 정리하세요:\n'
      f'1. 합의된 사항 (모두 동의한 방향)\n'
      f'2. 반박이 있었던 사항과 결론 (팀장 판단)\n'
      f'3. 이 방향으로 진행하겠다는 결론\n\n'
      f'3~5문장, 메신저 대화 스타일. 마크다운 금지.'
    )
    try:
      response = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=30.0)
      return response.strip()[:300]
    except Exception:
      logger.debug("합의 도출 실패", exc_info=True)
      return '의견 감사합니다. 종합해서 방향 잡고 진행하겠습니다.'

  async def _teamlead_answer(self, sender: str, question: str) -> str:
    '''팀장(Claude)이 회의 중 질문에 답변한다.'''
    # 지금까지 회의 내용을 컨텍스트로 전달
    meeting_context = '\n'.join(
      f'[{r.speaker}] {r.content}' for r in self.records
    )

    prompt = (
      f'팀 회의 중입니다. 당신은 팀장입니다.\n\n'
      f'[회의 주제]\n{self.topic}\n\n'
      f'[지금까지 회의 내용]\n{meeting_context}\n\n'
      f'{sender}이(가) 당신에게 질문/요청했습니다.\n\n'
      f'팀장으로서 짧고 명확하게 답변하세요 (1~3문장, 메신저 대화 스타일).\n'
      f'마크다운 형식 사용하지 마세요.'
    )
    try:
      response = await run_claude_isolated(prompt, timeout=60.0, model='claude-haiku-4-5-20251001')
      return response.strip()
    except Exception:
      logger.debug("팀장 회의 응답 LLM 호출 실패", exc_info=True)
      return '확인했습니다. 진행해 주세요.'

  def get_summary(self) -> str:
    '''회의 내용을 텍스트로 반환한다.'''
    lines = []
    for rec in self.records:
      lines.append(f'[{rec.speaker}] {rec.content}')
    return '\n'.join(lines)

  def _extract_mentions(self, from_round: int) -> list[tuple[str, str, str]]:
    '''특정 라운드 발언에서 @멘션을 추출한다.

    Returns:
      [(대상 에이전트 ID, 발신자 이름, 질문이 포함된 전체 문장)]
    '''
    results = []
    seen = set()  # (target, sender) 중복 방지

    for rec in self.records:
      if rec.round != from_round:
        continue

      # @로 시작하는 멘션 + 그 뒤의 문장을 추출
      # "@팀장님, 사이트의 주 타겟을 확정해 주십시오" 패턴
      mentions = re.findall(
        r'@([가-힣A-Za-z]+(?:님)?)[,.]?\s*([^@\n]*?)(?=@|$)',
        rec.content,
      )

      for raw_target, context_text in mentions:
        # 한국어/영어 멘션을 에이전트 ID로 변환
        target_id = MENTION_MAP.get(raw_target)
        if not target_id:
          # "님" 제거 후 재시도
          stripped = raw_target.rstrip('님')
          target_id = MENTION_MAP.get(stripped)
        if not target_id or target_id == rec.speaker:
          continue

        key = (target_id, rec.speaker)
        if key in seen:
          continue
        seen.add(key)

        # 질문 컨텍스트: 멘션 뒤의 문장 + 발언 전체
        question = context_text.strip() or rec.content
        results.append((target_id, rec.speaker, question))

    return results

  async def _emit(self, agent_id: str, message: str, event_type: str) -> None:
    '''이벤트 버스에 회의 로그를 발행한다.'''
    await self.event_bus.publish(LogEvent(
      agent_id=agent_id,
      event_type=event_type,
      message=message,
    ))
