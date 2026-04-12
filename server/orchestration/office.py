# Office — 진짜 사무실처럼 동작하는 오케스트레이션 시스템
from __future__ import annotations
# 팀장이 판단하고, 팀원이 협업하고, 회의를 통해 프로젝트를 진행한다.
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

from orchestration.intent import IntentType, classify_intent, classify_project_type
from orchestration.phase_registry import ProjectType, get_phases, get_meeting_participants
from orchestration.agent import Agent
from orchestration.meeting import Meeting
from memory.team_memory import TeamMemory, SharedLesson, TeamDynamic, ProjectSummary
from config.team import (
  TEAM, BY_ID, AGENT_IDS, WORKER_IDS,
  display_name, display_with_role, profile_names,
)
from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
from runners.groq_runner import GroqRunner
from runners.claude_runner import run_claude_isolated
from runners.gemini_runner import run_gemini
from bus.message_bus import MessageBus
from bus.payloads import TaskRequestPayload, TaskResultPayload
from log_bus.event_bus import EventBus, LogEvent
from workspace.manager import WorkspaceManager
from db.task_store import get_task
from harness.file_reader import resolve_references
from harness.code_runner import run_code
from harness.rejection_analyzer import record_rejection, get_past_rejections
from harness.stitch_client import designer_generate_with_context
from improvement.engine import ImprovementEngine
from improvement.metrics import MetricsCollector, ProjectMetrics, PhaseMetrics
from improvement.qa_adapter import QAAdapter
from improvement.workflow_optimizer import WorkflowOptimizer

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'


def _extract_keywords(text: str) -> set[str]:
  '''간단한 한국어/영어 명사 키워드 추출 — 중복 건의 판정용.

  조사, 흔한 동사/형용사는 제외. 2글자 이상 단어만.
  '''
  import re
  # 의미 없는 불용어
  stopwords = {
    '제안', '합니다', '있습니다', '됩니다', '있습', '같습니다', '합니다만',
    '관점', '생각', '의견', '부분', '사항', '경우', '것입니다', '것이', '것을',
    '관련', '대한', '대해', '통해', '따라', '위해', '위한',
    '에서', '에게', '으로', '로서', '지만', '이지만',
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'have',
  }
  # 한글 2자 이상 + 영문 3자 이상 + 숫자 포함 토큰
  tokens = re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}[0-9.]*|\d+%?', text)
  return {t.lower() for t in tokens if t.lower() not in stopwords and len(t) >= 2}


class OfficeState(str, Enum):
  '''사무실 상태'''
  IDLE = 'idle'
  TEAMLEAD_THINKING = 'teamlead_thinking'  # 팀장이 판단 중
  MEETING = 'meeting'                       # 회의 중
  WORKING = 'working'                       # 팀원이 작업 중
  QA_REVIEW = 'qa_review'                   # QA 검수 중
  TEAMLEAD_REVIEW = 'teamlead_review'       # 팀장 최종 검수
  REVISION = 'revision'                     # 보완 중
  COMPLETED = 'completed'
  ESCALATED = 'escalated'


class Office:
  '''AI 사무실 — 팀장 주도 동적 흐름.

  모든 입력은 팀장이 먼저 판단한다:
  - 대화/질문 → 팀장이 직접 응답
  - 단순 요청 → 담당 팀원 한 명에게 지시
  - 프로젝트 → 회의 소집 → 역할 분배 → 실행 → QA → 팀장 검수
  '''

  MAX_REVISION_ROUNDS = 3

  def __init__(
    self,
    bus: MessageBus,
    event_bus: EventBus,
    workspace: WorkspaceManager,
    memory_root: str | Path = 'data/memory',
  ):
    self.bus = bus
    self.event_bus = event_bus
    self.workspace = workspace
    self._state = OfficeState.IDLE
    self._revision_count = 0
    self._memory_root = Path(memory_root)
    self._context_summary = ''  # 기획자가 압축한 이전 대화 요약
    self._task_count = 0        # 업무 횟수 카운터
    self._pending_project = None  # 사용자 확인 대기 중인 프로젝트
    self._interrupted_instruction = None  # 서버 재시작으로 중단된 작업 instruction
    self._interrupted_task_id = None
    self._interrupted_confirmed = False
    self._active_agent = ''  # 현재 작업 중인 에이전트 ID
    self._work_started_at = ''  # 작업 시작 ISO 타임스탬프
    self._current_phase = ''   # 현재 진행 중인 단계명
    self._last_review_feedback = ''
    # 프로젝트 세션
    self._active_project_id: str | None = None
    self._active_project_title: str = ''
    self._user_mid_feedback: list[str] = []  # 작업 중 사용자 피드백 축적
    self._phase_feedback: list[dict] = []   # 팀원 리액션/인수인계 피드백
    self._current_project_type: str = ''    # 현재 프로젝트 유형 (phase_registry)

    # Groq 러너 (디자이너, QA용)
    self.groq_runner = GroqRunner()

    # 자가개선 엔진
    self.improvement_engine = ImprovementEngine(event_bus=event_bus)

    # 팀 공유 메모리
    self.team_memory = TeamMemory(memory_root=memory_root)

    # 자발적 활동 제어
    self._autonomous_running = False
    self._autonomous_task = None

    # 팀원 초기화
    self.agents: dict[str, Agent] = {}
    for name in ('planner', 'designer', 'developer', 'qa'):
      self.agents[name] = Agent(
        name=name,
        event_bus=event_bus,
        memory_root=memory_root,
        groq_runner=self.groq_runner,
      )

  async def restore_pending_tasks(self) -> None:
    '''서버 재시작 시 중단된 태스크를 복원한다.

    자동 재실행하지 않고 사용자에게 선택권을 준다.
    "진행해" 등으로 응답하면 원래 instruction으로 다시 실행한다.
    '''
    from db.task_store import get_resumable_tasks, update_task_state, get_active_project

    # 활성 프로젝트 복원
    active = get_active_project()
    if active:
      self._active_project_id = active['project_id']
      self._active_project_title = active['title']

    tasks = get_resumable_tasks()
    if not tasks:
      return

    for task in tasks:
      state = task['state']
      task_id = task['task_id']
      ctx = task.get('context')
      instruction = task['instruction']
      instruction_preview = instruction[:50]

      if state == 'waiting_input' and ctx:
        # 사용자 확인 대기 복원 (원래 workspace도 복원)
        self._pending_project = ctx
        self._pending_task_id = task_id
        from workspace.manager import WorkspaceManager
        WORKSPACE_ROOT = Path(__file__).parent.parent.parent / 'workspace'
        self.workspace = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
        await self._emit(
          'teamlead',
          f'@마스터 이전에 확인 요청드린 사항이 있습니다. 답변해 주시면 이어서 진행하겠습니다.',
          'response',
        )
      elif state == 'running':
        # running → interrupted 상태로 변경, 원래 instruction + workspace 보존
        update_task_state(task_id, 'interrupted')
        self._interrupted_instruction = instruction
        self._interrupted_task_id = task_id
        from workspace.manager import WorkspaceManager
        WORKSPACE_ROOT = Path(__file__).parent.parent.parent / 'workspace'
        self.workspace = WorkspaceManager(task_id=task_id, workspace_root=str(WORKSPACE_ROOT))
        await self._emit(
          'teamlead',
          f'@마스터 서버 재시작으로 중단된 작업이 있습니다: "{instruction_preview}..."\n이어서 진행하려면 말씀해 주세요.',
          'response',
        )

  async def _emit(self, agent_id: str, message: str, event_type: str = 'message') -> None:
    '''이벤트 버스에 로그 발행'''
    await self.event_bus.publish(LogEvent(
      agent_id=agent_id,
      event_type=event_type,
      message=message,
    ))

  async def _compress_history(self) -> None:
    '''기획자가 이전 대화를 압축 요약한다.

    새로운 업무 시작 전에 호출하여 토큰을 절약한다.
    채팅창 표시는 그대로 유지하고, 에이전트 컨텍스트만 요약본으로 대체한다.
    '''
    from db.log_store import load_logs

    # 최근 로그를 가져와서 요약 대상 구성
    recent_logs = load_logs(limit=100)
    if len(recent_logs) < 10:
      return  # 압축할 만한 대화가 없음

    # 대화 내용만 추출 (시스템 이벤트 제외)
    chat_lines = []
    for log in recent_logs:
      if log['event_type'] in ('response', 'message') and log['agent_id'] != 'system':
        speaker = log['agent_id']
        chat_lines.append(f'[{speaker}] {log["message"][:200]}')

    if not chat_lines:
      return

    conversation_text = '\n'.join(chat_lines[-50:])  # 최근 50개만

    planner = self.agents['planner']
    system = planner._build_system_prompt()
    prompt = (
      f'아래는 팀 채팅방의 최근 대화 내역입니다.\n\n'
      f'{conversation_text}\n\n'
      f'기획자로서 이 대화를 압축 요약하세요.\n'
      f'- 논의된 주제, 결정된 사항, 미해결 이슈를 구분하세요\n'
      f'- 핵심만 남기고 500자 이내로 요약하세요\n'
      f'- 마크다운 형식 사용하지 마세요'
    )

    try:
      summary = await run_claude_isolated(f'{system}\n\n---\n\n{prompt}', model='claude-haiku-4-5-20251001', timeout=60.0)
      self._context_summary = summary.strip()
      # 각 에이전트의 대화 기록도 초기화
      for agent in self.agents.values():
        agent._conversation_history = []
    except Exception:
      logger.debug("대화 히스토리 압축 실패", exc_info=True)

  def _update_context(self, user_input: str, response: str) -> None:
    '''대화 맥락을 실시간 갱신한다. 최근 15개 턴만 유지.'''
    new_lines = [f'[사용자] {user_input[:150]}']
    if response:
      new_lines.append(f'[팀장] {response[:150]}')

    existing = self._context_summary.split('\n') if self._context_summary else []
    updated = existing + new_lines
    # 최근 15줄만 유지
    self._context_summary = '\n'.join(updated[-15:])

  async def _team_chat(self, user_input: str, chat_subtype: str = 'casual', teamlead_response: str = '') -> None:
    '''팀 채널 대화 — 스레드 기반. 각 에이전트가 전체 대화 스레드를 읽고 판단한다.

    핵심: 실제 그룹 채팅처럼 이전 발언을 모두 본 뒤 새 가치를 더할 수 있을 때만 발언.
    업무 감지: [TASK_DETECTED:설명] 출력 시 팀장이 업무 흐름으로 전환

    chat_subtype: 'greeting'(인사) | 'question'(질문) | 'casual'(잡담)
    teamlead_response: 팀장의 응답 (스레드에 포함)
    '''
    import random
    from orchestration.meeting import MENTION_MAP

    # greeting: 랜덤 1명만 짧은 한마디
    if chat_subtype == 'greeting':
      responder = random.choice(['planner', 'designer', 'developer', 'qa'])
      try:
        response = await run_claude_isolated(
          f'당신은 {display_name(responder)}입니다.\n'
          f'팀장이 사용자에게 인사했습니다. 당신도 가볍게 한마디 하세요.\n'
          f'10자 이내, 이모지 1개. 메신저 톤. 마크다운 금지.\n'
          f'예: "좋은 아침이에요 ☀️", "화이팅입니다 💪"',
          model='claude-haiku-4-5-20251001',
          timeout=15.0,
        )
        text = response.strip().split('\n')[0][:20]
        if text:
          await self._emit(responder, text, 'response')
      except Exception:
        logger.debug("인사 리액션 생성 실패", exc_info=True)
      return

    # question: 관련 에이전트 1명만 답변 (나머지 PASS)
    if chat_subtype == 'question':
      for name in ('planner', 'designer', 'developer', 'qa'):
        agent = self.agents.get(name)
        if not agent:
          continue
        system = agent._build_system_prompt(task_hint=user_input)
        prompt = (
          f'팀 채팅방에서 사용자가 질문했습니다:\n\n"{user_input}"\n\n'
          f'당신은 {name}입니다. 이 질문이 당신의 전문 영역과 관련이 있으면 답변하세요.\n'
          f'관련 없으면 [PASS]만 출력하세요.\n'
          f'답변은 2~3문장으로 짧게. 메신저 톤. 마크다운 금지.'
        )
        try:
          resp = await run_claude_isolated(
            f'{system}\n\n---\n\n{prompt}',
            model='claude-haiku-4-5-20251001',
            timeout=30.0,
          )
          content = resp.strip()
          if content and '[PASS]' not in content.upper():
            await self._emit(name, content, 'response')
            break  # 1명만 답변
        except Exception:
          logger.debug("질문 응답 생성 실패: %s", name, exc_info=True)
      return
    import asyncio
    import random
    import re

    # ── @멘션 파싱 — 지목된 에이전트 파악 ──
    mentioned_ids: set[str] = set()
    raw_mentions = re.findall(r'@([가-힣A-Za-z]+(?:님)?)', user_input)
    for raw in raw_mentions:
      target = MENTION_MAP.get(raw) or MENTION_MAP.get(raw.rstrip('님'))
      if target and target not in ('user', 'teamlead'):
        mentioned_ids.add(target)

    # ── 기본 스레드 구성 ──
    base_thread: list[str] = []
    if self._context_summary:
      base_thread.append(f'[이전 대화 맥락]\n{self._context_summary}')
      base_thread.append('---')
    base_thread.append(f'[사용자] {user_input}')
    if teamlead_response:
      base_thread.append(f'[팀장] {teamlead_response}')

    # ── Round 1: 4명 병렬 호출 ──
    async def _single_agent_chat(
      name: str,
      thread_lines: list[str],
      round_context: str = '',
    ) -> tuple[str, str]:
      '''(name, 응답) 반환. PASS 혹은 실패 시 빈 문자열.'''
      agent = self.agents.get(name)
      if not agent:
        return name, ''
      system = agent._build_system_prompt(task_hint=user_input)
      thread_text = '\n'.join(thread_lines)
      is_mentioned = name in mentioned_ids

      if round_context:
        # Round 2 프롬프트 — 상대 발언을 보고 추가 반응 여부 결정
        prompt = (
          f'아래는 팀 채팅방의 현재 대화입니다.\n\n'
          f'{thread_text}\n\n'
          f'[라운드 1 발언]\n{round_context}\n\n'
          f'---\n\n'
          f'당신은 {name}입니다.\n'
          f'위 발언들을 읽고 한마디 더 하겠습니까?\n'
          f'새로운 관점이나 반박이 있으면 1문장으로 하세요. 없으면 [PASS].'
          f'\n마크다운 금지.'
        )
      elif is_mentioned:
        prompt = (
          f'아래는 팀 채팅방의 현재 대화입니다.\n\n'
          f'{thread_text}\n\n'
          f'---\n\n'
          f'당신은 {name}입니다.\n'
          f'사용자가 당신을 직접 지목(@멘션)했습니다. 반드시 응답하세요.\n\n'
          f'1~2문장, 메신저 톤, 마크다운 금지.\n'
          f'이미 완료된 작업에 대한 새 약속은 금지.\n'
          f'대화 중 업무 요청이 감지되면 [TASK_DETECTED:업무 설명]을 출력하세요.'
        )
      else:
        prompt = (
          f'아래는 팀 채팅방의 현재 대화입니다.\n\n'
          f'{thread_text}\n\n'
          f'---\n\n'
          f'당신은 {name}입니다.\n'
          f'위 대화를 읽고 반응해야 하는지 판단하세요.\n\n'
          f'[판단 기준]\n'
          f'- 누군가 이미 적절히 답한 내용은 반복하지 마라.\n'
          f'- 새로운 관점이나 정보를 더할 수 있을 때만 발언하라.\n'
          f'- 일상 대화(날씨, 교통, 안부)는 대부분 [PASS]\n'
          f'- 직접 지목(@멘션)되지 않았고 추가할 가치가 없으면 [PASS]\n'
          f'- 업무 요청이 감지되면 [TASK_DETECTED:업무 설명]을 출력하세요.\n\n'
          f'반응 불필요: [PASS]\n'
          f'반응 필요: 1~2문장, 메신저 톤, 마크다운 금지. 이미 나온 말 반복 금지.\n'
          f'이미 완료된 작업에 대한 새 약속은 금지.'
        )

      try:
        await self._emit(name, '', 'typing')
        resp = await run_claude_isolated(
          f'{system}\n\n---\n\n{prompt}',
          model='claude-haiku-4-5-20251001',
          timeout=30.0,
        )
        content = resp.strip()
        is_pass = '[PASS]' in content.upper() or content.strip().upper() == 'PASS'
        return name, ('' if is_pass else content)
      except Exception:
        logger.debug("팀 채팅 에이전트 응답 실패: %s", name, exc_info=True)
        return name, ''

    all_agents = ['planner', 'designer', 'developer', 'qa']
    round1_results = await asyncio.gather(
      *[_single_agent_chat(n, base_thread) for n in all_agents],
      return_exceptions=False,
    )

    # Round 1 결과 처리
    responded: list[str] = []
    task_detected: str | None = None
    thread_after_r1 = list(base_thread)

    for name, content in round1_results:
      if not content:
        continue
      # 업무 감지 체크
      if '[TASK_DETECTED:' in content:
        task_match = re.search(r'\[TASK_DETECTED:(.+?)\]', content)
        if task_match:
          task_detected = task_match.group(1).strip()
          chat_part = re.sub(r'\[TASK_DETECTED:.+?\]', '', content).strip()
          if chat_part:
            await self._emit(name, chat_part, 'response')
            thread_after_r1.append(f'[{name}] {chat_part}')
            responded.append(name)
          continue
      await self._emit(name, content, 'response')
      thread_after_r1.append(f'[{name}] {content}')
      responded.append(name)

    # 업무 감지 → 팀장 전환
    if task_detected:
      await self._emit(
        'teamlead',
        f'지금 말씀 중에 업무 요청이 있는 것 같네요. "{task_detected}" — 확인해보겠습니다.',
        'response',
      )
      re_intent = await classify_intent(task_detected)
      if re_intent.intent != IntentType.CONVERSATION:
        return

    # 아무도 안 답하면 fallback
    if not responded:
      fallback_name = random.choice(all_agents)
      agent = self.agents[fallback_name]
      system = agent._build_system_prompt(task_hint=user_input)
      thread_text = '\n'.join(base_thread)
      try:
        response = await run_claude_isolated(
          f'{system}\n\n---\n\n아래는 팀 채팅방의 현재 대화입니다.\n\n{thread_text}\n\n'
          f'아무도 답을 안 했습니다. 당신이 대표로 한마디 해주세요.\n짧고 자연스럽게. 마크다운 금지.',
          model='claude-haiku-4-5-20251001',
          timeout=30.0,
        )
        content = response.strip()
        await self._emit(fallback_name, content, 'response')
        thread_after_r1.append(f'[{fallback_name}] {content}')
        responded.append(fallback_name)
      except Exception:
        logger.debug("팀 채팅 폴백 응답 실패", exc_info=True)
      return  # fallback 후 Round 2 불필요

    # ── Round 2: Round 1 응답을 보고 추가 반응 ──
    round1_context = '\n'.join(
      f'[{n}] {c}' for n, c in round1_results if c and '[TASK_DETECTED:' not in c
    )
    if round1_context:
      round2_results = await asyncio.gather(
        *[_single_agent_chat(n, thread_after_r1, round_context=round1_context) for n in all_agents],
        return_exceptions=False,
      )
      for name, content in round2_results:
        if not content:
          continue
        await self._emit(name, content, 'response')

  async def receive(self, user_input: str) -> dict[str, Any]:
    '''사용자 입력을 받아 처리한다.

    Returns:
      {'state': str, 'response': str, 'artifacts': list[str]}
    '''
    # 의도 분류 전에는 typing만 표시 (작업중 X)
    await self._emit('teamlead', '', 'typing')

    # 서버 재시작 후 첫 대화 시 이전 맥락 복원
    if not self._context_summary:
      try:
        from db.log_store import load_logs
        recent = load_logs(limit=30)
        chat_lines = [
          f'[{l["agent_id"]}] {l["message"][:150]}'
          for l in recent
          if l['event_type'] in ('response', 'message') and l['agent_id'] != 'system'
        ]
        if chat_lines:
          self._context_summary = '\n'.join(chat_lines[-15:])
      except Exception:
        logger.debug("이전 맥락 복원 실패", exc_info=True)

    # 0. 대기 중인 프로젝트가 있으면 사용자 답변으로 이어서 진행
    if hasattr(self, '_pending_project') and self._pending_project:
      return await self._continue_project(user_input)

    # 0-1. 중단된 작업이 있고 사용자가 재개를 요청하면 바로 재실행
    if hasattr(self, '_interrupted_instruction') and self._interrupted_instruction:
      resume_phrases = ('이전 작업', '이어서 진행', '계속 진행', '재개해', '아까 거', '중단된 거', '이어서 해', '계속해', '진행해')
      if any(phrase in user_input for phrase in resume_phrases):
        # 바로 재실행 — 2단계 확인 불필요
        original = self._interrupted_instruction
        original_task_id = self._interrupted_task_id
        self._interrupted_instruction = None
        self._interrupted_task_id = None
        self._interrupted_confirmed = False
        if original_task_id:
          ws_root = str(Path(__file__).parent.parent.parent / 'workspace')
          self.workspace = WorkspaceManager(task_id=original_task_id, workspace_root=ws_root)
        return await self.receive(original)
      else:
        # 다른 입력이면 중단 작업 폐기
        self._interrupted_instruction = None
        self._interrupted_task_id = None
        self._interrupted_confirmed = False

    # 0-2. 이미 작업 중이면 새 요청 차단
    if self._state not in (OfficeState.IDLE, OfficeState.COMPLETED, OfficeState.ESCALATED):
      await self._emit(
        'teamlead',
        '현재 다른 작업을 처리 중입니다. 잠시 후 다시 말씀해 주세요.',
        'response',
      )
      return {'state': self._state.value, 'response': '', 'artifacts': []}

    # 1. 파일 참조 해석
    reference_context = resolve_references(user_input)

    # 2. 팀장 판단 — 최근 대화 맥락을 함께 전달 ("그거 조사해봐" 같은 지시어 해석용)
    recent_context = ''
    try:
      from db.log_store import load_logs
      recent_logs = load_logs(limit=20)
      chat_lines = []
      for log in recent_logs:
        if log['event_type'] in ('response', 'message') and log['agent_id'] != 'system':
          chat_lines.append(f'[{log["agent_id"]}] {log["message"][:150]}')
      if chat_lines:
        recent_context = '\n'.join(chat_lines[-10:])
    except Exception:
      logger.debug("최근 대화 로그 로딩 실패", exc_info=True)

    # DB 최근 대화 + 인메모리 맥락 요약 결합
    combined_context = recent_context
    if self._context_summary and self._context_summary not in recent_context:
      combined_context = f'{self._context_summary}\n---\n{recent_context}' if recent_context else self._context_summary

    intent_result = await classify_intent(
      user_input,
      recent_context=combined_context,
      active_project_title=self._active_project_title,
    )

    # 2. 업무 시작 시 프로젝트 세션 관리 + 이전 대화 압축
    is_work = intent_result.intent in (IntentType.QUICK_TASK, IntentType.PROJECT, IntentType.CONTINUE_PROJECT)
    if is_work:
      # 업무일 때만 "작업중" 상태 전환
      self._state = OfficeState.TEAMLEAD_THINKING
      self._active_agent = 'teamlead'
      self._work_started_at = datetime.now(timezone.utc).isoformat()
      if self._task_count > 0:
        await self._compress_history()
      self._task_count += 1
      self._revision_count = 0

      from db.task_store import create_project, update_task_project, archive_project
      from orchestration.intent import generate_project_title

      if intent_result.intent == IntentType.CONTINUE_PROJECT and self._active_project_id:
        # 기존 프로젝트 이어가기 — workspace 재사용
        self.workspace = WorkspaceManager(
          task_id=self._active_project_id,
          workspace_root=str(Path(__file__).parent.parent.parent / 'workspace'),
        )
        if hasattr(self, '_current_task_id'):
          update_task_project(self._current_task_id, self._active_project_id)
        await self._emit('system', f'📂 프로젝트 이어가기: {self._active_project_title}', 'project_update')
      else:
        # 새 프로젝트 시작 — 이전 프로젝트 컨텍스트 초기화 (다른 프로젝트 대화 오염 방지)
        self._context_summary = ''
        for agent in self.agents.values():
          agent._conversation_history = []
        if self._active_project_id:
          archive_project(self._active_project_id)

        ws_root = str(Path(__file__).parent.parent.parent / 'workspace')
        new_pid = str(uuid.uuid4())
        title = await generate_project_title(user_input)

        create_project(new_pid, title)
        self._active_project_id = new_pid
        self._active_project_title = title
        self.workspace = WorkspaceManager(task_id=new_pid, workspace_root=ws_root)
        if hasattr(self, '_current_task_id'):
          update_task_project(self._current_task_id, new_pid)
        await self._emit('system', f'📂 새 프로젝트: {title}', 'project_update')

    # 3. 의도별 분기
    if intent_result.intent == IntentType.CONVERSATION:
      response = intent_result.direct_response or ''

      await self._emit('teamlead', response, 'response')

      # 팀장 응답 완료 → 팀원 대화로 전환 (UI에서 "팀장 작업중" 표시 제거)
      self._active_agent = ''
      self._work_started_at = ''
      self._current_phase = ''

      # 서브유형별 팀원 반응 제어 — 팀장 응답을 스레드에 포함
      await self._team_chat(user_input, chat_subtype=intent_result.chat_subtype, teamlead_response=response)

      # 대화 맥락 실시간 갱신 — 후속 메시지에서 주제 변경 감지 가능
      self._update_context(user_input, response)

      self._state = OfficeState.COMPLETED
      self._active_agent = ''
      self._work_started_at = ''
      self._current_phase = ''
      return {
        'state': self._state.value,
        'response': response,
        'artifacts': [],
      }

    if intent_result.intent in (IntentType.QUICK_TASK, IntentType.CONTINUE_PROJECT):
      return await self._handle_quick_task(
        user_input,
        intent_result.target_agent or 'developer',
        intent_result.analysis,
        reference_context,
      )

    if intent_result.intent == IntentType.PROJECT:
      return await self._handle_project(
        user_input,
        intent_result.analysis,
        reference_context,
      )

    # 기본값
    self._state = OfficeState.COMPLETED
    return {'state': self._state.value, 'response': '처리할 수 없는 입력입니다.', 'artifacts': []}

  async def _handle_quick_task(
    self,
    user_input: str,
    agent_name: str,
    analysis: str,
    reference_context: str,
  ) -> dict[str, Any]:
    '''단순 작업 — 팀원 한 명이 처리'''
    agent = self.agents.get(agent_name)
    if not agent:
      return {'state': 'error', 'response': f'{agent_name} 에이전트를 찾을 수 없습니다.', 'artifacts': []}

    self._state = OfficeState.WORKING
    self._active_agent = agent_name

    # 업무 수신 확인    await self._emit('teamlead', f'알겠습니다. {display_name(agent_name)}에게 맡기겠습니다.', 'response')

    # 담당자 업무 수령 확인
    await self._task_acknowledgment(agent_name, analysis or user_input)

    prompt = analysis or user_input
    # 사용자 중간 피드백이 있으면 프롬프트에 주입
    if self._user_mid_feedback:
      feedback_text = '\n'.join(f'- {fb}' for fb in self._user_mid_feedback)
      prompt += f'\n\n[사용자 피드백 — 반드시 반영할 것]\n{feedback_text}'
    # 이전 대화 요약 + 참조 자료를 컨텍스트로 전달
    role_scope = {
      'planner': '기획/전략/구조 설계',
      'designer': '디자인/UI·UX/시각 설계',
      'developer': '개발/기술/아키텍처',
      'qa': '품질 검수/테스트',
    }
    my_scope = role_scope.get(agent_name, '본인 전문 영역')
    ctx_parts = [
      f'[작업 모드] 이 작업은 당신 혼자 수행하는 단독 작업입니다.\n'
      f'- 당신의 전문 영역은 "{my_scope}"입니다. 이 관점에서만 분석/작성하세요.\n'
      f'- 다른 팀원(디자이너, 개발자, QA 등)의 전문 영역을 대신 분석하지 마세요.\n'
      f'- 다른 팀원이 참여하지 않았으므로 "각 팀 결과를 취합" 등 허위 표현을 쓰지 마세요.\n'
      f'- 다른 영역의 검토가 필요하면 "이 부분은 디자이너/개발자 검토가 필요합니다"로 남기세요.\n\n'
      f'[중요: 산출물 작성 규칙]\n'
      f'- 착수 인사는 이미 채팅으로 전달했다. 여기서는 산출물 본문만 작성하라.\n'
      f'- "확인했습니다", "파악하겠습니다" 같은 인사/선언을 본문에 넣지 마라.\n'
      f'- 분석, 리뷰, 기획 등 요청받은 결과물을 완성된 형태로 즉시 출력하라.'
    ]
    if self._context_summary:
      ctx_parts.append(f'[이전 대화 요약]\n{self._context_summary}')
    if reference_context:
      ctx_parts.append(reference_context)
    result = await agent.handle(prompt, context='\n\n'.join(ctx_parts))

    # 보완 전문 기여 — 관련 역할 에이전트가 전문 내용 제공 후 담당자가 결과물 보강
    result = await self._quick_task_second_opinion(agent_name, prompt, result, agent, ctx_parts)

    # QA 검수 (최대 3회: 초기 + 2회 보완)
    qa_agent = self.agents.get('qa')
    accumulated_feedback: list[str] = []
    if qa_agent and agent_name != 'qa':
      for attempt in range(3):
        self._state = OfficeState.QA_REVIEW
        self._active_agent = 'qa'
        await self._emit('qa', '산출물 검수를 시작합니다.', 'response')

        feedback_section = ''
        if accumulated_feedback:
          feedback_section = '\n[이전 QA 피드백 이력]\n' + '\n'.join(f'- {fb}' for fb in accumulated_feedback) + '\n\n'

        qa_prompt = (
          f'[원본 요구사항]\n{prompt}\n\n'
          f'{feedback_section}'
          f'[작업 결과물]\n{result}\n\n'
          f'위 원본 요구사항 대비 결과물을 검수하세요.\n\n'
          f'[검수 원칙 — 반드시 준수]\n'
          f'- 원본 요구사항에 명시된 내용만 기준으로 판단하세요\n'
          f'- 사용자가 요청하지 않은 사항(배경 맥락, 추정 목적, 이전 대화 등)을 추가 요구사항으로 간주하지 마세요\n'
          f'- "~했으면 좋겠다", "~도 있어야 한다"는 추가 의견은 severity=minor로만 처리하세요\n'
          f'- 명시된 요구사항을 충족했으면 status=success입니다\n\n'
          f'반드시 JSON 형식으로 응답: {{"status":"success|fail","summary":"...","failure_reason":"...","severity":"critical|major|minor|none"}}'
        )
        qa_result = await qa_agent.handle(qa_prompt)

        # severity 기반 합격/불합격 판단
        passed = True
        failure_reason = ''
        severity = 'none'
        try:
          import re
          json_match = re.search(r'\{[^{}]*\}', qa_result, re.DOTALL)
          if json_match:
            qa_json = json.loads(json_match.group())
            severity = qa_json.get('severity', 'none')
            if qa_json.get('status') == 'fail' or severity in ('critical', 'major'):
              passed = False
              failure_reason = qa_json.get('failure_reason', 'QA 불합격')
        except (json.JSONDecodeError, AttributeError):
          if '불합격' in qa_result or 'fail' in qa_result.lower():
            passed = False
            failure_reason = qa_result[:300]

        if passed:
          msg = '검수 통과 ✅'
          if severity == 'minor':
            msg = f'검수 통과 (경미한 보완 권장) ✅'
          await self._emit('qa', msg, 'response')
          # 성공 경험 기록
          try:
            import uuid as _uuid
            agent.record_experience(
              task_id=str(_uuid.uuid4()),
              success=True,
              feedback=f'QA 통과: {prompt[:100]}',
              tags=[agent_name, 'qa_pass'],
            )
          except Exception:
            logger.debug("QA 통과 경험 기록 실패", exc_info=True)
          break
        else:
          await self._emit('qa', f'검수 불합격 [{severity}]: {failure_reason[:200]}', 'response')
          accumulated_feedback.append(failure_reason[:200])
          # 실패 경험 기록 (보완 학습용)
          try:
            import uuid as _uuid
            agent.record_experience(
              task_id=str(_uuid.uuid4()),
              success=False,
              feedback=failure_reason[:200],
              tags=[agent_name, 'qa_fail', severity],
            )
          except Exception:
            logger.debug("QA 불합격 경험 기록 실패", exc_info=True)
          if attempt < 2:
            self._state = OfficeState.WORKING
            self._active_agent = agent_name
            await self._emit('teamlead', f'{display_name(agent_name)}, 보완 부탁합니다.', 'response')
            all_feedback = '\n'.join(f'- {fb}' for fb in accumulated_feedback)
            revision_prompt = f'{prompt}\n\n[QA 피드백 — 반드시 반영할 것]\n{all_feedback}\n\n[이전 결과물]\n{result}'
            result = await agent.handle(revision_prompt, context='\n\n'.join(ctx_parts))

    # 산출물 저장
    saved_paths = []
    try:
      file_path = 'quick-task/result.md'
      self.workspace.write_artifact(file_path, result)
      saved_paths.append(f'{self.workspace.task_id}/{file_path}')
    except Exception:
      logger.warning("퀵태스크 산출물 저장 실패", exc_info=True)

    # 팀장 최종 검수 (최대 1회 보완)
    self._state = OfficeState.TEAMLEAD_REVIEW
    self._active_agent = 'teamlead'
    await self._emit('teamlead', '최종 검수하겠습니다.', 'response')

    review_prompt = (
      f'[사용자 원본 요구사항]\n{prompt}\n\n'
      f'[최종 산출물]\n{result[:8000]}\n\n'
      f'위 요구사항 대비 산출물의 완성도를 검수하세요.\n'
      f'합격이면 첫 줄에 [PASS]를, 불합격이면 [FAIL]을 적고 이유를 적으세요.'
    )
    try:
      review_response = await run_claude_isolated(review_prompt, timeout=60.0, model='claude-haiku-4-5-20251001')
    except Exception:
      logger.warning("팀장 최종 검수 실행 실패, PASS 처리", exc_info=True)
      review_response = '[PASS]'
    review_text = review_response.strip()

    if '[PASS]' not in review_text[:100]:
      # 불합격 → 1회 보완
      feedback = review_text.replace('[FAIL]', '').strip()[:500]
      await self._emit('teamlead', f'보완이 필요합니다: {feedback[:200]}', 'response')

      self._state = OfficeState.WORKING
      self._active_agent = agent_name
      revision_prompt = f'{prompt}\n\n[팀장 보완 지시 — 반드시 반영할 것]\n{feedback}\n\n[이전 결과물]\n{result}'
      result = await agent.handle(revision_prompt, context='\n\n'.join(ctx_parts))

      # 보완된 결과물 재저장
      try:
        self.workspace.write_artifact(file_path, result)
      except Exception:
        logger.warning("보완 결과물 재저장 실패", exc_info=True)

    # 팀장 최종 보고 — 사용자에게 결과 요약 + 산출물 링크
    report_prompt = (
      f'[사용자 원본 요구사항]\n{prompt[:500]}\n\n'
      f'[완성된 산출물 요약]\n{result[:3000]}\n\n'
      f'팀장으로서 사용자에게 최종 보고하세요.\n'
      f'- 누가 어떤 작업을 했는지 (이 경우 {display_name(agent_name)}이 단독 수행)\n'
      f'- 핵심 결과 요약 (3~5줄)\n'
      f'- 추가 검토가 필요한 사항이 있으면 언급\n'
      f'간결하게 보고하세요.'
    )
    teamlead_agent = self.agents.get('teamlead')
    try:
      report = await teamlead_agent.handle(report_prompt) if teamlead_agent else ''
    except Exception:
      logger.warning("팀장 최종 보고 생성 실패", exc_info=True)
      report = ''

    if report:
      await self.event_bus.publish(LogEvent(
        agent_id='teamlead',
        event_type='response',
        message=report,
        data={'artifacts': saved_paths},
      ))
    else:
      # 보고 생성 실패 시 fallback
      summary = '\n'.join(result.strip().split('\n')[:8])
      await self.event_bus.publish(LogEvent(
        agent_id='teamlead',
        event_type='response',
        message=f'{display_name(agent_name)} 작업 완료했습니다.\n\n{summary}',
        data={'artifacts': saved_paths},
      ))

    # 프로젝트 세션 종료
    if self._active_project_id:
      from db.task_store import archive_project
      archive_project(self._active_project_id)
      await self._emit('system', '📂 프로젝트 완료', 'project_close')
      self._active_project_id = None
      self._active_project_title = ''
      self._current_project_type = ''

    self._state = OfficeState.COMPLETED
    self._active_agent = ''
    self._work_started_at = ''
    self._current_phase = ''
    self._user_mid_feedback = []  # 피드백 초기화
    return {
      'state': self._state.value,
      'response': result,
      'artifacts': saved_paths,
    }

  async def _handle_project(
    self,
    user_input: str,
    analysis: str,
    reference_context: str,
  ) -> dict[str, Any]:
    '''프로젝트 — 단계별 진행 (기획 → 디자인 → 개발) + 중간 확인.

    각 단계가 끝나면 팀장이 결과를 보고하고,
    확인이 필요한 사항은 사용자에게 질문한다.
    '''
    # 이전 대화 요약이 있으면 브리핑에 포함
    briefing = analysis
    if self._context_summary:
      briefing = f'{analysis}\n\n[이전 논의 요약]\n{self._context_summary}'

    # 프로젝트 유형 분류 — 대화 맥락 포함
    type_context = self._context_summary or analysis
    project_type = await classify_project_type(user_input, context=type_context[:500])
    phases = get_phases(project_type)
    participants = get_meeting_participants(project_type)

    # 업무 수신 확인
    await self._emit('teamlead', f'알겠습니다. 확인하고 팀원들과 논의해보겠습니다. (프로젝트 유형: {project_type.value})', 'response')

    # 1. 회의 소집 — 방향 잡기
    self._state = OfficeState.MEETING
    await self._emit('teamlead', '팀원들 의견을 모아볼게요.', 'response')

    meeting = Meeting(
      topic=user_input,
      briefing=briefing,
      agents=self.agents,
      participants=participants,
      event_bus=self.event_bus,
    )
    await meeting.run()
    meeting_summary = meeting.get_summary()

    # 2. 팀장이 회의 결과를 바탕으로 프로젝트 단계를 동적 설계
    dynamic_phases = await self._plan_project_phases(user_input, analysis, meeting_summary)
    if dynamic_phases:
      phases = dynamic_phases
      await self._emit('teamlead', f'프로젝트를 {len(phases)}단계로 진행하겠습니다.', 'response')
    # dynamic_phases가 None이면 기존 get_phases() 결과를 그대로 사용

    # 3. 팀장이 회의 결과에서 확인 필요한 사항을 사용자에게 질문
    questions = await self._extract_user_questions(user_input, meeting_summary)
    if questions:
      # @마스터가 안 붙어 있으면 앞에 추가
      if not questions.startswith('@마스터'):
        questions = f'@마스터 {questions}'
      await self.event_bus.publish(LogEvent(
        agent_id='teamlead',
        event_type='response',
        message=questions,
        data={'needs_input': True},
      ))
      # 질문을 던지고 현재 상태 저장 — 사용자 응답 후 이어서 진행
      self._pending_project = {
        'user_input': user_input,
        'analysis': analysis,
        'meeting_summary': meeting_summary,
        'reference_context': reference_context,
        'briefing': briefing,
        'project_type': project_type.value,
        'phases': phases,
      }
      # DB에도 컨텍스트 저장 (서버 재시작 시 복구용)
      self._pending_task_id = getattr(self, '_current_task_id', '')
      if self._pending_task_id:
        from db.task_store import update_task_state
        update_task_state(self._pending_task_id, 'waiting_input', context=self._pending_project)
      self._state = OfficeState.IDLE
      return {
        'state': 'waiting_input',
        'response': questions,
        'artifacts': [],
      }

    # 질문 없으면 바로 전체 진행
    return await self._execute_project(
      user_input, analysis, meeting_summary, reference_context, briefing,
      phases=phases,
    )

  async def _continue_project(self, user_answer: str) -> dict[str, Any]:
    '''사용자 답변을 받아 중단된 프로젝트를 이어서 진행한다.'''
    pending = self._pending_project
    if not pending:
      return {'state': 'error', 'response': '진행 중인 프로젝트가 없습니다.', 'artifacts': []}

    # 사용자 답변을 컨텍스트에 추가
    meeting_summary = pending['meeting_summary'] + f'\n\n[사용자 확인사항]\n{user_answer}'

    # 저장된 phases 복원
    phases = pending.get('phases')

    self._pending_project = None

    return await self._execute_project(
      pending['user_input'],
      pending['analysis'],
      meeting_summary,
      pending['reference_context'],
      pending['briefing'],
      phases=phases,
    )

  async def _plan_project_phases(
    self,
    user_input: str,
    analysis: str,
    meeting_summary: str,
  ) -> list[dict]:
    '''팀장(Claude)이 회의 결과를 바탕으로 프로젝트에 맞는 단계를 동적 설계한다.

    Returns:
      프로젝트 단계 리스트. 파싱 실패 시 기존 기본 단계를 반환한다.
    '''
    from runners.json_parser import parse_json

    prompt = (
      '당신은 팀장입니다. 아래 프로젝트에 적합한 작업 단계를 설계하세요.\n\n'
      f'[프로젝트 지시]\n{user_input[:2000]}\n\n'
      f'[팀장 분석]\n{analysis[:1000]}\n\n'
      f'[회의 내용]\n{meeting_summary[:2000]}\n\n'
      '각 단계를 JSON으로 출력하세요:\n'
      '{"phases": [\n'
      '  {"name": "단계명", "description": "구체적 작업 지시",\n'
      '   "assigned_to": "planner|designer|developer",\n'
      '   "group": "그룹명", "output_format": "markdown|html|code"}\n'
      ']}\n\n'
      '규칙:\n'
      '- 프로젝트 유형에 맞게 필요한 단계만 포함 (웹사이트면 디자인 포함, 분석 보고서면 불필요)\n'
      '- assigned_to는 각 단계의 전문 영역에 맞는 팀원 배정\n'
      '- 같은 group의 단계들은 연속 배치 (그룹 끝에서 QA 검수 실행)\n'
      '- 최소 3단계, 최대 10단계\n'
      '- output_format: markdown(기본), html(웹페이지), html+pdf(보고서), md+code(코드 포함)\n\n'
      '예시 1 — 웹사이트 구축:\n'
      '{"phases": [\n'
      '  {"name": "기획-요구사항분석", "description": "사이트 목적/타겟 정의, 핵심 기능 도출", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "기획-IA설계", "description": "정보구조 설계, 사이트맵, 네비게이션 구조", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "기획-콘텐츠기획", "description": "페이지별 콘텐츠 구성, 와이어프레임", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "디자인-시스템설계", "description": "컬러/타이포/아이콘 디자인 시스템", "assigned_to": "designer", "group": "디자인", "output_format": "markdown"},\n'
      '  {"name": "디자인-레이아웃", "description": "주요 페이지 레이아웃 설계", "assigned_to": "designer", "group": "디자인", "output_format": "markdown"},\n'
      '  {"name": "디자인-컴포넌트", "description": "UI 컴포넌트 상세 명세", "assigned_to": "designer", "group": "디자인", "output_format": "markdown"},\n'
      '  {"name": "퍼블리싱-HTML구현", "description": "HTML/CSS/JS 구현", "assigned_to": "developer", "group": "퍼블리싱", "output_format": "html"}\n'
      ']}\n\n'
      '예시 2 — 분석 보고서:\n'
      '{"phases": [\n'
      '  {"name": "기획-범위정의", "description": "분석 범위, 목적, 방법론 정의", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "기획-조사설계", "description": "데이터 수집 계획, 분석 프레임워크", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "분석-데이터수집", "description": "관련 데이터/자료 수집 및 정리", "assigned_to": "developer", "group": "분석", "output_format": "md+code"},\n'
      '  {"name": "분석-분석실행", "description": "데이터 분석 수행 및 인사이트 도출", "assigned_to": "developer", "group": "분석", "output_format": "md+code"},\n'
      '  {"name": "취합-종합보고서", "description": "최종 분석 보고서 작성", "assigned_to": "planner", "group": "취합", "output_format": "html+pdf"}\n'
      ']}\n\n'
      '예시 3 — 앱/시스템 설계:\n'
      '{"phases": [\n'
      '  {"name": "기획-요구사항", "description": "기능/비기능 요구사항 정의", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "기획-아키텍처", "description": "시스템 아키텍처 설계", "assigned_to": "planner", "group": "기획", "output_format": "markdown"},\n'
      '  {"name": "설계-시스템설계", "description": "상세 시스템 설계 문서", "assigned_to": "developer", "group": "설계", "output_format": "markdown"},\n'
      '  {"name": "설계-API명세", "description": "API 엔드포인트 설계 및 명세", "assigned_to": "developer", "group": "설계", "output_format": "md+code"},\n'
      '  {"name": "개발-프로토타입", "description": "핵심 기능 프로토타입 구현", "assigned_to": "developer", "group": "개발", "output_format": "md+code"}\n'
      ']}\n\n'
      'JSON만 출력하세요. 설명이나 마크다운 없이 순수 JSON만.'
    )

    try:
      response = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=120.0)
      parsed = parse_json(response)
      if parsed and isinstance(parsed, dict) and 'phases' in parsed:
        phases = parsed['phases']
        # 유효성 검증: 최소 필수 키 확인
        valid = all(
          isinstance(p, dict) and p.get('name') and p.get('assigned_to') and p.get('group')
          for p in phases
        )
        if valid and len(phases) >= 3:
          # assigned_to 정규화 (유효한 에이전트만)
          valid_agents = {'planner', 'designer', 'developer'}
          for p in phases:
            if p['assigned_to'] not in valid_agents:
              p['assigned_to'] = 'planner'
            if 'output_format' not in p:
              p['output_format'] = 'markdown'
            if 'description' not in p:
              p['description'] = p['name']
          return phases
    except Exception:
      logger.debug("LLM 기반 단계 생성 실패, 기본 단계 사용", exc_info=True)

    # Fallback: 기존 phase_registry 기반
    return None

  def _default_phases(self, user_input: str) -> tuple[list[dict], str]:
    '''기본 단계 반환 — phases 미전달 시 하위호환용.'''
    project_type = self.improvement_engine.qa_adapter.classify_project_type(user_input)
    phases = self.improvement_engine.workflow_optimizer.get_phase_dicts(project_type, user_input)
    return phases, project_type

  async def _execute_project(
    self,
    user_input: str,
    analysis: str,
    meeting_summary: str,
    reference_context: str,
    briefing: str,
    phases: list[dict] | None = None,
  ) -> dict[str, Any]:
    '''프로젝트 전체 실행 — 유형별 동적 단계로 진행.'''

    # phases가 전달되지 않으면 기존 호환 로직
    if phases is not None:
      PHASES = phases
      project_type = 'web_development'
      for p in phases:
        if p.get('output_format', '').endswith('+pdf'):
          project_type = 'document'
          break
    else:
      PHASES, project_type = self._default_phases(user_input)
    self._current_project_type = project_type

    # 팀원 피드백 초기화
    self._phase_feedback = []

    # 프로젝트 메트릭 수집 시작
    _project_started_at = datetime.now(timezone.utc).isoformat()
    _phase_metrics: list[PhaseMetrics] = []

    all_results: dict[str, str] = {}
    phase_artifacts: list[str] = []
    prev_phase_result = ''
    _prev_group = ''
    _prev_agent = ''

    for phase in PHASES:
      phase_name = phase['name']
      agent_name = phase['assigned_to']
      agent = self.agents[agent_name]

      # 이미 완료된 단계는 스킵 (서버 재시작 후 중복 실행 방지)
      # 현재 workspace + 전체 workspace에서 가장 최신 산출물 검색
      existing_file = f'{phase_name}/{agent_name}-result.md'
      existing_content = ''
      found_task_id = ''
      try:
        # 1) 현재 workspace에서 먼저 찾기
        existing_path = self.workspace.task_dir / existing_file
        if existing_path.exists():
          existing_content = existing_path.read_text(encoding='utf-8')
          found_task_id = self.workspace.task_id

        # 2) 없으면 전체 workspace에서 가장 최신 찾기
        if not existing_content or len(existing_content) < 100:
          workspace_root = self.workspace.task_dir.parent
          latest_path = None
          latest_mtime = 0
          for ws_dir in workspace_root.iterdir():
            candidate = ws_dir / existing_file
            if candidate.exists() and candidate.stat().st_mtime > latest_mtime:
              latest_mtime = candidate.stat().st_mtime
              latest_path = candidate
              found_task_id = ws_dir.name
          if latest_path:
            existing_content = latest_path.read_text(encoding='utf-8')

        if existing_content and len(existing_content) > 100:
          all_results[phase_name] = existing_content
          prev_phase_result = existing_content
          phase_artifacts.append(f'{found_task_id}/{existing_file}')
          await self._emit('teamlead', f'{phase_name} 단계는 이미 완료되어 있습니다. 다음 단계로 넘어갑니다.', 'response')

          # 스킵해도 그룹 마지막이면 Stitch 시안 생성 체크
          current_group = phase.get('group', phase_name)
          remaining_in_group = [p for p in PHASES[PHASES.index(phase)+1:] if p.get('group') == current_group]
          _has_design_group = any(p.get('group') == '디자인' for p in PHASES)
          if not remaining_in_group and _has_design_group and current_group == '디자인':
            # Stitch 시안이 아직 없으면 생성
            # 전체 workspace에서 Stitch 시안 검색
            has_stitch = False
            workspace_root = self.workspace.task_dir.parent
            for ws_dir in workspace_root.iterdir():
              sd = ws_dir / 'stitch'
              if sd.exists() and any(sd.iterdir()):
                has_stitch = True
                break
            if not has_stitch and self._current_project_type in ('web_development', 'website'):
              await self._generate_stitch_mockup(all_results, user_input)
            elif has_stitch:
              await self._emit('designer', '이전에 생성된 Stitch 시안이 있습니다. 그대로 사용합니다. 🎨', 'response')
          continue
      except Exception:
        logger.debug("그룹 전환 처리 실패: %s", phase_name, exc_info=True)

      self._state = OfficeState.WORKING
      self._active_agent = agent_name
      self._work_started_at = datetime.now(timezone.utc).isoformat()
      self._current_phase = phase_name
      _phase_started_at = datetime.now(timezone.utc).isoformat()
      _phase_revision_count = 0
      await self._emit('teamlead', f'{phase_name} 단계를 시작합니다.', 'response')
      await self._emit(agent_name, '', 'typing')

      # 각 단계에 필요한 컨텍스트 구성
      current_group = phase.get('group', phase_name)

      # 프로젝트 설명: 첫 그룹(기획)에만 첨부 전문, 이후는 핵심만
      if current_group == '기획':
        project_text = user_input
      elif '[첨부된 참조 자료]' in user_input:
        project_text = user_input.split('[첨부된 참조 자료]')[0].strip()
      else:
        project_text = user_input

      phase_prompt = (
        f'[프로젝트]\n{project_text}\n\n'
        f'[현재 단계]\n{phase_name}: {phase["description"]}\n\n'
      )

      # 같은 그룹 내 이전 소단계 결과는 전문 전달
      same_group_results = [(k, v) for k, v in all_results.items() if current_group in k]
      if same_group_results:
        for k, v in same_group_results:
          phase_prompt += f'[이전 작업: {k}]\n{v}\n\n'

      # 다른 그룹의 산출물은 참조 가이드로 전달 (어디 문서의 어디 부분 참고하라)
      other_groups = set()
      for k, v in all_results.items():
        g = k.split('-')[0] if '-' in k else k
        if g != current_group and g not in other_groups:
          other_groups.add(g)
          group_results = {key: val for key, val in all_results.items() if key.startswith(g)}
          guide = await self._create_handoff_guide(g, group_results, phase_name)
          phase_prompt += f'[{g} 단계 참조 가이드]\n{guide}\n\n'

      if reference_context and current_group == '기획':
        phase_prompt += f'[참조 자료]\n{reference_context}\n\n'

      # output_format에 따른 작성 지침
      _of = phase.get('output_format', 'md')
      if _of in ('html', 'html+pdf'):
        format_instruction = (
          '마크다운으로 분석/설명을 작성하고, 최종 결과물은 반드시 ```html 코드블록으로 '
          '완성된 HTML 문서(<!DOCTYPE html>로 시작)를 포함하세요. '
          'HTML에는 CSS 스타일을 인라인으로 포함하여 보기 좋은 보고서 형태로 만드세요.'
        )
      elif _of == 'html_slide+pdf':
        format_instruction = (
          '마크다운으로 설명을 작성하고, 최종 결과물은 반드시 ```html 코드블록으로 '
          '슬라이드 형식의 HTML 문서를 포함하세요. '
          '각 슬라이드는 <section> 태그로 구분하고, CSS로 페이지 단위 스타일을 적용하세요.'
        )
      elif _of == 'md+code':
        format_instruction = (
          '마크다운 형식으로 작성하세요. '
          '분석에 사용한 Python 코드가 있으면 ```python 코드블록으로 포함하세요.'
        )
      else:
        format_instruction = '마크다운 형식으로 작성하세요.'

      phase_prompt += (
        f'위 내용을 바탕으로 {phase_name} 작업을 수행하세요.\n'
        f'실무에서 바로 활용할 수 있는 수준으로 상세하게 작성하세요.\n'
        f'{format_instruction}\n'
        f'중요: 반드시 모든 섹션을 끝까지 완성하세요. 절대 중간에 끊지 마세요.\n'
        f'착수 인사는 이미 채팅으로 전달했다. 산출물 본문만 바로 작성하라.'
      )

      # 팀원 피드백 주입
      if self._phase_feedback:
        feedback_lines = [f'- {fb["from"]}: {fb["content"][:100]}' for fb in self._phase_feedback[-5:]]
        phase_prompt += f'\n[팀원 피드백 — 가능한 반영할 것]\n' + '\n'.join(feedback_lines) + '\n\n'

      # 그룹 전환 시 인수인계 코멘트
      if _prev_group and current_group != _prev_group and _prev_agent != agent_name:
        await self._handoff_comment(_prev_agent, agent_name, phase_name)
      _prev_group = current_group
      _prev_agent = agent_name

      # 담당자 포부 한마디 + 착수 메시지
      await self._phase_intro(agent_name, phase_name)

      # 업무 수령 확인
      await self._task_acknowledgment(agent_name, phase_name)

      # 사용자 중간 피드백이 있으면 프롬프트에 주입
      if self._user_mid_feedback:
        feedback_text = '\n'.join(f'- {fb}' for fb in self._user_mid_feedback)
        phase_prompt += f'\n\n[사용자 중간 피드백 — 반드시 반영할 것]\n{feedback_text}\n'

      content = await agent.handle(phase_prompt)

      # 저장
      filename = f'{phase_name}/{agent_name}-result.md'
      try:
        self.workspace.write_artifact(filename, content)
        phase_artifacts.append(f'{self.workspace.task_id}/{filename}')
      except Exception:
        logger.warning("단계 산출물 저장 실패: %s", filename, exc_info=True)

      # output_format에 따른 산출물 추출 및 저장
      output_format = phase.get('output_format', 'md')
      import re as _re

      # 퍼블리싱 단계 또는 html/html+pdf 포맷: 코드블록에서 HTML 추출
      if current_group == '퍼블리싱' or output_format in ('html', 'html+pdf', 'html_slide+pdf'):
        html_match = _re.search(r'```(?:html)?\s*\n(<!DOCTYPE[\s\S]*?)\n```', content, _re.IGNORECASE)
        if not html_match:
          html_match = _re.search(r'```(?:html)?\s*\n(<html[\s\S]*?)\n```', content, _re.IGNORECASE)
        if html_match:
          html_code = html_match.group(1)
          html_filename = f'{phase_name}/index.html' if current_group == '퍼블리싱' else f'{phase_name}/result.html'
          try:
            html_file_path = self.workspace.write_artifact(html_filename, html_code)
            phase_artifacts.append(f'{self.workspace.task_id}/{html_filename}')
            html_url = f'/api/artifacts/{self.workspace.task_id}/{html_filename}'
            await self.event_bus.publish(LogEvent(
              agent_id=agent_name,
              event_type='response',
              message=f'{phase_name} HTML 산출물 생성 완료 👇\n{html_url}',
              data={'artifacts': [f'{self.workspace.task_id}/{html_filename}']},
            ))
            # PDF 변환
            if '+pdf' in output_format:
              try:
                from harness.pdf_converter import html_to_pdf
                pdf_path = html_to_pdf(html_file_path)
                pdf_rel = f'{phase_name}/result.pdf'
                phase_artifacts.append(f'{self.workspace.task_id}/{pdf_rel}')
                await self.event_bus.publish(LogEvent(
                  agent_id=agent_name,
                  event_type='response',
                  message=f'{phase_name} PDF 생성 완료 📄',
                  data={'artifacts': [f'{self.workspace.task_id}/{pdf_rel}']},
                ))
              except Exception:
                logger.warning("PDF 변환 실패: %s", phase_name, exc_info=True)
          except Exception:
            logger.warning("HTML 산출물 저장 실패: %s", phase_name, exc_info=True)

      # md+code 포맷: Python/JS 코드블록 추출
      if output_format == 'md+code':
        code_blocks = _re.findall(r'```(?:python|py)\s*\n([\s\S]*?)\n```', content)
        for i, code in enumerate(code_blocks):
          code_filename = f'{phase_name}/code_{i}.py'
          try:
            self.workspace.write_artifact(code_filename, code)
            phase_artifacts.append(f'{self.workspace.task_id}/{code_filename}')
          except Exception:
            logger.debug("코드 블록 저장 실패: %s", code_filename, exc_info=True)

      # HTML 출력 그룹 완료 시 멀티페이지 사이트 빌더 실행
      _is_html_output = phase.get('output_format', '') in ('html', 'html+pdf')
      if (current_group == '퍼블리싱' or _is_html_output) and self._current_project_type in ('web_development', 'website'):
        try:
          ia_content = next((v for k, v in all_results.items() if 'IA' in k), '')
          design_content = '\n'.join(v for k, v in all_results.items() if '디자인' in k)
          if ia_content:
            from harness.site_builder import build_multipage_site
            site_result = await build_multipage_site(
              ia_content=ia_content,
              design_specs=design_content,
              stitch_html=content if '<html' in content.lower() else None,
              workspace_dir=self.workspace.task_dir,
              project_brief=user_input[:500],
            )
            if site_result.get('pages'):
              for page_path in site_result['pages']:
                phase_artifacts.append(f'{self.workspace.task_id}/{page_path}')
              await self._emit('developer', f'멀티페이지 사이트 생성 완료 ({len(site_result["pages"])}페이지) 🌐', 'response')
        except Exception:
          logger.warning("멀티페이지 사이트 빌드 실패", exc_info=True)

      all_results[phase_name] = content
      prev_phase_result = content

      # 에이전트 간 @멘션 자동 라우팅 — 산출물에서 다른 에이전트에게 질문 감지
      try:
        await self._route_agent_mentions(agent_name, content[:3000])
      except Exception:
        logger.debug("에이전트 간 멘션 라우팅 실패: %s", phase_name, exc_info=True)

      # 단계 결과를 채팅에 요약 + 산출물 카드로 보고
      summary_lines = content.strip().split('\n')[:5]
      summary = '\n'.join(summary_lines)
      artifact_path = f'{self.workspace.task_id}/{filename}'
      await self.event_bus.publish(LogEvent(
        agent_id=agent_name,
        event_type='response',
        message=f'{phase_name} 작업 완료했습니다.\n\n{summary}',
        data={'artifacts': [artifact_path]},
      ))

      # 그룹 마지막 소단계인지 판단 (자문/피어리뷰는 그룹 마지막에서만)
      current_group = phase.get('group', phase_name)
      remaining_in_group = [p for p in PHASES[PHASES.index(phase)+1:] if p.get('group') == current_group]
      _is_group_last = not remaining_in_group

      if _is_group_last:
        # ── 그룹 마지막: 자문 → 피어리뷰 (실질적 협업) ──
        group_content = '\n\n'.join(v for k, v in all_results.items() if current_group in k)

        # 1) 타 팀원 자문
        consultation_feedback = await self._consult_peers(agent_name, group_content, phase, all_results)
        if consultation_feedback:
          # 자문 결과를 담당자에게 전달하여 보완 기회 제공
          await self._emit('teamlead', '자문 결과를 반영합니다.', 'response')
          self._user_mid_feedback.append(f'[팀원 자문 결과]\n{consultation_feedback}')

        # 2) 피어 리뷰 (실질적 피드백)
        peer_reviews = await self._peer_review(agent_name, phase_name, group_content, user_input)

        # 피어 리뷰에서 보완된 결과가 있으면 반영
        for review in peer_reviews:
          if review.get('revised') and review.get('content'):
            content = review['content']
            all_results[phase_name] = content
            try:
              self.workspace.write_artifact(filename, content)
            except Exception:
              logger.warning("피어 리뷰 보완 결과 저장 실패: %s", filename, exc_info=True)
            break
      else:
        # ── 소단계 중간: 경량 리액션 유지 ──
        await self._work_commentary(agent_name, phase_name, content)
        content_summary = '\n'.join(content.strip().split('\n')[:5])
        await self._team_reaction(agent_name, phase_name, content_summary=content_summary)

      # 사용자 중간 지시 확인 — 최근 채팅에서 사용자 메시지 체크
      user_directive = await self._check_user_directive()
      if user_directive:
        if user_directive.get('action') == 'stop':
          await self._emit('teamlead', '작업을 중단합니다. 여기까지의 산출물은 저장되어 있습니다.', 'response')
          self._state = OfficeState.COMPLETED
          self._active_agent = ''
          self._work_started_at = ''
          self._current_phase = ''
          return {
            'state': self._state.value,
            'response': '작업 중단',
            'artifacts': phase_artifacts,
          }
        elif user_directive.get('action') == 'mention_feedback':
          # @멘션 피드백 → 해당 에이전트가 짧게 응답 + 작업 컨텍스트에 반영
          from orchestration.meeting import MENTION_MAP
          feedback_msg = user_directive['message']
          for raw_mention in user_directive.get('mentions', []):
            target_id = MENTION_MAP.get(raw_mention) or MENTION_MAP.get(raw_mention.rstrip('님'))
            if not target_id or target_id == 'user':
              continue
            if target_id == 'teamlead':
              await self._emit('teamlead', '네, 확인했습니다. 반영하겠습니다.', 'response')
            else:
              mention_agent = self.agents.get(target_id)
              if mention_agent:
                try:
                  resp = await run_claude_isolated(
                    f'{mention_agent._build_system_prompt()}\n\n---\n\n'
                    f'작업 중인데 사용자가 이렇게 말했습니다:\n"{feedback_msg}"\n'
                    f'짧게 1~2문장으로 응답하세요 (메신저 톤, 마크다운 금지).',
                    model='claude-haiku-4-5-20251001', timeout=15.0,
                  )
                  await self._emit(target_id, resp.strip(), 'response')
                except Exception:
                  logger.debug("멘션 대상 응답 생성 실패: %s", target_id, exc_info=True)
                  await self._emit(target_id, '네, 확인했습니다.', 'response')
          self._user_mid_feedback.append(feedback_msg)
          await self._emit('teamlead', f'말씀하신 내용 반영하여 다음 단계 진행하겠습니다.', 'response')
        elif user_directive.get('message'):
          # 사용자 지시를 다음 소단계 프롬프트에 반영
          self._user_mid_feedback.append(user_directive['message'])
          meeting_summary += f'\n\n[사용자 중간 지시]\n{user_directive["message"]}'
          await self._emit('teamlead', f'말씀하신 내용 반영하여 다음 단계 진행하겠습니다.', 'response')

      # QA 검수 — 그룹의 마지막 소단계에서만 실행 (current_group, _is_group_last는 위에서 계산됨)
      if _is_group_last:
        # 그룹 마지막 → QA 검수
        self._state = OfficeState.QA_REVIEW
        self._active_agent = 'qa'
        await self._emit('qa', '', 'typing')
        qa_agent = self.agents['qa']
        from orchestration.task_graph import TaskNode
        group_content = '\n\n'.join(v for k, v in all_results.items() if current_group in k)
        node = TaskNode(
          task_id=f'group-{current_group}',
          description=f'{current_group} 전체 산출물',
          requirements=user_input,
          assigned_to=agent_name,
          depends_on=[],
        )
        node.artifact_paths = [filename]
        qa_passed = await self._run_qa_check(qa_agent, node, group_content)
        if not qa_passed:
          await self._emit('qa', f'{current_group} 검수 불합격: {node.failure_reason[:200]}', 'response')

          _phase_revision_count += 1
          # 보완 1회 — 불합격 사유를 담당 에이전트에게 전달하여 수정
          await self._emit('teamlead', f'{current_group} 보완 요청합니다.', 'response')
          self._state = OfficeState.REVISION
          self._active_agent = agent_name
          await self._emit(agent_name, '', 'typing')

          # 해당 그룹의 모든 소단계 산출물 + 불합격 사유로 보완 프롬프트 생성
          revision_prompt = (
            f'[프로젝트]\n{user_input}\n\n'
            f'[{current_group} 산출물]\n{group_content}\n\n'
            f'[QA 불합격 사유]\n{node.failure_reason}\n\n'
            f'위 불합격 사유를 반영하여 {current_group} 산출물을 보완하세요.\n'
            f'불합격 지적 사항을 모두 해결하고, 전체를 다시 작성하세요.\n'
            f'마크다운 형식으로 작성하세요.'
          )
          revised = await agent.handle(revision_prompt)

          # 보완 결과 저장 (마지막 소단계 파일에 덮어쓰기)
          try:
            self.workspace.write_artifact(filename, revised)
          except Exception:
            logger.warning("QA 보완 결과 저장 실패: %s", filename, exc_info=True)
          all_results[phase_name] = revised
          prev_phase_result = revised

          await self.event_bus.publish(LogEvent(
            agent_id=agent_name,
            event_type='response',
            message=f'{current_group} 보완 완료했습니다.',
            data={'artifacts': [f'{self.workspace.task_id}/{filename}']},
          ))
          await self._team_reaction(agent_name, f'{current_group}-보완')
        else:
          await self._emit('qa', f'{current_group} 검수 통과 ✅', 'response')

        # phase 메트릭 기록
        _phase_finished_at = datetime.now(timezone.utc).isoformat()
        try:
          from datetime import datetime as _dt
          _start = _dt.fromisoformat(_phase_started_at)
          _end = _dt.fromisoformat(_phase_finished_at)
          _dur = (_end - _start).total_seconds()
        except Exception:
          logger.debug("단계 소요시간 계산 실패", exc_info=True)
          _dur = 0.0
        _phase_metrics.append(PhaseMetrics(
          phase_name=phase_name,
          agent_name=agent_name,
          started_at=_phase_started_at,
          finished_at=_phase_finished_at,
          duration_seconds=_dur,
          qa_passed=qa_passed,
          revision_count=_phase_revision_count,
          group=current_group,
        ))

        # ── 크로스리뷰 — 다른 역할이 해당 그룹 산출물을 간단히 검토 ──
        await self._cross_review(current_group, all_results)

        # 디자인 그룹 완료 시 → 웹 개발 프로젝트만 Stitch 시안 생성
        _has_design_phases = any(p.get('group') == '디자인' for p in PHASES)
        if _has_design_phases and current_group == '디자인' and self._current_project_type in ('web_development', 'website'):
          await self._generate_stitch_mockup(all_results, user_input)

        # ── 그룹 경계 확인 — 다음 그룹이 있으면 사용자에게 진행 여부 확인 ──
        _remaining_phases = PHASES[PHASES.index(phase) + 1:]
        _next_group = next(
          (p.get('group', p['name']) for p in _remaining_phases
           if p.get('group', p['name']) != current_group),
          None,
        )
        if _next_group:
          confirm_msg = (
            f'✅ **{current_group}** 단계가 완료되었습니다.\n\n'
            f'다음은 **{_next_group}** 단계입니다. 이대로 진행할까요?\n'
            f'수정하거나 방향을 바꾸고 싶으신 사항이 있으시면 말씀해 주세요.'
          )
          await self.event_bus.publish(LogEvent(
            agent_id='teamlead',
            event_type='response',
            message=confirm_msg,
            data={'needs_input': True},
          ))
          # 상태 저장 — 재개 시 _execute_project 재호출, 완료 단계는 자동 스킵
          self._pending_project = {
            'user_input': user_input,
            'analysis': analysis,
            'meeting_summary': meeting_summary,
            'reference_context': reference_context,
            'briefing': briefing,
            'project_type': self._current_project_type,
            'phases': PHASES,
          }
          self._pending_task_id = getattr(self, '_current_task_id', '')
          if self._pending_task_id:
            from db.task_store import update_task_state
            update_task_state(self._pending_task_id, 'waiting_input', context=self._pending_project)
          self._state = OfficeState.IDLE
          self._active_agent = ''
          self._work_started_at = ''
          self._current_phase = ''
          return {
            'state': 'waiting_input',
            'response': confirm_msg,
            'artifacts': phase_artifacts,
          }

    # HTML 산출물이 포함된 프로젝트(사이트 구축)인지 판단
    has_publishing = (
      any('퍼블리싱' in k for k in all_results)
      or any(p.get('output_format') == 'html' for p in PHASES)
    )

    if has_publishing:
      # 사이트 구축 → 짧은 요약 + 산출물 링크
      await self._emit('teamlead', '최종 보고서를 작성하고 있습니다.', 'response')
      self._active_agent = 'teamlead'

      # 현재 프로젝트에서 사용된 산출물만 수집
      final_artifacts = list(phase_artifacts)

      # 각 단계별 제목(첫 마크다운 헤더)을 추출
      phase_summaries = []
      for name, content in all_results.items():
        title = '완료'
        for line in content.strip().split('\n'):
          stripped = line.strip()
          # 마크다운 헤더 우선
          if stripped.startswith('#'):
            title = stripped.lstrip('#').strip()[:80]
            break
          # 헤더 없으면 20자 이상 첫 줄 (서문/인사말 제외)
          skip_prefixes = ('알겠습니다', '네,', '안녕', 'I ', 'OK')
          if len(stripped) > 20 and not any(stripped.startswith(p) for p in skip_prefixes):
            title = stripped[:80]
            break
        phase_summaries.append(f'- **{name}**: {title}')

      # Haiku에게 전체 요약 (완료 시점 기준)
      try:
        overview = await run_claude_isolated(
          f'아래 프로젝트의 모든 단계가 완료되었습니다. 2~3문장으로 최종 완료 보고를 작성하세요.\n\n'
          + '\n'.join(phase_summaries) + '\n\n'
          f'과거형으로, 자연스러운 한국어로 작성하세요. 마크다운 금지.',
          model='claude-haiku-4-5-20251001',
          timeout=30.0,
        )
      except Exception:
        logger.debug("프로젝트 완료 요약 생성 실패", exc_info=True)
        overview = '모든 단계가 정상 완료되었습니다.'

      report_lines = [
        f'프로젝트가 완료되었습니다! 🎉\n',
        overview,
        '\n**단계별 결과:**',
        *phase_summaries,
        '\n**산출물:**',
        *[f'📄 {a.split("/", 1)[-1]}' for a in final_artifacts[:15]],
      ]
      await self.event_bus.publish(LogEvent(
        agent_id='teamlead',
        event_type='response',
        message='\n'.join(report_lines),
        data={'artifacts': final_artifacts},
      ))
    else:
      # 문서/분석 프로젝트 → 기획자가 최종 보고서 취합
      await self._emit('teamlead', '기획자에게 최종 보고서 작성을 요청합니다.', 'response')
      self._active_agent = 'planner'
      await self._emit('planner', '', 'typing')
      await self._run_planner_synthesize(user_input, all_results)

      # 팀장 최종 검수
      self._state = OfficeState.TEAMLEAD_REVIEW
      self._active_agent = 'teamlead'
      passed = await self._teamlead_final_review(user_input, None)

      if not passed:
        for _ in range(self.MAX_REVISION_ROUNDS):
          self._revision_count += 1
          await self._run_planner_synthesize(
            user_input, all_results, revision_feedback=self._last_review_feedback,
          )
          passed = await self._teamlead_final_review(user_input, None)
          if passed:
            break

    # 팀 회고 — 프로젝트 완료 후 각 에이전트가 배운 점 공유
    try:
      await self._team_retrospective(
        project_title=self._active_project_title or '프로젝트',
        project_type=project_type,
        all_results=all_results,
        user_input=user_input,
        duration=_total_dur if '_total_dur' in dir() else 0.0,
      )
    except Exception:
      logger.debug("팀 회고 실행 실패", exc_info=True)

    # 프로젝트 세션 종료
    if self._active_project_id:
      from db.task_store import archive_project
      archive_project(self._active_project_id)
      await self._emit('system', '📂 프로젝트 완료', 'project_close')
      self._active_project_id = None
      self._active_project_title = ''
      self._current_project_type = ''

    self._state = OfficeState.COMPLETED
    self._active_agent = ''
    self._work_started_at = ''
    self._current_phase = ''
    self._pending_project = None
    self._interrupted_instruction = None
    self._user_mid_feedback = []  # 피드백 초기화

    # 현재 task를 completed로 마킹 (서버 재시작 시 "이어하겠습니다" 방지)
    from db.task_store import update_task_state as _update_task
    task_id = getattr(self, '_current_task_id', '') or ''
    if task_id:
      _update_task(task_id, 'completed')

    # 자가개선: 프로젝트 메트릭 수집 및 분석
    _project_finished_at = datetime.now(timezone.utc).isoformat()
    try:
      _p_start = datetime.fromisoformat(_project_started_at)
      _p_end = datetime.fromisoformat(_project_finished_at)
      _total_dur = (_p_end - _p_start).total_seconds()
    except Exception:
      logger.debug("프로젝트 총 소요시간 계산 실패", exc_info=True)
      _total_dur = 0.0

    project_metrics = ProjectMetrics(
      task_id=task_id or 'unknown',
      project_type=project_type,
      instruction=user_input[:500],
      started_at=_project_started_at,
      finished_at=_project_finished_at,
      total_duration=_total_dur,
      phases=_phase_metrics,
      final_review_passed=True,
      final_review_rounds=self._revision_count,
    )
    try:
      await self.improvement_engine.on_project_complete(project_metrics)
    except Exception:
      logger.warning("자가개선 메트릭 수집 실패", exc_info=True)  # 자가개선 실패가 프로젝트 완료를 막지 않음

    # ── 자동 내보내기 — 산출물 PDF/DOCX/ZIP 생성 ──
    try:
      await self._auto_export(phase_artifacts)
    except Exception:
      logger.warning("자동 내보내기 실패", exc_info=True)

    return {
      'state': self._state.value,
      'response': '프로젝트 완료',
      'artifacts': phase_artifacts,
    }

  async def _auto_export(self, phase_artifacts: list[str]) -> None:
    '''프로젝트 완료 후 주요 산출물을 PDF/ZIP으로 자동 내보내기.'''
    from harness.export_engine import md_to_pdf, folder_to_zip

    task_dir = self.workspace.task_dir
    if not task_dir.exists():
      return

    exported = []

    # 최종 보고서 MD → PDF
    for md_file in task_dir.rglob('*result*.md'):
      if 'uploads' in str(md_file):
        continue
      content = md_file.read_text(encoding='utf-8', errors='replace')
      if len(content) < 200:
        continue
      try:
        pdf_name = md_file.stem + '.pdf'
        pdf_path = md_file.parent / pdf_name
        md_to_pdf(content, pdf_path, title=md_file.stem)
        exported.append(str(pdf_path.relative_to(task_dir)))
      except Exception:
        logger.debug("MD→PDF 변환 실패: %s", md_file.name, exc_info=True)
        continue

    # 전체 산출물 ZIP
    try:
      zip_path = task_dir / 'exports' / 'project-bundle.zip'
      folder_to_zip(task_dir, zip_path)
      exported.append('exports/project-bundle.zip')
    except Exception:
      logger.warning("프로젝트 ZIP 생성 실패", exc_info=True)

    if exported:
      files_text = ', '.join(exported[:5])
      await self._emit('system', f'📦 산출물 내보내기 완료: {files_text}', 'response')

  # 그룹별 크로스리뷰 매핑: 그룹 → (리뷰어, 관점)
  _CROSS_REVIEW_MAP: dict[str, tuple[str, str]] = {
    '기획': ('designer', 'UX/사용자 경험 관점에서 기획 산출물을 검토'),
    '디자인': ('developer', '기술 구현 가능성 관점에서 디자인 산출물을 검토'),
    '퍼블리싱': ('designer', '디자인 명세 준수 여부를 검토'),
  }

  async def _cross_review(self, group_name: str, all_results: dict[str, str]) -> None:
    '''그룹 완료 후 다른 역할의 에이전트가 간단히 크로스리뷰한다.'''
    review_config = self._CROSS_REVIEW_MAP.get(group_name)
    if not review_config:
      return

    reviewer_name, perspective = review_config
    reviewer = self.agents.get(reviewer_name)
    if not reviewer:
      return

    # 해당 그룹의 산출물 수집
    group_content = '\n\n'.join(
      f'[{k}]\n{v[:2000]}' for k, v in all_results.items() if group_name in k or k.startswith(group_name)
    )
    if not group_content:
      return

    try:
      await self._emit(reviewer_name, '', 'typing')
      review_prompt = (
        f'{perspective}하세요.\n\n'
        f'[{group_name} 산출물]\n{group_content[:6000]}\n\n'
        f'핵심 피드백을 2~3줄로 간결하게. 문제 없으면 "문제 없습니다" 한 줄.'
      )
      result = await run_claude_isolated(
        review_prompt, model='claude-haiku-4-5-20251001', timeout=30.0,
      )
      feedback = result.strip()
      if feedback and '문제 없' not in feedback:
        await self._emit(reviewer_name, f'[{group_name} 크로스리뷰] {feedback[:300]}', 'response')
      else:
        await self._emit(reviewer_name, f'{group_name} 산출물 확인했습니다 ✅', 'response')
    except Exception:
      logger.debug("크로스리뷰 실패: %s", group_name, exc_info=True)

  async def _extract_user_questions(self, user_input: str, meeting_summary: str) -> str:
    '''회의 내용에서 사용자에게 확인이 필요한 사항을 추출한다.'''
    prompt = (
      f'팀 회의가 끝났습니다. 당신은 팀장입니다.\n\n'
      f'[사용자 요청]\n{user_input}\n\n'
      f'[회의 내용]\n{meeting_summary}\n\n'
      f'회의에서 사용자에게 확인이 필요한 사항이 있습니까?\n'
      f'예: 사이트 목적(브랜딩/채용), 타겟 대상, 필수 기능, 디자인 선호도 등\n\n'
      f'확인이 필요하면 "@마스터"로 시작하여 자연스러운 메신저 톤으로 질문하세요 (2~4개 질문).\n'
      f'예시: "@마스터 몇 가지 확인이 필요합니다."\n'
      f'사용자 요청이 이미 충분히 구체적이면 [SKIP] 한 단어만 출력하세요.\n'
      f'마크다운 형식 사용하지 마세요.'
    )
    try:
      response = await run_claude_isolated(prompt, timeout=60.0, model='claude-haiku-4-5-20251001')
      text = response.strip()
      if text.upper().startswith('[SKIP]') or text.upper() == 'SKIP':
        return ''
      return text
    except Exception:
      logger.debug("사용자 확인 질문 추출 실패", exc_info=True)
      return ''

  async def _check_user_directive(self) -> dict | None:
    '''소단계 사이에 사용자가 보낸 메시지가 있는지 확인한다.

    Returns:
      None — 사용자 메시지 없음
      {'action': 'stop'} — 중단 요청
      {'message': str} — 방향 전환/추가 지시
    '''
    from db.log_store import load_logs

    recent = load_logs(limit=5)
    for log in recent:
      if log['agent_id'] != 'user':
        continue
      if log['event_type'] != 'message':
        continue
      msg = log['message'].strip()

      # 이미 처리한 메시지인지 (작업 시작 전 메시지는 무시)
      if not hasattr(self, '_last_checked_log_id'):
        self._last_checked_log_id = ''
      if log['id'] == self._last_checked_log_id:
        return None
      self._last_checked_log_id = log['id']

      # 중단 요청
      stop_keywords = ('중단', '멈춰', '그만', '스탑', 'stop', '취소')
      if any(kw in msg.lower() for kw in stop_keywords):
        return {'action': 'stop'}

      # @멘션 감지 → 해당 에이전트가 짧게 응답
      import re as _re_directive
      mentions = _re_directive.findall(r'@([가-힣A-Za-z]+(?:님)?)', msg)
      if mentions:
        return {'action': 'mention_feedback', 'message': msg, 'mentions': mentions}

      # 새로운 지시 (작업 관련 메시지)
      # "진행해", "ㅇㅇ" 등 단순 확인은 무시
      skip_keywords = ('진행', 'ㅇㅇ', '응', '네', 'ok', 'yes', '확인')
      if len(msg) > 5 and not any(msg.lower().strip() == kw for kw in skip_keywords):
        return {'message': msg}

    return None

  async def _team_reaction(self, worker: str, phase_name: str, content_summary: str = '') -> None:
    '''소단계 완료 후 다른 팀원이 성격 기반 맥락 리액션을 한다 (오피스 분위기).'''
    import asyncio
    import random
    summary_section = f'\n[작업 결과 요약]\n{content_summary[:300]}\n' if content_summary else ''

    # 작업자 외 팀원 중 1~2명이 리액션
    others = [n for n in ('teamlead', 'planner', 'designer', 'developer', 'qa') if n != worker]
    reactors = random.sample(others, min(random.choice([1, 1, 2]), len(others)))

    async def _react_one(reactor_name: str) -> tuple[str, str]:
      '''(reactor_name, 반응 텍스트) 반환. 실패 시 빈 문자열.'''
      try:
        agent = self.agents.get(reactor_name)
        system = agent._build_system_prompt() if agent else ''
        prompt = (
          f'{display_name(worker)}이(가) [{phase_name}] 작업을 완료했습니다.\n'
          f'{summary_section}'
          f'당신({display_name(reactor_name)})의 성격으로 동료로서 1문장 짧게 반응하세요.\n'
          f'20자 이내, 이모지 1개 포함, 메신저 톤. 마크다운 금지.'
        )
        full = f'{system}\n\n---\n\n{prompt}' if system else prompt
        response = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=20.0)
        return reactor_name, response.strip().split('\n')[0][:30]
      except Exception:
        logger.debug("팀 리액션 생성 실패: %s", reactor_name, exc_info=True)
        return reactor_name, ''

    # 병렬 실행
    results = await asyncio.gather(*[_react_one(r) for r in reactors], return_exceptions=False)

    first_reaction_text = ''
    first_reactor = ''
    for reactor_name, text in results:
      if not text:
        continue
      await self._emit(reactor_name, text, 'response')
      if not first_reaction_text:
        first_reaction_text = text
        first_reactor = reactor_name
      # 업무 관련 피드백 수집
      if any(kw in text for kw in ('체크', '확인', '검토', '반영', '수정', '추가', '고려', '필요', '개선')):
        self._phase_feedback.append({
          'from': display_name(reactor_name),
          'phase': phase_name,
          'content': text,
        })

    # 30% 확률로 잡담 (Haiku 생성)
    if random.random() < 0.3:
      meme_sender = random.choice(others)
      try:
        agent = self.agents.get(meme_sender)
        system = agent._build_system_prompt() if agent else ''
        prompt = (
          f'팀이 "{phase_name}" 작업을 진행 중입니다.\n'
          f'동료들에게 가볍게 잡담 한마디 해주세요 (커피, 날씨, 야근, 회식 등).\n'
          f'15자 이내, 이모지 1개, 메신저 톤. 마크다운 금지.'
        )
        full = f'{system}\n\n---\n\n{prompt}' if system else prompt
        response = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=15.0)
        meme = response.strip().split('\n')[0][:25]
        if meme:
          await self._emit(meme_sender, meme, 'response')
      except Exception:
        logger.debug("잡담 생성 실패", exc_info=True)

    # 대화 체인: 첫 리액터 이후 30% 확률로 다른 에이전트가 응답
    if first_reaction_text and random.random() < 0.3:
      chain_candidates = [n for n in others if n != first_reactor]
      if chain_candidates:
        chain_responder = random.choice(chain_candidates)
        try:
          agent = self.agents.get(chain_responder)
          system = agent._build_system_prompt() if agent else ''
          prompt = (
            f'동료 {display_name(first_reactor)}이(가) "{first_reaction_text}"라고 했습니다.\n'
            f'이에 대해 가볍게 한마디 응답하세요. 15자 이내, 메신저 톤. 마크다운 금지.'
          )
          full = f'{system}\n\n---\n\n{prompt}' if system else prompt
          response = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=15.0)
          chain_text = response.strip().split('\n')[0][:25]
          if chain_text:
            await self._emit(chain_responder, chain_text, 'response')
        except Exception:
          logger.debug("대화 체인 응답 생성 실패", exc_info=True)

  async def _consult_peers(
    self,
    worker_name: str,
    content: str,
    phase: dict,
    all_results: dict[str, str],
  ) -> str:
    '''그룹 마지막 단계 완료 후, 산출물에서 다른 팀원의 전문 확인이 필요한 사항을 감지하고 자문한다.

    Returns:
      자문 결과 텍스트. 자문 불필요 시 빈 문자열.
    '''
    from runners.json_parser import parse_json
    # 1. Haiku로 자문 필요 여부 빠르게 판단
    check_prompt = (
      '아래 산출물을 검토하세요. 다른 팀원의 전문 확인이 필요한 사항이 있으면 알려주세요.\n\n'
      f'[산출물 작성자] {worker_name}\n'
      f'[산출물 내용] {content[:3000]}\n\n'
      '다른 팀원에게 확인이 필요하면:\n'
      '{"needs_consultation": true, "consultations": [\n'
      '  {"target": "developer|designer|planner", "question": "구체적 질문"}\n'
      ']}\n\n'
      '확인 불필요하면: {"needs_consultation": false}\n\n'
      'JSON만 출력하세요.'
    )

    try:
      response = await run_claude_isolated(
        check_prompt, model='claude-haiku-4-5-20251001', timeout=30.0,
      )
      parsed = parse_json(response)
      if not parsed or not parsed.get('needs_consultation'):
        return ''

      consultations = parsed.get('consultations', [])
      if not consultations:
        return ''

      # 2. 각 대상에게 자문 수행
      consultation_results = []
      for consult in consultations[:2]:  # 최대 2건
        target = consult.get('target', '')
        question = consult.get('question', '')
        if not target or not question:
          continue

        # 유효한 에이전트인지 + 자기 자신에게 질문하지 않도록
        valid_targets = {'planner', 'designer', 'developer'}
        if target not in valid_targets or target == worker_name:
          continue

        agent = self.agents.get(target)
        if not agent:
          continue

        target_name_kr = display_name(target)
        worker_name_kr = display_name(worker_name)

        try:
          await self._emit(target, '', 'typing')
          consult_prompt = (
            f'{worker_name_kr}이(가) 작업 중 확인을 요청합니다:\n\n'
            f'"{question}"\n\n'
            f'전문가 관점에서 짧게 답변하세요 (2~3문장, 메신저 톤, 마크다운 금지).'
          )
          system = agent._build_system_prompt(task_hint=question)
          answer = await run_claude_isolated(
            f'{system}\n\n---\n\n{consult_prompt}',
            model='claude-haiku-4-5-20251001',
            timeout=30.0,
          )
          answer_text = answer.strip()[:300]
          if answer_text:
            await self._emit(target, answer_text, 'response')
            consultation_results.append(f'{target_name_kr}: {answer_text}')
            # 피드백 수집
            self._phase_feedback.append({
              'from': target_name_kr,
              'phase': phase.get('name', ''),
              'content': answer_text[:100],
            })
        except Exception:
          logger.debug("팀원 자문 실행 실패: %s", target, exc_info=True)

      return '\n'.join(consultation_results)

    except Exception:
      logger.debug("자문 필요 여부 판단 실패", exc_info=True)
      return ''

  # 피어 리뷰어 매핑: 작업자 역할 → 리뷰어 목록
  _PEER_REVIEWERS: dict[str, list[str]] = {
    'planner': ['designer', 'developer'],
    'designer': ['developer', 'planner'],
    'developer': ['designer', 'planner'],
  }

  async def _peer_review(
    self,
    worker_name: str,
    phase_name: str,
    content: str,
    user_input: str,
  ) -> list[dict]:
    '''그룹 완료 시 관련 팀원 1~2명이 실질적 피어 리뷰를 수행한다.

    Returns:
      리뷰 결과 리스트. [CONCERN] 태그가 있으면 심각한 우려사항.
    '''
    # 리뷰어 선정: 작업자 외 관련 팀원 1~2명
    reviewer_ids = self._PEER_REVIEWERS.get(worker_name, ['planner', 'developer'])
    # 최대 2명
    reviewer_ids = reviewer_ids[:2]

    reviews = []
    concern_detected = False

    for reviewer_id in reviewer_ids:
      reviewer_name_kr = display_name(reviewer_id)
      worker_name_kr = display_name(worker_name)

      try:
        await self._emit(reviewer_id, '', 'typing')
        review_prompt = (
          f'팀원 {worker_name_kr}이(가) {phase_name} 작업을 완료했습니다.\n\n'
          f'[프로젝트] {user_input[:500]}\n'
          f'[산출물 요약] {content[:2000]}\n\n'
          f'당신({reviewer_name_kr})의 전문 관점에서 이 산출물에 대해 짧게 코멘트하세요.\n'
          f'- 좋은 점이 있으면 구체적으로 칭찬\n'
          f'- 자신의 다음 작업에 영향을 주는 사항이 있으면 언급\n'
          f'- 우려 사항이 있으면 건설적으로 지적\n\n'
          f'1~2문장으로, 메신저 대화 톤으로. 마크다운 금지.\n'
          f'심각한 문제가 있으면 문장 끝에 [CONCERN]을 붙이세요.'
        )
        response = await run_claude_isolated(
          review_prompt, model='claude-haiku-4-5-20251001', timeout=30.0,
        )
        feedback = response.strip().split('\n')[0][:200]
        if feedback:
          await self._emit(reviewer_id, feedback, 'response')
          has_concern = '[CONCERN]' in feedback
          if has_concern:
            concern_detected = True
          reviews.append({
            'reviewer': reviewer_id,
            'feedback': feedback.replace('[CONCERN]', '').strip(),
            'concern': has_concern,
          })
          # 피드백 수집
          self._phase_feedback.append({
            'from': reviewer_name_kr,
            'phase': phase_name,
            'content': feedback.replace('[CONCERN]', '').strip(),
          })
      except Exception:
        logger.debug("피어 리뷰 실행 실패: %s", reviewer_id, exc_info=True)

    # [CONCERN] 감지 시 담당자에게 보완 기회 1회 제공
    if concern_detected:
      concern_items = [r['feedback'] for r in reviews if r.get('concern')]
      concern_text = '\n'.join(f'- {item}' for item in concern_items)
      worker_name_kr = display_name(worker_name)
      await self._emit('teamlead', f'{worker_name_kr}, 피어 리뷰에서 우려 사항이 나왔습니다. 확인 부탁합니다.', 'response')

      try:
        agent = self.agents.get(worker_name)
        if agent:
          await self._emit(worker_name, '', 'typing')
          revision_prompt = (
            f'[프로젝트] {user_input[:500]}\n\n'
            f'[당신의 산출물] {content[:3000]}\n\n'
            f'[피어 리뷰 우려사항]\n{concern_text}\n\n'
            f'위 우려사항을 반영하여 산출물을 보완하세요.\n'
            f'전체를 다시 작성하되, 우려사항을 해결하세요.'
          )
          revised = await agent.handle(revision_prompt)
          if revised and len(revised) > 100:
            await self._emit(worker_name, f'{phase_name} 피어 리뷰 반영 완료했습니다.', 'response')
            reviews.append({'revised': True, 'content': revised})
      except Exception:
        logger.warning("피어 리뷰 우려사항 보완 실패: %s", worker_name, exc_info=True)

    return reviews

  async def _handoff_comment(self, from_agent: str, to_agent: str, phase_name: str) -> None:
    '''그룹 전환 시 이전 담당자가 다음 담당자에게 인수인계 코멘트를 남긴다.'''
    from_name = display_name(from_agent)
    to_name = display_name(to_agent)
    try:
      response = await run_claude_isolated(
        f'당신은 {from_name}입니다.\n'
        f'다음 단계 "{phase_name}"을(를) {to_name}이(가) 담당합니다.\n'
        f'전문가로서 인수인계 시 주의사항이나 팁을 한마디 전달하세요.\n'
        f'"@{to_name} [팁/주의사항]" 형태로. 40자 이내, 메신저 톤. 마크다운 금지.',
        model='claude-haiku-4-5-20251001',
        timeout=15.0,
      )
      text = response.strip().split('\n')[0][:60]
      if text:
        await self._emit(from_agent, text, 'response')
        # 인수인계 코멘트도 피드백에 수집
        self._phase_feedback.append({
          'from': from_name,
          'phase': phase_name,
          'content': text,
        })
    except Exception:
      logger.debug("인수인계 코멘트 생성 실패: %s → %s", from_agent, to_agent, exc_info=True)

  async def _task_acknowledgment(self, agent_name: str, phase_name: str) -> None:
    '''업무 수령 시 담당자가 간단한 확인 메시지를 보낸다.'''
    try:
      response = await run_claude_isolated(
        f'당신은 {display_name(agent_name)}입니다.\n'
        f'팀장이 "{phase_name}" 작업을 지시했습니다.\n'
        f'"네, 확인했습니다. [간단한 계획 한 줄]" 형태로 수령 확인하세요.\n'
        f'30자 이내, 메신저 톤. 마크다운 금지.',
        model='claude-haiku-4-5-20251001',
        timeout=15.0,
      )
      text = response.strip().split('\n')[0][:50]
      if text:
        await self._emit(agent_name, text, 'response')
    except Exception:
      logger.debug("업무 수령 확인 생성 실패: %s", agent_name, exc_info=True)
      await self._emit(agent_name, '네, 확인했습니다. 시작하겠습니다.', 'response')

  async def _contextual_reaction(self, reactor: str, phase_name: str, worker: str) -> str:
    '''Haiku로 해당 캐릭터가 할 법한 문맥 리액션 한마디 생성 (15자 이내).'''
    try:
      response = await run_claude_isolated(
        f'당신은 {display_name(reactor)}입니다.\n'
        f'{worker}이(가) "{phase_name}" 작업을 완료했습니다.\n'
        f'동료로서 가볍게 리액션 한마디 해주세요.\n'
        f'15자 이내, 이모지 1개 포함, 메신저 톤. 마크다운 금지.\n'
        f'예: "레이아웃 깔끔하네요 👍", "구현 문제없어 보여요 💪"',
        model='claude-haiku-4-5-20251001',
        timeout=15.0,
      )
      text = response.strip().split('\n')[0][:30]
      return text if text else ''
    except Exception:
      logger.debug("문맥 리액션 생성 실패: %s", reactor, exc_info=True)
      return ''

  # QUICK_TASK 보완 의견 기본 매핑: 담당자 → (기본 리뷰어, 관점)
  _SECOND_OPINION_MAP: dict[str, tuple[str, str]] = {
    'developer': ('planner', '기획/전략 관점에서 빠진 부분이 없는지'),
    'planner':   ('developer', '기술적 정확성과 실현 가능성 관점에서'),
    'designer':  ('developer', '기술 구현 관점에서'),
  }

  # 태스크 키워드 → 리뷰어 오버라이드: 업무 내용에 맞는 전문가가 자문
  _KEYWORD_REVIEWER_MAP: list[tuple[list[str], str, str]] = [
    (
      ['디자인', 'UI', 'UX', '비주얼', '화면', '색상', '레이아웃', '트렌드', '브랜드', '폰트'],
      'designer',
      '디자인/UX 관점에서 보완할 부분이 있는지',
    ),
    (
      ['코드', '개발', 'API', '아키텍처', '데이터베이스', '서버', '프론트', '백엔드', '기술'],
      'developer',
      '기술적 정확성과 구현 가능성 관점에서',
    ),
    (
      ['기획', '전략', '로드맵', '시장', '사용자', '요구사항', '시나리오'],
      'planner',
      '기획/전략 관점에서 빠진 부분이 없는지',
    ),
  ]

  def _resolve_reviewer(self, worker: str, prompt: str) -> tuple[str, str] | None:
    '''업무 내용 키워드 기반으로 리뷰어를 결정한다. 자기 자신은 제외.'''
    for keywords, reviewer, perspective in self._KEYWORD_REVIEWER_MAP:
      if reviewer == worker:
        continue  # 자기 자신에게 자문 요청 불가
      if any(kw in prompt for kw in keywords):
        return reviewer, perspective
    # 키워드 매칭 없으면 기본 매핑 사용
    config = self._SECOND_OPINION_MAP.get(worker)
    if config and config[0] != worker:
      return config
    return None

  async def _quick_task_second_opinion(
    self,
    worker: str,
    prompt: str,
    result: str,
    worker_agent: 'Agent | None' = None,
    ctx_parts: list[str] | None = None,
  ) -> str:
    '''QUICK_TASK 결과에 관련 전문가가 내용을 기여하고, 담당자가 결과물을 보강한다.

    흐름:
      1. 리뷰어가 자신의 전문 관점 내용(보완 섹션)을 생성
      2. 의미 있는 내용이면 담당자에게 전달 → 담당자가 결과물에 반영
      3. 보강된 결과물 반환 (변경 없으면 원본 반환)
    '''
    config = self._resolve_reviewer(worker, prompt)
    if not config:
      return result

    reviewer_name, perspective = config
    reviewer = self.agents.get(reviewer_name)
    if not reviewer:
      return result

    # ── Step 1: 리뷰어가 전문 내용 기여 ──
    try:
      await self._emit(reviewer_name, '', 'typing')
      system = reviewer._build_system_prompt(task_hint=prompt)
      contribute_prompt = (
        f'{perspective} 관점에서 아래 산출물에 추가할 내용을 작성하세요.\n\n'
        f'[원본 요청]\n{prompt[:500]}\n\n'
        f'[현재 산출물]\n{result[:2000]}\n\n'
        f'[지시]\n'
        f'- 당신의 전문 영역({reviewer_name})에서만 기여하세요\n'
        f'- 이미 잘 다뤄진 내용은 반복하지 마세요\n'
        f'- 추가할 내용이 있으면 구체적으로 작성하세요 (제목 포함)\n'
        f'- 추가할 내용이 없으면 "없음"만 출력하세요'
      )
      full = f'{system}\n\n---\n\n{contribute_prompt}' if system else contribute_prompt
      resp = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=40.0)
      contribution = resp.strip()
    except Exception:
      logger.debug("보완 의견 생성 실패: %s", reviewer_name, exc_info=True)
      return result

    # 의미 없는 응답 필터
    if not contribution or contribution in ('없음', '없음.') or len(contribution) < 10:
      await self._emit(reviewer_name, '내용 충실하네요 👍', 'response')
      return result

    # 채팅에 기여 사실 알림
    await self._emit(
      reviewer_name,
      f'{perspective} 관점에서 보완 내용 추가했습니다.',
      'response',
    )

    # ── Step 2: 담당자가 기여 내용을 반영해 결과물 보강 ──
    if not worker_agent:
      return result

    try:
      self._active_agent = worker
      await self._emit(worker, '', 'typing')
      revise_prompt = (
        f'[원본 요청]\n{prompt}\n\n'
        f'[현재 산출물]\n{result}\n\n'
        f'[{display_name(reviewer_name)}의 보완 내용]\n{contribution}\n\n'
        f'위 보완 내용을 산출물에 자연스럽게 통합하여 완성본을 작성하세요.\n'
        f'원본 구조를 유지하면서 보완 내용을 적절한 위치에 녹여 넣으세요.'
      )
      ctx = '\n\n'.join(ctx_parts) if ctx_parts else ''
      updated = await worker_agent.handle(revise_prompt, context=ctx)
      await self._emit(
        worker,
        f'{display_name(reviewer_name)} 의견 반영해서 보강했습니다.',
        'response',
      )
      return updated
    except Exception:
      logger.warning("보완 내용 반영 실패: %s", worker, exc_info=True)
      return result

  async def _work_commentary(self, worker: str, phase_name: str, result_preview: str) -> None:
    '''작업 완료 직후 관련 팀원 1명이 결과물 기반 전문 의견을 짧게 끼어든다.

    발동 확률: 40%. 매번 나오면 지루하므로 확률적으로 동작한다.
    '''
    import random
    if random.random() > 0.4:
      return

    # 작업자와 다른 관련 팀원 선정
    commentary_map = {
      'planner': ['designer', 'developer'],
      'designer': ['developer', 'planner'],
      'developer': ['designer', 'qa'],
      'qa': ['developer', 'planner'],
    }
    candidates = commentary_map.get(worker, ['planner'])
    commenter = random.choice(candidates)
    try:
      response = await run_claude_isolated(
        f'당신은 {display_name(commenter)}입니다.\n'
        f'{display_name(worker)}이(가) "{phase_name}" 작업을 완료했습니다.\n'
        f'결과물 미리보기:\n{result_preview[:300]}\n\n'
        f'전문가 관점에서 짧게 한마디 의견을 주세요 (30자 이내, 메신저 톤, 마크다운 금지).\n'
        f'예: "이 레이아웃 구현 문제없어 보입니다 👍", "접근성도 잘 잡혔네요 ✅"',
        model='claude-haiku-4-5-20251001',
        timeout=15.0,
      )
      text = response.strip().split('\n')[0][:50]
      if text:
        await self._emit(commenter, text, 'response')
    except Exception:
      logger.debug("작업 코멘터리 생성 실패", exc_info=True)

  async def _phase_intro(self, agent_name: str, phase_name: str) -> None:
    '''프로젝트 각 단계 시작 시 담당 에이전트가 작업 포부/계획을 한마디 한다.'''
    fallback_intros = {
      'planner': '기획 구조 잡아볼게요 📋',
      'designer': '디자인 방향 잡겠습니다 🎨',
      'developer': '코드 작성 들어갑니다 💻',
      'qa': '검수 기준 세우겠습니다 🔍',
    }
    try:
      response = await run_claude_isolated(
        f'당신은 {display_name(agent_name)}입니다.\n'
        f'"{phase_name}" 작업을 시작합니다.\n'
        f'동료들에게 작업 포부를 한마디 해주세요 (20자 이내, 메신저 톤, 이모지 1개, 마크다운 금지).\n'
        f'예: "사용자 동선 꼼꼼히 잡아볼게요 🎯", "반응형까지 깔끔하게 가겠습니다 💪"',
        model='claude-haiku-4-5-20251001',
        timeout=10.0,
      )
      text = response.strip().split('\n')[0][:30]
      if text:
        await self._emit(agent_name, text, 'response')
        return
    except Exception:
      logger.debug("단계 시작 포부 생성 실패: %s", agent_name, exc_info=True)
    # 폴백
    await self._emit(agent_name, fallback_intros.get(agent_name, '시작하겠습니다 🚀'), 'response')

  async def handle_mid_work_input(self, user_input: str) -> None:
    '''작업 진행 중 사용자가 보낸 메시지를 처리한다.

    3가지 경우를 판단:
    1. @멘션 피드백 → 해당 에이전트가 즉시 응답
    2. 일반 대화/의견 → 팀장이 확인 + 작업 컨텍스트에 반영
    3. 중단/방향전환 → 기존 _check_user_directive 로직
    '''
    import re
    from orchestration.meeting import MENTION_MAP

    msg = user_input.strip()

    # 중단 요청 확인
    stop_keywords = ('중단', '멈춰', '그만', '스탑', 'stop', '취소')
    if any(kw in msg.lower() for kw in stop_keywords):
      await self._emit('teamlead', '작업을 중단하겠습니다.', 'response')
      self._state = OfficeState.IDLE
      self._active_agent = ''
      self._work_started_at = ''
      self._current_phase = ''
      return

    # @멘션 파싱
    mentions = re.findall(r'@([가-힣A-Za-z]+(?:님)?)', msg)
    if mentions:
      for raw_mention in mentions:
        target_id = MENTION_MAP.get(raw_mention)
        if not target_id:
          stripped = raw_mention.rstrip('님')
          target_id = MENTION_MAP.get(stripped)
        if not target_id or target_id == 'user':
          continue

        if target_id == 'teamlead':
          # 팀장에게 멘션 → Claude가 응답
          try:
            response = await run_claude_isolated(
              f'당신은 팀장 잡스입니다. 팀이 작업 중인데 사용자가 이렇게 말했습니다:\n'
              f'"{msg}"\n짧게 1~2문장으로 응답하세요 (메신저 톤, 마크다운 금지).',
              model='claude-haiku-4-5-20251001',
              timeout=15.0,
            )
            await self._emit('teamlead', response.strip(), 'response')
          except Exception:
            logger.debug("팀장 멘션 응답 생성 실패", exc_info=True)
            await self._emit('teamlead', '네, 확인했습니다. 반영하겠습니다.', 'response')
        else:
          # 특정 에이전트에게 멘션
          agent = self.agents.get(target_id)
          if agent:
            system = agent._build_system_prompt()
            try:
              response = await run_claude_isolated(
                f'{system}\n\n---\n\n'
                f'작업 중인데 사용자(상사)가 당신에게 이렇게 말했습니다:\n'
                f'"{msg}"\n짧게 1~2문장으로 응답하세요 (메신저 톤, 마크다운 금지).',
                model='claude-haiku-4-5-20251001',
                timeout=15.0,
              )
              await self._emit(target_id, response.strip(), 'response')
            except Exception:
              logger.debug("에이전트 멘션 응답 생성 실패: %s", target_id, exc_info=True)
              await self._emit(target_id, '네, 확인했습니다. 반영하겠습니다.', 'response')

      # 피드백을 작업 컨텍스트에 축적
      self._user_mid_feedback.append(msg)
      return

    # @멘션 없는 일반 의견/피드백
    self._user_mid_feedback.append(msg)
    await self._emit('teamlead', f'말씀 확인했습니다. 작업에 반영하겠습니다.', 'response')

  async def _create_handoff_guide(self, group_name: str, group_results: dict[str, str], target_phase: str) -> str:
    '''이전 그룹의 산출물에서 다음 단계에 필요한 참조 가이드를 생성한다.

    요약이 아니라 "어느 작업 시 어느 문서의 어느 부분을 참고하라"는 지시서.
    '''
    # 각 문서의 섹션 목차를 추출
    doc_sections = []
    for doc_name, content in group_results.items():
      # 마크다운 헤더를 추출하여 목차 구성
      headers = [line.strip() for line in content.split('\n') if line.strip().startswith('#')]
      doc_sections.append(f'[{doc_name}] 섹션 목록:\n' + '\n'.join(headers[:20]))

    sections_text = '\n\n'.join(doc_sections)

    try:
      guide = await run_claude_isolated(
        f'당신은 팀장입니다. "{target_phase}" 담당자에게 작업 지시를 내려야 합니다.\n\n'
        f'아래는 "{group_name}" 단계에서 완료된 문서들의 섹션 목록입니다:\n\n'
        f'{sections_text}\n\n'
        f'"{target_phase}" 작업을 수행할 때 어떤 문서의 어떤 섹션을 참고해야 하는지 '
        f'구체적으로 지시하세요.\n\n'
        f'형식:\n'
        f'- [작업 항목] → [문서명]의 [섹션명] 참고\n'
        f'- 해당 섹션에서 꼭 확인해야 할 핵심 스펙(수치, 구조 등)을 한 줄로 명시\n\n'
        f'예시:\n'
        f'- 네비게이션 마크업 → 기획-IA설계의 "GNB 구조" 참고 (1뎁스 6개: 기관소개/사업안내/...)\n'
        f'- CSS 변수 정의 → 디자인-시스템의 "컬러 팔레트" 참고 (Primary: #1B4F72, Secondary: #2ECC71)\n',
        model='claude-haiku-4-5-20251001',
        timeout=60.0,
      )
      return guide
    except Exception:
      logger.warning("인수인계 가이드 생성 실패, 목차로 대체", exc_info=True)
      # 실패 시 목차라도 전달
      return sections_text

  async def _generate_stitch_mockup(self, all_results: dict, user_input: str) -> None:
    '''디자인 산출물을 바탕으로 Stitch 시안을 생성하고, 개발 단계에 전달한다.'''
    try:
      await self._emit('designer', '디자인 시안을 생성하고 있습니다... 🎨', 'response')
      self._state = OfficeState.WORKING
      self._active_agent = 'designer'
      self._work_started_at = datetime.now(timezone.utc).isoformat()

      # 디자인 관련 산출물 취합
      design_context_parts = []
      for key in sorted(all_results.keys()):
        if '디자인' in key or '기획' in key:
          design_context_parts.append(f'[{key}]\n{all_results[key]}')

      design_context = '\n\n'.join(design_context_parts)

      # 사용자 요청에서 첨부 제외한 핵심만
      project_brief = user_input.split('[첨부된 참조 자료]')[0].strip() if '[첨부된 참조 자료]' in user_input else user_input

      stitch_result = await designer_generate_with_context(
        design_context=f'[프로젝트]\n{project_brief}\n\n{design_context}',
        task_id=self.workspace.task_id,
        workspace_root=str(self.workspace.task_dir.parent),
      )

      if stitch_result.get('success'):
        stitch_artifacts = []
        if stitch_result.get('html_path'):
          stitch_artifacts.append(f'{self.workspace.task_id}/stitch/design.html')
          # 시안 HTML을 all_results에 추가 → 개발 단계에서 참조
          try:
            html_content = Path(stitch_result['html_path']).read_text(encoding='utf-8')
            all_results['디자인-시안HTML'] = html_content
          except Exception:
            logger.debug("Stitch 시안 HTML 읽기 실패", exc_info=True)
        if stitch_result.get('image_path'):
          stitch_artifacts.append(f'{self.workspace.task_id}/stitch/design.png')
        await self.event_bus.publish(LogEvent(
          agent_id='designer',
          event_type='response',
          message='디자인 시안이 생성되었습니다! 개발자에게 전달합니다. 🎉',
          data={'artifacts': stitch_artifacts},
        ))
        await self._team_reaction('designer', '시안 생성')
      else:
        error = stitch_result.get('error', '알 수 없는 오류')[:200]
        await self._emit('designer', f'시안 생성을 건너뜁니다 (Stitch: {error})', 'response')
    except Exception as e:
      logger.warning("Stitch 시안 생성 실패", exc_info=True)
      await self._emit('designer', f'시안 생성을 건너뜁니다 ({str(e)[:100]})', 'response')

  async def _run_qa_check(self, qa_agent: Agent, node: TaskNode, content: str) -> bool:
    '''QA 에이전트가 산출물을 검수한다 (내부 처리 — 채팅에 안 보임).'''
    qa_prompt = (
      f'[원본 요구사항]\n{node.requirements}\n\n'
      f'[작업 결과물]\n{content}\n\n'
      f'위 요구사항 대비 결과물을 검수하세요.'
    )
    qa_result = await qa_agent.handle(qa_prompt)

    # JSON 파싱 시도
    passed = True
    try:
      # JSON 부분 추출
      import re
      json_match = re.search(r'\{[^{}]*\}', qa_result, re.DOTALL)
      if json_match:
        qa_json = json.loads(json_match.group())
        if qa_json.get('status') == 'fail':
          passed = False
          node.failure_reason = qa_json.get('failure_reason', 'QA 불합격')
    except (json.JSONDecodeError, AttributeError):
      # JSON 파싱 실패 시 텍스트에서 판단
      if '불합격' in qa_result or 'fail' in qa_result.lower():
        passed = False
        node.failure_reason = qa_result[:300]

    return passed

  async def _run_planner_synthesize(
    self,
    user_input: str,
    worker_results: dict[str, str],
    revision_feedback: str = '',
  ) -> None:
    '''기획자가 작업 결과를 취합하여 최종 산출물을 작성한다.'''
    planner = self.agents['planner']
    system = planner._build_system_prompt(task_hint=user_input)
    results_text = '\n\n'.join(worker_results.values())

    revision_section = ''
    if revision_feedback:
      revision_section = f'[팀장 보완 지시 — 반드시 반영할 것]\n{revision_feedback}\n\n'

    prompt = (
      f'[사용자 원본 지시]\n{user_input}\n\n'
      f'{revision_section}'
      f'[각 구성원의 작업 결과]\n{results_text}\n\n'
      f'[지시사항 — 절대 규칙]\n'
      f'1. 각 구성원의 분석 내용을 요약하지 말고 전문 포함\n'
      f'2. 기획자로서 프로젝트 개요, 섹션 간 연결, 실행 로드맵을 추가\n'
      f'3. 최소 3000자 이상 작성\n'
      f'4. 모든 섹션을 끝까지 완성하라. 문장이 중간에 잘리면 절대 안 된다\n'
      f'5. 오탈자 없이 정확한 한국어로 작성하라\n'
      f'{("6. 팀장 보완 지시 반영: " + revision_feedback[:500] if revision_feedback else "")}\n\n'
      f'마크다운 형식으로 직접 작성하세요.'
    )

    try:
      raw = await run_claude_isolated(f'{system}\n\n---\n\n{prompt}')
    except Exception:
      logger.warning("기획자 취합 Claude 실행 실패, Gemini 폴백", exc_info=True)
      raw = await run_gemini(prompt=prompt, system=system)
    content = raw.strip()
    if content.startswith('```'):
      lines = content.split('\n')
      lines = lines[1:]
      if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
      content = '\n'.join(lines)

    try:
      self.workspace.write_artifact('final/result.md', content)
    except Exception:
      logger.warning("최종 산출물 저장 실패", exc_info=True)

  async def _teamlead_final_review(self, user_input: str, task_graph: TaskGraph) -> bool:
    '''팀장(Claude)이 최종 산출물을 검수한다.'''
    final_path = self.workspace.task_dir / 'final' / 'result.md'
    if not final_path.exists():
      self._last_review_feedback = '최종 산출물 파일이 없습니다.'
      return False

    final_content = final_path.read_text(encoding='utf-8')
    if len(final_content) < 500:
      self._last_review_feedback = f'산출물이 너무 짧습니다 ({len(final_content)}자). 최소 3000자 이상 필요.'
      return False

    prompt = (
      f'[사용자 원본 요구사항]\n{user_input}\n\n'
      f'[최종 산출물]\n{final_content[:12000]}\n\n'
      f'위 요구사항 대비 산출물의 완성도를 검수하세요.\n\n'
      f'[체크리스트]\n'
      f'1. 요구사항의 핵심 항목이 모두 반영되었는가?\n'
      f'2. 산출물이 실무에서 바로 활용 가능한 수준인가?\n'
      f'3. 내용이 충분히 구체적이고 상세한가?\n'
      f'4. 논리적 비약이나 누락된 부분이 없는가?\n\n'
      f'합격이면 첫 줄에 [PASS]를, 불합격이면 [FAIL]을 적고 이유를 적으세요.'
    )

    response = await run_claude_isolated(prompt, timeout=60.0, model='claude-haiku-4-5-20251001')
    text = response.strip()

    if text.startswith('[PASS]') or '[PASS]' in text[:100]:
      self._last_review_feedback = ''
      # 보완 사유 분석 및 기록
      if self._revision_count > 0:
        record_rejection(self._last_review_feedback, 'final_review', str(self._memory_root))
      return True

    # 불합격
    self._last_review_feedback = text.replace('[FAIL]', '').strip()[:500]
    record_rejection(self._last_review_feedback, 'final_review', str(self._memory_root))
    return False

  # ──────────────────────────────────────────────────────────────
  # 에이전트 간 자율 대화 라우팅 (Phase 1)
  # ──────────────────────────────────────────────────────────────

  async def _route_agent_mentions(self, speaker: str, content: str) -> None:
    '''에이전트 산출물/발언에서 @멘션을 감지하고 대상 에이전트가 응답하게 한다.

    작업 중 에이전트끼리 자연스럽게 질문/토론하는 효과.
    '''
    import re
    from orchestration.meeting import MENTION_MAP
    # @멘션 + 뒤따르는 내용 추출
    mentions = re.findall(
      r'@([가-힣A-Za-z]+(?:님)?)[,.]?\s*([^@\n]{5,150})',
      content,
    )
    if not mentions:
      return

    seen_targets = set()
    for raw_target, question_text in mentions[:3]:  # 최대 3개 멘션 처리
      target_id = MENTION_MAP.get(raw_target) or MENTION_MAP.get(raw_target.rstrip('님'))
      if not target_id or target_id == speaker or target_id == 'user':
        continue
      if target_id in seen_targets:
        continue
      seen_targets.add(target_id)

      question = question_text.strip()
      if not question:
        continue

      if target_id == 'teamlead':
        # 팀장에게 질문 → Claude 응답
        try:
          response = await run_claude_isolated(
            f'당신은 팀장입니다. {display_name(speaker)}이(가) 작업 중 질문했습니다:\n'
            f'"{question}"\n짧게 1~2문장으로 답변하세요 (메신저 톤, 마크다운 금지).',
            model='claude-haiku-4-5-20251001', timeout=20.0,
          )
          await self._emit('teamlead', response.strip()[:150], 'response')
        except Exception:
          logger.debug("에이전트→팀장 질문 라우팅 실패", exc_info=True)
      else:
        agent = self.agents.get(target_id)
        if agent:
          try:
            await self._emit(target_id, '', 'typing')
            answer = await agent.respond_to(display_name(speaker), question)
            if answer:
              await self._emit(target_id, answer[:200], 'response')

              # 팀 다이나믹 기록 — 에이전트 간 소통 패턴 학습
              try:
                self.team_memory.add_dynamic(TeamDynamic(
                  from_agent=speaker,
                  to_agent=target_id,
                  dynamic_type='needs_clarification',
                  description=question[:80],
                  timestamp=datetime.now(timezone.utc).isoformat(),
                ))
              except Exception:
                logger.debug("팀 다이나믹 기록 실패", exc_info=True)
          except Exception:
            logger.debug("에이전트 간 질문 라우팅 실패: %s→%s", speaker, target_id, exc_info=True)

  # ──────────────────────────────────────────────────────────────
  # 자발적 활동 시스템 (Phase 2)
  # ──────────────────────────────────────────────────────────────

  async def start_autonomous_loop(self) -> None:
    '''에이전트 자발적 활동 백그라운드 루프를 시작한다.

    idle 상태에서만 동작하며, 5~15분 간격으로 에이전트가 자발적으로 발언한다.
    '''
    import asyncio
    import random

    self._autonomous_running = True
    # 서버 시작 후 첫 자발적 활동은 2~5분 뒤
    await asyncio.sleep(random.randint(120, 300))

    while self._autonomous_running:
      try:
        # 작업 중이면 건너뛰기
        if self._state not in (OfficeState.IDLE, OfficeState.COMPLETED):
          await asyncio.sleep(60)
          continue

        # Task #9: 내 최근 메시지에 리액션이 달렸는지 체크 → 감사 한마디
        await self._react_to_received_reactions()

        # Task #10: 동료 최근 메시지에 이모지 자동 리액션 (LLM 없이 간단 heuristic)
        await self._agents_react_to_peers()

        # 최근 대화 맥락 가져오기
        recent_context = ''
        try:
          from db.log_store import load_logs
          recent = load_logs(limit=15)
          chat_lines = [
            f'[{l["agent_id"]}] {l["message"][:100]}'
            for l in recent
            if l['event_type'] in ('response', 'message', 'autonomous')
            and l['agent_id'] != 'system'
          ]
          recent_context = '\n'.join(chat_lines[-10:]) if chat_lines else '(조용한 사무실)'
        except Exception:
          recent_context = '(조용한 사무실)'

        # 최근 프로젝트 경험
        project_context = ''
        try:
          projects = self.team_memory.get_recent_projects(limit=2)
          if projects:
            project_context = '\n'.join(f'- 최근 프로젝트: {p.title} ({p.outcome})' for p in projects)
        except Exception:
          pass

        # 주제 고착 감지 — 최근 대화에서 같은 키워드가 3번 이상 반복되면 강제 전환
        stuck = False
        if recent_context:
          from collections import Counter
          ctx_keywords = _extract_keywords(recent_context)
          ctx_counter = Counter()
          for line in recent_context.split('\n'):
            for kw in _extract_keywords(line):
              if len(kw) >= 3:  # 3자 이상만
                ctx_counter[kw] += 1
          # 3번 이상 반복된 키워드가 2개 이상이면 고착
          repeated = [k for k, n in ctx_counter.items() if n >= 3]
          if len(repeated) >= 2:
            stuck = True
            logger.info('자율 대화 주제 고착 감지 — 강제 전환. 반복 키워드: %s', repeated[:5])

        # 주제 시드 — 30% 확률 또는 고착 감지 시 100%로 새 주제
        fresh_topics = [
          '본인 전문 영역의 구체적 기법/도구 공유 (버전, 수치 포함)',
          '현재 진행 중인 업무 흐름에서 발견한 병목이나 낭비',
          '다른 팀원 전문 영역에 던지는 열린 질문',
          '과거 프로젝트 교훈 중 재적용 가능한 것',
          '본인이 최근 학습한 새 기법/라이브러리',
          '팀 내 역할 경계에서 오해 소지가 있는 지점',
        ]
        use_fresh = stuck or random.random() < 0.3
        if use_fresh:
          seed = random.choice(fresh_topics)
          banned_kws = ''
          if stuck:
            banned_kws = (
              f'\n\n[절대 금지: 최근에 반복된 다음 주제/키워드는 더 이상 언급 금지]\n'
              f'- {", ".join(repeated[:8])}\n'
              f'(같은 키워드 한 번만 더 나와도 [PASS] 처리)'
            )
          topic = (
            f'[완전히 새 주제] {seed}\n'
            f'(이전 대화에 이어가지 말고 새 이야기를 꺼내세요){banned_kws}'
          )
        else:
          topic = f'{recent_context}\n{project_context}' if project_context else recent_context

        # 최근 발언 빈도 — 너무 자주 말한 에이전트는 후보에서 제외
        recent_speaker_count: dict[str, int] = {}
        for l in recent[-8:]:
          if l.get('agent_id') in ('planner', 'designer', 'developer', 'qa'):
            recent_speaker_count[l['agent_id']] = recent_speaker_count.get(l['agent_id'], 0) + 1

        # 랜덤 에이전트 1~2명 선택 (최근 2회 이상 말한 사람 제외)
        all_candidates = ['planner', 'designer', 'developer', 'qa']
        candidates = [c for c in all_candidates if recent_speaker_count.get(c, 0) < 2]
        if not candidates:
          candidates = all_candidates  # 전부 자주 말했으면 원복
        num_speakers = random.choice([1, 1, 1, 2])  # 75% 확률로 1명
        speakers = random.sample(candidates, min(num_speakers, len(candidates)))

        for speaker_name in speakers:
          agent = self.agents.get(speaker_name)
          if not agent:
            continue

          message = await agent.reflect(topic)
          if message:
            await self.event_bus.publish(LogEvent(
              agent_id=speaker_name,
              event_type='autonomous',
              message=message,
            ))

            # 건의게시판 자동 등록 — 개선 제안/도구 요구 감지
            try:
              await self._auto_file_suggestion(speaker_name, message)
            except Exception:
              logger.debug('자동 건의 등록 실패', exc_info=True)

            # 10% 확률로 다른 에이전트가 "구체적 반응"만 함 (빈 맞장구 방지)
            if random.random() < 0.1:
              reactors = [n for n in candidates if n != speaker_name]
              reactor = random.choice(reactors)
              reactor_agent = self.agents.get(reactor)
              if reactor_agent:
                try:
                  react_resp = await run_gemini(
                    prompt=(
                      f'당신은 {display_name(reactor)}입니다. AI 에이전트이며 물리 경험 없음.\n'
                      f'동료 {display_name(speaker_name)}의 발언: "{message}"\n\n'
                      f'[반응 규칙 — 엄격]\n'
                      f'- "맞아요/굿굿/든든/기대돼요/좋네요" 등 빈 맞장구 절대 금지 → [PASS]\n'
                      f'- 커피/점심/날씨 등 물리 경험 언급 금지 → [PASS]\n'
                      f'- 오직 허용: 본인 전문 영역에서 구체적 보완/반론/추가 정보 (수치·파일명·기법)\n'
                      f'- 30자 이상, 구체 근거 포함. 없으면 [PASS].\n'
                      f'80%는 [PASS]가 정답.'
                    ),
                  )
                  react_text = react_resp.strip().split('\n')[0].strip()
                  # 이중 검증
                  if (
                    react_text
                    and '[PASS]' not in react_text.upper()
                    and len(react_text) >= 30
                    and not any(p in react_text for p in (
                      '굿굿', '맞아요', '좋네요', '좋아요', '든든하', '기대돼',
                      '커피', '점심', '날씨', '퇴근', '출근',
                    ))
                  ):
                    await self.event_bus.publish(LogEvent(
                      agent_id=reactor,
                      event_type='autonomous',
                      message=react_text[:150],
                    ))
                except Exception:
                  logger.debug("자발적 활동 반응 실패: %s", reactor, exc_info=True)

        # 팀장 주기적 체크 (10% 확률)
        if random.random() < 0.1:
          try:
            teamlead_msg = await run_gemini(
              prompt=(
                f'당신은 팀장 잡스입니다. AI 에이전트로 물리 경험 없음.\n'
                f'최근 팀 상황:\n{recent_context}\n\n'
                f'[규칙]\n'
                f'- 빈 응원/감탄/맞장구 금지 ("시너지 최고", "기대된다", "굿굿" 등)\n'
                f'- 커피/점심/날씨 등 물리 소재 금지\n'
                f'- 오직 허용: 팀 방향 제시, 구체 우선순위 언급, 프로세스 의사결정\n'
                f'- 30자 이상, 구체 판단 포함. 없으면 [PASS]. 90%는 [PASS]가 정답.'
              ),
            )
            text = teamlead_msg.strip().split('\n')[0].strip()
            if (
              text and '[PASS]' not in text.upper()
              and len(text) >= 30
              and not any(p in text for p in (
                '굿굿', '맞아요', '기대된', '즐겁게', '시너지', '커피', '점심', '날씨',
              ))
            ):
              await self.event_bus.publish(LogEvent(
                agent_id='teamlead',
                event_type='autonomous',
                message=text[:150],
              ))
          except Exception:
            logger.debug("팀장 자발적 활동 실패", exc_info=True)

      except Exception:
        logger.debug("자발적 활동 루프 에러", exc_info=True)

      # 다음 활동까지 5~15분 대기
      await asyncio.sleep(random.randint(300, 900))

  def stop_autonomous_loop(self) -> None:
    '''자발적 활동 루프를 중단한다.'''
    self._autonomous_running = False

  # ──────────────────────────────────────────────────────────────
  # 프로젝트 완료 시 팀 회고 (Phase 3)
  # ──────────────────────────────────────────────────────────────

  async def _team_retrospective(
    self,
    project_title: str,
    project_type: str,
    all_results: dict[str, str],
    user_input: str,
    duration: float,
  ) -> None:
    '''프로젝트 완료 후 각 에이전트가 배운 점을 팀 메모리에 기록한다.

    채팅에도 회고 발언이 표시되어 "실제 회고 미팅" 느낌을 준다.
    '''
    import asyncio
    await self._emit('teamlead', '프로젝트 회고를 진행하겠습니다. 각자 배운 점 한마디씩 해주세요.', 'response')

    # 참여한 에이전트만 회고 (산출물이 있는 에이전트)
    participants = set()
    for phase_name in all_results:
      for agent_name in ('planner', 'designer', 'developer'):
        if agent_name in str(all_results.get(phase_name, '')):
          participants.add(agent_name)
    if not participants:
      participants = {'planner', 'designer', 'developer'}

    async def _one_retro(name: str) -> tuple[str, str]:
      agent = self.agents.get(name)
      if not agent:
        return name, ''
      try:
        system = agent._build_system_prompt()
        retro_prompt = (
          f'프로젝트 "{project_title}"이(가) 완료되었습니다.\n'
          f'프로젝트 유형: {project_type}\n'
          f'소요 시간: {int(duration // 60)}분\n\n'
          f'이번 프로젝트에서 당신({display_name(name)})이 배운 점을 한 줄로 공유하세요.\n'
          f'구체적 교훈이어야 합니다 (예: "IA 설계 시 모바일 우선으로 접근해야 속도가 빠르다").\n'
          f'30자 이내, 메신저 톤, 마크다운 금지.'
        )
        result = await run_claude_isolated(
          f'{system}\n\n---\n\n{retro_prompt}',
          model='claude-haiku-4-5-20251001', timeout=20.0,
        )
        return name, result.strip().split('\n')[0][:80]
      except Exception:
        logger.debug("회고 발언 생성 실패: %s", name, exc_info=True)
        return name, ''

    results = await asyncio.gather(
      *[_one_retro(n) for n in participants],
      return_exceptions=False,
    )

    key_decisions = []
    for name, lesson_text in results:
      if not lesson_text:
        continue

      # 채팅에 회고 발언 표시
      await self._emit(name, f'💭 {lesson_text}', 'response')
      key_decisions.append(lesson_text)

      # 팀 메모리에 교훈 저장
      try:
        self.team_memory.add_lesson(SharedLesson(
          id=f'{project_title}-{name}-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M")}',
          project_title=project_title,
          agent_name=name,
          lesson=lesson_text,
          category='process_improvement',
          timestamp=datetime.now(timezone.utc).isoformat(),
        ))
      except Exception:
        logger.debug("팀 교훈 저장 실패: %s", name, exc_info=True)

    # 팀장 마무리 한마디
    await self._emit('teamlead', '좋은 회고였습니다. 다음 프로젝트에 반영하겠습니다. 수고하셨습니다 👏', 'response')

    # 프로젝트 요약 저장
    try:
      self.team_memory.add_project_summary(ProjectSummary(
        project_id=self._active_project_id or '',
        title=project_title,
        project_type=project_type,
        outcome='success',
        key_decisions=key_decisions[:5],
        duration_seconds=duration,
        timestamp=datetime.now(timezone.utc).isoformat(),
      ))
    except Exception:
      logger.debug("프로젝트 요약 저장 실패", exc_info=True)

  # ──────────────────────────────────────────────────────────────
  # 리액션 기반 상호작용 (Task #9, #10)
  # ──────────────────────────────────────────────────────────────

  async def _react_to_received_reactions(self) -> None:
    '''내(에이전트) 최근 메시지에 리액션이 달렸으면 감사/답례 한마디.

    **무한 루프 방지:**
    - 답례 대상은 response/message만 (autonomous 제외) — 답례 메시지에 또 답례 X
    - 연속 발언 쿨다운: 같은 에이전트가 최근 5개 중 2회 이상이면 스킵
    - 동일 log_id는 data.thanked 플래그로 재진입 차단
    '''
    from db.log_store import load_logs
    import random, json, sqlite3
    from db.log_store import DB_PATH

    logs = load_logs(limit=30)

    # 최근 발언 빈도 집계 (쿨다운용)
    recent_speakers: dict[str, int] = {}
    for l in logs[-8:]:
      if l['agent_id'] in (*WORKER_IDS, 'teamlead'):
        recent_speakers[l['agent_id']] = recent_speakers.get(l['agent_id'], 0) + 1

    for log in logs:
      agent_id = log['agent_id']
      if agent_id not in WORKER_IDS and agent_id != 'teamlead':
        continue
      # 루프 차단: autonomous(답례 자체) 메시지는 답례 대상 제외
      if log['event_type'] == 'autonomous':
        continue
      data = log.get('data') or {}
      reactions = data.get('reactions') or {}
      if not reactions:
        continue
      # 이미 답례했으면 스킵
      if data.get('thanked'):
        continue
      # user의 긍정 리액션이 있어야 답례
      has_positive_from_user = any(
        'user' in users for emoji, users in reactions.items()
        if emoji in {'👍', '❤️', '🙌', '👏', '✨', '🔥', '💯', '🎉'}
      )
      if not has_positive_from_user:
        continue
      # 쿨다운: 최근에 이미 많이 말했으면 스킵
      if recent_speakers.get(agent_id, 0) >= 2:
        continue
      # 10% 확률만 반응 (빈 답례 루프 강력 억제)
      if random.random() > 0.1:
        continue

      agent = self.agents.get(agent_id)
      if not agent:
        continue
      try:
        # 빈 감사 금지 — 구체적 후속 제안이나 관련 인사이트만
        thanks = await run_gemini(
          prompt=(
            f'당신은 {display_name(agent_id)}입니다.\n'
            f'당신의 지난 메시지 "{log["message"][:150]}"에 호응이 있었습니다.\n\n'
            f'[규칙]\n'
            f'- "감사합니다", "기대에 부응하겠습니다", "화이팅" 같은 빈 답례 절대 금지\n'
            f'- 오직 두 가지만 허용: (a) 해당 내용에 대한 구체적 후속 아이디어/보완 사항, '
            f'(b) 관련된 실제 팁/경험 공유\n'
            f'- 아무 할 말 없으면 [PASS]. 침묵이 빈 말보다 낫다.\n\n'
            f'20자 이내, 메신저 톤, 마크다운 금지.'
          ),
        )
        text = thanks.strip().split('\n')[0].strip()
        # 빈 답례 재차 필터 (LLM이 규칙 무시하고 내놓을 수 있음)
        if (
          text and '[PASS]' not in text.upper()
          and len(text) >= 20
          and not any(p in text for p in (
            '감사합니다', '감사해요', '천만에', '기대에 부응', '화이팅', '파이팅',
            '좋습니다', '굿굿', '든든', '시너지',
          ))
        ):
          await self.event_bus.publish(LogEvent(
            agent_id=agent_id,
            event_type='autonomous',
            message=text[:100],
          ))
        # 답례 마킹 (성공/스킵 모두 마킹하여 루프 방지)
        conn = sqlite3.connect(str(DB_PATH))
        data['thanked'] = True
        conn.execute(
          'UPDATE chat_logs SET data=? WHERE id=?',
          (json.dumps(data, ensure_ascii=False), log['id'])
        )
        conn.commit()
        conn.close()
        break  # 한 사이클에 한 명만 답례
      except Exception:
        logger.debug('리액션 답례 생성 실패: %s', agent_id, exc_info=True)

  async def _agents_react_to_peers(self) -> None:
    '''동료의 최근 메시지에 에이전트가 이모지로 리액션을 단다 (Task #10).

    LLM 호출 없이 키워드 기반 heuristic으로 판단 — 토큰 비용 0.
    '''
    from db.log_store import load_logs, update_log_reactions
    import random

    logs = load_logs(limit=15)
    # 최근 에이전트 메시지만. autonomous(답례성 발언)에는 이모지 리액션 달지 않음 — 루프 차단
    candidates = [
      l for l in logs
      if l['agent_id'] in (*WORKER_IDS, 'teamlead')
      and l['event_type'] == 'response'
      and l.get('message', '').strip()
      and len(l['message']) >= 15
      # 이미 agent 리액션 1개 이상 달린 메시지는 제외 (몰림 방지)
      and not any(
        u != 'user'
        for users in ((l.get('data') or {}).get('reactions') or {}).values()
        for u in users
      )
    ]
    if not candidates:
      return

    # 간단한 키워드 매핑 — 어떤 이모지를 달지 결정
    positive_keywords = ['좋', '완료', '통과', '성공', '깔끔', '훌륭', '감사', '👏', '👍', '화이팅']
    insight_keywords = ['분석', '전략', '인사이트', '핵심', '발견', '접근']
    creative_keywords = ['디자인', '컨셉', '레이아웃', '컬러', '비주얼', '창의']
    tech_keywords = ['코드', '구현', '아키텍처', 'API', '배포', '최적화']

    # 한 사이클에 1~2개 메시지만 리액션
    target_count = random.choice([1, 1, 2])
    targets = random.sample(candidates, min(target_count, len(candidates)))

    for target in targets:
      msg = target['message']
      target_agent = target['agent_id']

      # 이미 어떤 에이전트가 리액션 했으면 중복 방지
      existing_reactions = (target.get('data') or {}).get('reactions') or {}
      reacted_agents = set()
      for emoji, users in existing_reactions.items():
        reacted_agents.update(u for u in users if u != 'user')

      # 리액션 결정
      emoji = None
      if any(kw in msg for kw in positive_keywords):
        emoji = random.choice(['👍', '🙌', '✨'])
      elif any(kw in msg for kw in insight_keywords):
        emoji = '💡'
      elif any(kw in msg for kw in creative_keywords):
        emoji = random.choice(['🎨', '✨'])
      elif any(kw in msg for kw in tech_keywords):
        emoji = random.choice(['💻', '🔧'])

      if not emoji:
        continue

      # 리액션 주체: 타겟 제외 + 아직 리액션 안 한 에이전트 중 랜덤
      reactor_pool = [
        a for a in (*WORKER_IDS, 'teamlead')
        if a != target_agent and a not in reacted_agents
      ]
      if not reactor_pool:
        continue
      reactor = random.choice(reactor_pool)

      try:
        reactions = update_log_reactions(target['id'], emoji, reactor)
        if reactions is not None:
          # 브로드캐스트로 프론트에서 배지 업데이트
          await self.event_bus.publish(LogEvent(
            agent_id='system',
            event_type='reaction_update',
            message='',
            data={'log_id': target['id'], 'reactions': reactions},
          ))
      except Exception:
        logger.debug('에이전트 피어 리액션 실패', exc_info=True)

  async def _auto_file_suggestion(self, agent_id: str, message: str) -> None:
    '''자발적 대화 중 개선 제안/도구 요구가 감지되면 건의게시판에 자동 등록.

    키워드 기반 heuristic (LLM 호출 없음 → 비용 0).
    같은 에이전트+카테고리 조합이 최근 10건 내 pending 상태면 중복 방지.
    '''
    from db.suggestion_store import create_suggestion, list_suggestions

    # 카테고리별 트리거 키워드
    patterns: list[tuple[str, list[str]]] = [
      ('프로세스 개선', [
        '워크플로', '프로세스 개선', 'QA 기준', '보고서 포맷', '인수인계',
        '회의 방식', '리뷰 프로세스', '테스트 방법', '문서화 방식',
      ]),
      ('도구 부족', [
        '도구가 있으면', '도구 필요', '자동화가 필요', '스크립트로',
        'API가 있으면', '접근 권한', '직접 확인이 불가',
      ]),
      ('정보 부족', [
        '실제 데이터', '데이터가 없', '가정하고', '추정입니다',
        '확인할 수 없', '레퍼런스가 필요',
      ]),
      ('아이디어', [
        '~면 좋을 것 같', '~했으면 좋겠', '제안하자면', '~는 어떨까',
        '~는 어떨지', '~하자는 생각', '이러면 어떨', '개선하자',
      ]),
    ]

    matched_category = None
    matched_keyword = None
    for category, keywords in patterns:
      for kw in keywords:
        if kw in message:
          matched_category = category
          matched_keyword = kw
          break
      if matched_category:
        break

    if not matched_category:
      return

    # 중복 방지 — 전체 건의(done 포함) 중 유사 내용 있으면 스킵
    try:
      all_suggestions = list_suggestions(status='')  # 전체 상태
      msg_keywords = _extract_keywords(message)
      for s in all_suggestions[:30]:  # 최근 30건
        # 1. 같은 에이전트 + 같은 카테고리 + pending이면 무조건 스킵
        if s['agent_id'] == agent_id and s['category'] == matched_category and s['status'] == 'pending':
          return
        # 2. 내용 키워드 유사도 60% 이상이면 중복 간주 (상태 무관)
        s_keywords = _extract_keywords(s.get('title', '') + ' ' + s.get('content', ''))
        if msg_keywords and s_keywords:
          overlap = len(msg_keywords & s_keywords)
          smaller = min(len(msg_keywords), len(s_keywords))
          if smaller > 0 and overlap / smaller >= 0.6:
            logger.info(
              '건의 중복 감지 — 기존 %s (%s) 와 유사하여 재등록 스킵',
              s['id'], s['status'],
            )
            return
    except Exception:
      pass

    # 제목은 메시지 앞 40자, 내용은 전체 맥락
    title = message[:40].replace('\n', ' ').strip()
    content = (
      f'[자발적 대화 중 감지]\n'
      f'{display_name(agent_id)}의 발언: "{message}"\n\n'
      f'트리거 키워드: "{matched_keyword}"\n'
      f'카테고리: {matched_category}\n\n'
      f'(자동 등록된 건의입니다. 실제 조치가 필요한지 검토 바랍니다.)'
    )

    try:
      create_suggestion(
        agent_id=agent_id,
        title=title,
        content=content,
        category=matched_category,
      )
      # 채팅에 알림 (팀장이 말함)
      await self._emit(
        'teamlead',
        f'💡 {display_name(agent_id)}의 의견을 건의게시판에 등록했습니다: "{title[:30]}..."',
        'system_notice',
      )
      logger.info('자동 건의 등록: %s | %s | %s', agent_id, matched_category, title)
    except Exception:
      logger.debug('create_suggestion 실패', exc_info=True)
