# 회의 시스템 — 실제 대화처럼 주고받는 회의
import re
from dataclasses import dataclass

from orchestration.agent import Agent
from log_bus.event_bus import EventBus, LogEvent
from runners.claude_runner import run_claude_isolated


@dataclass
class MeetingRecord:
  '''회의 발언 기록'''
  speaker: str
  content: str
  round: int


# 에이전트 멘션 매핑 — 한국어/영어/포켓몬명 모두 인식
MENTION_MAP: dict[str, str] = {
  # 팀장
  'teamlead': 'teamlead', '팀장': 'teamlead', '팀장님': 'teamlead', '뮤츠': 'teamlead',
  # 기획자
  'planner': 'planner', '기획자': 'planner', '기획자님': 'planner', '알라카짐': 'planner',
  'Planner': 'planner', 'PM': 'planner',
  # 디자이너
  'designer': 'designer', '디자이너': 'planner', '디자이너님': 'designer', '나인테일': 'designer',
  'Designer': 'designer',
  # 개발자
  'developer': 'developer', '개발자': 'developer', '개발자님': 'developer', '리자몽': 'developer',
  'Developer': 'developer',
  # QA
  'qa': 'qa', 'QA': 'qa', '야도란': 'qa',
}


class Meeting:
  '''팀 회의 — 라운드별 의견 + @멘션 기반 대화.

  라운드 1: 각자 의견 제시 (이전 발언 참고)
  라운드 2: @멘션된 사람이 답변 (팀장 포함)
  라운드 3: 추가 대화가 필요하면 한 번 더
  '''

  MAX_ROUNDS = 3

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

    # 라운드 1: 각자 의견
    context = f'[팀장 브리핑]\n{self.briefing}\n'

    # 첨부파일이 큰 경우 TPM이 작은 에이전트에게는 요약본 전달
    topic_full = self.topic
    topic_short = self.topic
    if '[첨부된 참조 자료]' in self.topic:
      topic_short = await self._summarize_for_meeting(self.topic)

    for name in self.participants:
      agent = self.agents.get(name)
      if not agent:
        continue

      # Gemini(planner, developer)는 전문, Groq(designer 등)는 요약본
      topic = topic_full if name in ('planner', 'developer') else topic_short
      opinion = await agent.speak(topic, context=context)
      self.records.append(MeetingRecord(speaker=name, content=opinion, round=1))
      await self._emit(name, opinion, 'response')
      context += f'\n[{name}의 의견]\n{opinion}\n'

    # 라운드 2~3: @멘션 기반 대화
    for round_num in range(2, self.MAX_ROUNDS + 1):
      questions = self._extract_mentions(round_num - 1)
      if not questions:
        break

      for target, sender, question_context in questions:
        # 팀장에 대한 질문은 Claude가 답변
        if target == 'teamlead':
          answer = await self._teamlead_answer(sender, question_context)
        else:
          agent = self.agents.get(target)
          if not agent:
            continue
          answer = await agent.respond_to(sender, question_context)

        self.records.append(MeetingRecord(
          speaker=target, content=answer, round=round_num,
        ))
        await self._emit(target, answer, 'response')

    return self.records

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
      response = await run_claude_isolated(prompt, timeout=120.0)
      return response.strip()
    except Exception:
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

  async def _summarize_for_meeting(self, topic: str) -> str:
    '''첨부파일이 포함된 토픽을 요약하여 TPM이 작은 에이전트용으로 만든다.'''
    from runners.groq_runner import GroqRunner
    parts = topic.split('[첨부된 참조 자료]', 1)
    user_message = parts[0].strip()
    attachments = parts[1] if len(parts) > 1 else ''

    # planner와 같은 모델(Llama 4 Scout)로 요약 — TPM 30K
    groq = self.agents.get('planner', next(iter(self.agents.values()))).groq_runner
    if not groq:
      return user_message + '\n\n[첨부 자료 요약 불가]'

    try:
      summary = await groq.generate(
        f'아래 첨부 자료의 핵심 내용을 1000자 이내로 요약하세요. '
        f'주요 요구사항, 목표, 범위, 제약사항을 중심으로 정리하세요.\n\n{attachments}',
        model='meta-llama/llama-4-scout-17b-16e-instruct',
      )
      return user_message + f'\n\n[첨부 자료 요약]\n{summary}'
    except Exception:
      # 요약 실패 시 앞부분만 전달
      return user_message + '\n\n[첨부 자료 요약]\n' + attachments[:2000]

  async def _emit(self, agent_id: str, message: str, event_type: str) -> None:
    '''이벤트 버스에 회의 로그를 발행한다.'''
    await self.event_bus.publish(LogEvent(
      agent_id=agent_id,
      event_type=event_type,
      message=message,
    ))
