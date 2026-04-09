# 에이전트 기반 클래스 — 인격과 판단력을 가진 에이전트
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from runners.groq_runner import GroqRunner
from runners.gemini_runner import run_gemini
from runners.claude_runner import run_claude_isolated
from log_bus.event_bus import EventBus, LogEvent
from memory.agent_memory import AgentMemory, MemoryRecord
from harness.rejection_analyzer import get_past_rejections
from improvement.prompt_evolver import PromptEvolver

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'
_prompt_evolver = PromptEvolver()


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
    self._restore_conversation_history()

  def _load_prompt(self) -> str:
    '''agents/{name}.md에서 시스템 프롬프트를 로드한다.'''
    path = AGENTS_DIR / f'{self.name}.md'
    if path.exists():
      return path.read_text(encoding='utf-8')
    return ''

  def _restore_conversation_history(self) -> None:
    '''DB에서 최근 DM 대화 이력을 복원한다 (서버 재시작 시 연속성 유지).'''
    try:
      from db.log_store import load_logs
      recent = load_logs(limit=50)
      for log in recent:
        if log['event_type'] not in ('message', 'response'):
          continue
        data = log.get('data') or {}
        if log['agent_id'] == 'user' and data.get('to') == self.name:
          self._conversation_history.append({'role': 'user', 'content': log['message']})
        elif log['agent_id'] == self.name and data.get('dm'):
          self._conversation_history.append({'role': 'assistant', 'content': log['message']})
      self._conversation_history = self._conversation_history[-10:]
    except Exception:
      pass

  def _build_system_prompt(self, task_hint: str = '') -> str:
    '''시스템 프롬프트 + 전문 지식 + 과거 경험 + 과거 불합격 패턴을 결합한다.'''
    prompt = self._system_prompt

    # Layer 1 + 2: 전문 지식 주입
    from orchestration.expertise import load_expertise, detect_task_type
    task_type = detect_task_type(task_hint) if task_hint else ''
    expertise = load_expertise(self.name, task_type)
    if expertise:
      prompt += f'\n\n{expertise}'

    # Layer 3: 과거 불합격 패턴 주입
    past_warnings = get_past_rejections(limit=3)
    if past_warnings:
      prompt += (
        '\n\n## 과거 불합격 주의사항 (반드시 회피할 것)\n'
        + '\n'.join(past_warnings)
      )

    # Layer 3: 이전 경험 주입 (limit 3, feedback 길이 제한)
    experiences = self.memory.load_relevant(task_type=self.name, limit=3)
    if experiences:
      lines = []
      for exp in experiences:
        status_str = '성공' if exp.success else '실패'
        feedback_short = exp.feedback[:80]
        lines.append(f'- [{status_str}] {feedback_short}')
      prompt += '\n\n## 이전 경험\n' + '\n'.join(lines)

    # 학습된 품질 규칙 주입 (자가개선 프레임워크)
    try:
      rules_text = _prompt_evolver.get_active_rules_text(self.name)
      if rules_text:
        prompt += '\n\n' + rules_text
    except Exception:
      pass

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

    파이프라인: 도구 사전실행 → LLM 생성 → 완전성 가드 → 셀프리뷰

    Args:
      prompt: 작업 지시 또는 대화 내용
      context: 추가 컨텍스트 (참조 자료, 이전 결과 등)

    Returns:
      에이전트의 응답 텍스트
    '''
    system = self._build_system_prompt(task_hint=prompt)

    full_prompt = prompt
    if context:
      full_prompt = f'{prompt}\n\n[참고 자료]\n{context}'

    # ── 도구 사전 실행 (키워드 기반, LLM 호출 없음) ──
    try:
      from harness.tool_registry import ToolRegistry, analyze_tool_needs
      tool_needs = analyze_tool_needs(full_prompt, self.name)
      if tool_needs:
        registry = ToolRegistry()
        tool_results = []
        for need in tool_needs[:3]:  # 최대 3개 도구 실행
          result = await registry.execute(self.name, need['tool'], **{k: v for k, v in need.items() if k != 'tool'})
          if result:
            tool_results.append(f'[{need["tool"]}]\n{result[:3000]}')
        if tool_results:
          full_prompt = f'{full_prompt}\n\n[도구 실행 결과]\n' + '\n\n'.join(tool_results)
    except Exception:
      pass

    # 최근 대화 기록을 컨텍스트에 포함 (DM 대화 연속성)
    if self._conversation_history:
      recent = self._conversation_history[-10:]
      history_text = '\n'.join(
        f'{"사용자" if m["role"] == "user" else "나"}: {m["content"][:300]}'
        for m in recent
      )
      full_prompt = f'[이전 대화]\n{history_text}\n\n[현재 메시지]\n{full_prompt}'

    # 입력 중... 표시
    await self._emit('', 'typing')

    # 역할별 러너로 생성
    result = await self._generate(full_prompt, system)

    # 마크다운 코드 펜스 제거
    content = result.strip()
    if content.startswith('```'):
      lines = content.split('\n')
      lines = lines[1:]
      if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
      content = '\n'.join(lines)

    # ── 완전성 가드: 잘림 감지 → 자동 이어쓰기 (최대 2회) ──
    try:
      from harness.output_templates import detect_truncation
      for _ in range(2):
        if not detect_truncation(content):
          break
        continuation = await self._generate(
          f'아래 글이 중간에 잘렸습니다. 잘린 부분부터 이어서 완성하세요.\n\n{content[-2000:]}',
          system,
        )
        content = content + '\n' + continuation.strip()
    except Exception:
      pass

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
    system = self._build_system_prompt(task_hint=topic)

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
      f'- 핵심적으로 발언하세요 (300~500자)\n'
      f'- 다른 팀원 의견에 동의/반박할 때는 근거를 짧게 제시하세요\n'
    )

    await self._emit('', 'typing')
    result = await self._generate(prompt, system)
    return result.strip()

  async def respond_to(self, sender: str, question: str) -> str:
    '''다른 에이전트의 질문에 답변한다.'''
    system = self._build_system_prompt(task_hint=question)
    prompt = (
      f'{sender}이(가) 당신에게 질문했습니다:\n\n'
      f'"{question}"\n\n'
      f'당신의 전문 관점에서 답변하세요. 짧고 명확하게.'
    )
    result = await self._generate(prompt, system)
    return result.strip()

  async def _generate(self, prompt: str, system: str = '') -> str:
    '''에이전트 역할에 맞는 러너로 텍스트를 생성한다.

    러너 매핑:
    - qa: Haiku (판단 전담)
    - planner: Gemini 1차 → Sonnet 폴백
    - developer, designer: Sonnet 1차 → Gemini 폴백
    '''
    full = f'{system}\n\n---\n\n{prompt}' if system else prompt

    if self.name == 'qa':
      return await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=60.0)

    if self.name == 'planner':
      try:
        return await run_gemini(prompt=prompt, system=system)
      except Exception:
        return await run_claude_isolated(full)

    # developer, designer: Sonnet → Gemini
    try:
      return await run_claude_isolated(full)
    except Exception:
      return await run_gemini(prompt=prompt, system=system)

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
    # 실패 시 학습 규칙 추출 시도
    if not success:
      from orchestration.expertise import extract_learned_rule
      extract_learned_rule(self.name, feedback, str(self.memory._file.parent))
