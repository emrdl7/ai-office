# 에이전트 기반 클래스 — 인격과 판단력을 가진 에이전트
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from runners.groq_runner import GroqRunner, MODEL as GROQ_DEFAULT_MODEL
from runners.gemini_runner import run_gemini

# 에이전트별 Groq 모델 매핑 (기본: llama-3.3-70b)
AGENT_GROQ_MODEL: dict[str, str] = {
  'planner': 'meta-llama/llama-4-scout-17b-16e-instruct',
}
from runners.claude_runner import run_claude_isolated
from log_bus.event_bus import EventBus, LogEvent
from memory.agent_memory import AgentMemory, MemoryRecord
from harness.rejection_analyzer import get_past_rejections

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'


class Agent:
  '''인격과 판단력을 가진 에이전트 기반 클래스.

  각 에이전트는:
  - 자기 역할의 시스템 프롬프트(성격, 판단력, 대화 스타일)를 가진다
  - 작업을 거부하거나 다른 에이전트에게 질문할 수 있다
  - 과거 경험을 바탕으로 학습한다
  '''

  def __init__(
    self,
    name: str,
    event_bus: EventBus,
    memory_root: str | Path = 'data/memory',
    groq_runner: GroqRunner | None = None,
  ):
    self.name = name
    self.groq_runner = groq_runner
    self.event_bus = event_bus
    self.memory = AgentMemory(name, memory_root=memory_root)
    self._system_prompt = self._load_prompt()
    self._conversation_history: list[dict[str, str]] = []

  def _load_prompt(self) -> str:
    '''agents/{name}.md에서 시스템 프롬프트를 로드한다.'''
    path = AGENTS_DIR / f'{self.name}.md'
    if path.exists():
      return path.read_text(encoding='utf-8')
    return ''

  def _build_system_prompt(self) -> str:
    '''시스템 프롬프트 + 과거 경험 + 과거 불합격 패턴을 결합한다.'''
    prompt = self._system_prompt

    # 과거 불합격 패턴 주입
    past_warnings = get_past_rejections(limit=3)
    if past_warnings:
      prompt += (
        '\n\n## 과거 불합격 주의사항 (반드시 회피할 것)\n'
        + '\n'.join(past_warnings)
      )

    # 이전 경험 주입
    experiences = self.memory.load_relevant(task_type=self.name, limit=5)
    if experiences:
      lines = []
      for exp in experiences:
        status_str = '성공' if exp.success else '실패'
        lines.append(f'- [{status_str}] {exp.feedback} (태그: {", ".join(exp.tags)})')
      prompt += '\n\n## 이전 경험\n' + '\n'.join(lines)

    return prompt

  async def _emit(self, message: str, event_type: str = 'message') -> None:
    '''이벤트 버스에 로그를 발행한다.'''
    await self.event_bus.publish(LogEvent(
      agent_id=self.name,
      event_type=event_type,
      message=message,
    ))

  async def handle(self, prompt: str, context: str = '') -> str:
    '''작업을 수행하고 결과를 반환한다.

    Args:
      prompt: 작업 지시 또는 대화 내용
      context: 추가 컨텍스트 (참조 자료, 이전 결과 등)

    Returns:
      에이전트의 응답 텍스트
    '''
    system = self._build_system_prompt()

    full_prompt = prompt
    if context:
      full_prompt = f'{prompt}\n\n[참고 자료]\n{context}'

    # 입력 중... 표시
    await self._emit('', 'typing')

    # developer, planner → Gemini CLI
    # designer, qa → Groq(클라우드)
    if self.name in ('developer', 'planner'):
      result = await run_gemini(prompt=full_prompt, system=system)
    elif self.groq_runner:
      result = await self.groq_runner.generate(full_prompt, system=system, model=AGENT_GROQ_MODEL.get(self.name, ''))
    else:
      raise RuntimeError(f'{self.name}: 사용 가능한 러너가 없습니다')

    # 마크다운 코드 펜스 제거
    content = result.strip()
    if content.startswith('```'):
      lines = content.split('\n')
      lines = lines[1:]
      if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
      content = '\n'.join(lines)

    # 대화 기록 추가
    self._conversation_history.append({'role': 'user', 'content': prompt})
    self._conversation_history.append({'role': 'assistant', 'content': content})

    return content

  async def speak(self, topic: str, context: str = '') -> str:
    '''회의에서 자기 관점으로 의견을 제시한다.

    handle()과 달리 산출물을 만드는 게 아니라 의견을 말하는 것.

    Args:
      topic: 회의 주제
      context: 이전 발언자들의 의견 등 컨텍스트

    Returns:
      에이전트의 발언 텍스트
    '''
    system = self._build_system_prompt()

    prompt = (
      f'팀 회의 중입니다. 아래 주제에 대해 당신의 전문 관점에서 의견을 말하세요.\n\n'
      f'[회의 주제]\n{topic}\n'
    )
    if context:
      prompt += f'\n[다른 팀원들의 의견]\n{context}\n'

    prompt += (
      f'\n[주의사항]\n'
      f'- 당신의 전문 영역({self.name}) 관점에서 의견을 말하세요\n'
      f'- 다른 팀원에게 질문이 있으면 "@에이전트명 질문내용" 형태로 적으세요\n'
      f'- 동의하지 않는 부분이 있으면 근거와 함께 반박하세요\n'
      f'- 짧고 핵심적으로 발언하세요 (200자 이내)\n'
    )

    await self._emit('', 'typing')
    result = await self._generate(prompt, system)
    return result.strip()

  async def respond_to(self, sender: str, question: str) -> str:
    '''다른 에이전트의 질문에 답변한다.'''
    system = self._build_system_prompt()
    prompt = (
      f'{sender}이(가) 당신에게 질문했습니다:\n\n'
      f'"{question}"\n\n'
      f'당신의 전문 관점에서 답변하세요. 짧고 명확하게.'
    )
    result = await self._generate(prompt, system)
    return result.strip()

  async def _generate(self, prompt: str, system: str = '') -> str:
    '''에이전트에 맞는 러너로 텍스트를 생성한다.'''
    if self.name in ('developer', 'planner'):
      return await run_gemini(prompt=prompt, system=system)
    if self.groq_runner:
      return await self.groq_runner.generate(prompt, system=system, model=AGENT_GROQ_MODEL.get(self.name, ''))
    raise RuntimeError(f'{self.name}: 사용 가능한 러너가 없습니다')

  def record_experience(self, task_id: str, success: bool, feedback: str, tags: list[str] | None = None) -> None:
    '''경험을 메모리에 기록한다.'''
    from datetime import datetime, timezone
    self.memory.record(MemoryRecord(
      task_id=task_id,
      task_type=self.name,
      success=success,
      feedback=feedback,
      tags=tags or [],
      timestamp=datetime.now(timezone.utc).isoformat(),
    ))
