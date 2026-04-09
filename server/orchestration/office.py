# Office — 진짜 사무실처럼 동작하는 오케스트레이션 시스템
from __future__ import annotations
# 팀장이 판단하고, 팀원이 협업하고, 회의를 통해 프로젝트를 진행한다.
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from orchestration.intent import IntentType, classify_intent, classify_project_type
from orchestration.phase_registry import ProjectType, get_phases, get_meeting_participants
from orchestration.agent import Agent
from orchestration.meeting import Meeting
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
    self._last_review_feedback = ''
    # 프로젝트 세션
    self._active_project_id: str | None = None
    self._active_project_title: str = ''
    self._base_task_id: str = ''  # 🔗 이전 작업 참조 (main.py에서 설정)
    self._user_mid_feedback: list[str] = []  # 작업 중 사용자 피드백 축적
    self._phase_feedback: list[dict] = []   # 팀원 리액션/인수인계 피드백

    # Groq 러너 (디자이너, QA용)
    self.groq_runner = GroqRunner()

    # 자가개선 엔진
    self.improvement_engine = ImprovementEngine(event_bus=event_bus)

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
      pass

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
      profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}
      responder = random.choice(['planner', 'designer', 'developer', 'qa'])
      try:
        response = await run_claude_isolated(
          f'당신은 {profile_names[responder]}입니다.\n'
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
        pass
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
          pass
      return
    agent_model_map = {
      'planner': 'Claude Sonnet(업무) / Haiku(대화)',
      'designer': 'Claude Sonnet(업무) / Haiku(대화)',
      'developer': 'Claude Sonnet(업무) / Haiku(대화)',
      'qa': 'Claude Sonnet(업무) / Haiku(대화)',
    }

    # ── @멘션 파싱 — 지목된 에이전트 우선 응답 ──
    import re
    mentioned_ids: set[str] = set()
    raw_mentions = re.findall(r'@([가-힣A-Za-z]+(?:님)?)', user_input)
    for raw in raw_mentions:
      target = MENTION_MAP.get(raw) or MENTION_MAP.get(raw.rstrip('님'))
      if target and target not in ('user', 'teamlead'):
        mentioned_ids.add(target)

    # 멘션된 에이전트가 먼저, 나머지는 기본 순서
    default_order = ['planner', 'designer', 'developer', 'qa']
    if mentioned_ids:
      ordered = [n for n in default_order if n in mentioned_ids] + \
                [n for n in default_order if n not in mentioned_ids]
    else:
      ordered = default_order

    # ── 대화 스레드 구성 — 최근 맥락 + 현재 대화 ──
    thread: list[str] = []
    responded: list[str] = []

    # 1) 이전 대화 맥락 (흐름 파악용)
    if self._context_summary:
      thread.append(f'[이전 대화 맥락]\n{self._context_summary}')
      thread.append('---')

    # 2) 현재 대화 — 사용자 메시지 + 팀장 응답
    thread.append(f'[사용자] {user_input}')
    if teamlead_response:
      thread.append(f'[팀장] {teamlead_response}')

    for name in ordered:
      agent = self.agents.get(name)
      if not agent:
        continue
      system = agent._build_system_prompt(task_hint=user_input)
      my_model = agent_model_map.get(name, '알 수 없음')

      is_mentioned = name in mentioned_ids
      thread_text = '\n'.join(thread)

      if is_mentioned:
        # 직접 지목된 에이전트 → 반드시 응답
        prompt = (
          f'아래는 팀 채팅방의 현재 대화입니다.\n\n'
          f'{thread_text}\n\n'
          f'---\n\n'
          f'당신은 {name}입니다. (모델: {my_model})\n'
          f'사용자가 당신을 직접 지목(@멘션)했습니다. 반드시 응답하세요.\n\n'
          f'1~2문장, 메신저 톤, 마크다운 금지.\n'
          f'대화 중 사용자가 은연중에 업무를 요청한 것 같다면 [TASK_DETECTED:업무 설명]을 출력하세요.'
        )
      else:
        prompt = (
          f'아래는 팀 채팅방의 현재 대화입니다.\n\n'
          f'{thread_text}\n\n'
          f'---\n\n'
          f'당신은 {name}입니다. (모델: {my_model})\n'
          f'위 대화를 전부 읽고, 당신이 반응해야 하는지 판단하세요.\n\n'
          f'[판단 기준]\n'
          f'- 대화 맥락을 정확히 파악하라. 같은 단어라도 문맥에 따라 의미가 다르다.\n'
          f'- 누군가 이미 적절히 답변/반응한 내용은 반복하지 마라.\n'
          f'- 새로운 관점이나 정보를 더할 수 있을 때만 발언하라.\n'
          f'- 일상 대화(날씨, 교통, 안부)는 전문 영역과 무관하므로 대부분 [PASS]\n'
          f'- 당신을 직접 지목(@멘션)하지 않았고, 추가할 가치가 없으면 [PASS]\n'
          f'- 대화 중 사용자가 은연중에 업무를 요청한 것 같다면 [TASK_DETECTED:업무 설명]을 출력하세요.\n\n'
          f'반응할 필요 없으면: [PASS]\n'
          f'반응할 필요 있으면: 1~2문장, 메신저 톤, 마크다운 금지.\n'
          f'이미 나온 말을 다른 표현으로 반복하는 것은 금지.'
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

        if not is_pass:
          # 업무 감지 체크
          if '[TASK_DETECTED:' in content:
            import re
            task_match = re.search(r'\[TASK_DETECTED:(.+?)\]', content)
            if task_match:
              detected_task = task_match.group(1).strip()
              chat_part = re.sub(r'\[TASK_DETECTED:.+?\]', '', content).strip()
              if chat_part:
                await self._emit(name, chat_part, 'response')
                thread.append(f'[{name}] {chat_part}')
                responded.append(name)
              await self._emit('teamlead', f'지금 말씀 중에 업무 요청이 있는 것 같네요. "{detected_task}" — 확인해보겠습니다.', 'response')
              from orchestration.intent import classify_intent
              re_intent = await classify_intent(detected_task)
              if re_intent.intent != IntentType.CONVERSATION:
                return
              continue

          # 응답을 스레드에 추가 → 다음 에이전트가 볼 수 있게
          thread.append(f'[{name}] {content}')
          responded.append(name)
          await self._emit(name, content, 'response')
      except Exception:
        pass

    # 아무도 안 답하면 랜덤 한 명이 답변 (왕따 방지)
    if not responded:
      import random
      fallback_name = random.choice(['planner', 'designer', 'developer', 'qa'])
      agent = self.agents[fallback_name]
      system = agent._build_system_prompt(task_hint=user_input)
      thread_text = '\n'.join(thread)
      prompt = (
        f'아래는 팀 채팅방의 현재 대화입니다.\n\n'
        f'{thread_text}\n\n'
        f'아무도 답을 안 했습니다. 당신이 대표로 한마디 해주세요.\n'
        f'짧고 자연스럽게. 마크다운 금지.'
      )
      try:
        response = await run_claude_isolated(
          f'{system}\n\n---\n\n{prompt}',
          model='claude-haiku-4-5-20251001',
          timeout=30.0,
        )
        content = response.strip()
        await self._emit(fallback_name, content, 'response')
      except Exception:
        pass

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
        pass

    # 0. 대기 중인 프로젝트가 있으면 사용자 답변으로 이어서 진행
    if hasattr(self, '_pending_project') and self._pending_project:
      return await self._continue_project(user_input)

    # 0-1. 중단된 작업이 있고 사용자가 재개를 요청하면 원래 instruction으로 재실행
    if hasattr(self, '_interrupted_instruction') and self._interrupted_instruction:
      # 명시적 재개 표현만 허용 (단순 "네", "응" 같은 일상 표현은 제외)
      resume_phrases = ('이전 작업', '이어서 진행', '계속 진행', '재개해', '아까 거', '중단된 거', '이어서 해', '계속해')
      is_confirmed_resume = self._interrupted_confirmed and user_input.strip().lower() in ('네', '응', 'ㅇㅇ', 'yes', 'ok')
      if any(phrase in user_input for phrase in resume_phrases) or is_confirmed_resume:
        if not self._interrupted_confirmed:
          # 첫 번째 응답: 확인 질문
          self._interrupted_confirmed = True
          instruction_preview = self._interrupted_instruction[:80]
          await self._emit('teamlead', f'@마스터 이전 작업 "{instruction_preview}..." 이어서 진행할까요?', 'response')
          self._state = OfficeState.IDLE
          return {'state': self._state.value, 'response': '', 'artifacts': []}
        else:
          # 두 번째 응답: 원래 task_id의 workspace 복원 후 재실행
          original = self._interrupted_instruction
          original_task_id = self._interrupted_task_id
          self._interrupted_instruction = None
          self._interrupted_task_id = None
          self._interrupted_confirmed = False
          # 원래 workspace 복원 (이미 완료된 단계 산출물 유지)
          if original_task_id:
            ws_root = str(Path(__file__).parent.parent.parent / 'workspace')
            self.workspace = WorkspaceManager(task_id=original_task_id, workspace_root=ws_root)
          return await self.receive(original)
      else:
        # 다른 입력이면 중단 작업 폐기
        self._interrupted_instruction = None
        self._interrupted_task_id = None
        self._interrupted_confirmed = False

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
      pass

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
        # 새 프로젝트 시작
        if self._active_project_id:
          archive_project(self._active_project_id)

        # 🔗 이전 작업 참조가 있으면 해당 workspace를 프로젝트로 승격
        ws_root = str(Path(__file__).parent.parent.parent / 'workspace')
        if self._base_task_id:
          new_pid = self._base_task_id  # 이전 workspace 그대로 사용
          base_task = get_task(self._base_task_id)
          title = await generate_project_title(
            base_task['instruction'] if base_task else user_input
          )
          self._base_task_id = ''  # 사용 후 초기화
        else:
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

      # 서브유형별 팀원 반응 제어 — 팀장 응답을 스레드에 포함
      await self._team_chat(user_input, chat_subtype=intent_result.chat_subtype, teamlead_response=response)

      # 대화 맥락 실시간 갱신 — 후속 메시지에서 주제 변경 감지 가능
      self._update_context(user_input, response)

      self._state = OfficeState.COMPLETED
      self._active_agent = ''
      self._work_started_at = ''
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

    # 업무 수신 확인
    profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}
    await self._emit('teamlead', f'알겠습니다. {profile_names.get(agent_name, agent_name)}에게 맡기겠습니다.', 'response')

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
      f'- 다른 영역의 검토가 필요하면 "이 부분은 디자이너/개발자 검토가 필요합니다"로 남기세요.'
    ]
    if self._context_summary:
      ctx_parts.append(f'[이전 대화 요약]\n{self._context_summary}')
    if reference_context:
      ctx_parts.append(reference_context)
    result = await agent.handle(prompt, context='\n\n'.join(ctx_parts))

    # 다른 팀원의 전문 의견 (40% 확률)
    await self._work_commentary(agent_name, 'quick-task', result)

    # QA 검수 (최대 2회 재작업)
    qa_agent = self.agents.get('qa')
    if qa_agent and agent_name != 'qa':
      for attempt in range(2):
        self._state = OfficeState.QA_REVIEW
        self._active_agent = 'qa'
        await self._emit('qa', '산출물 검수를 시작합니다.', 'response')

        qa_prompt = (
          f'[원본 요구사항]\n{prompt}\n\n'
          f'[작업 결과물]\n{result}\n\n'
          f'위 요구사항 대비 결과물을 검수하세요.'
        )
        qa_result = await qa_agent.handle(qa_prompt)

        # JSON 파싱으로 합격/불합격 판단
        passed = True
        failure_reason = ''
        try:
          import re
          json_match = re.search(r'\{[^{}]*\}', qa_result, re.DOTALL)
          if json_match:
            qa_json = json.loads(json_match.group())
            if qa_json.get('status') == 'fail':
              passed = False
              failure_reason = qa_json.get('failure_reason', 'QA 불합격')
        except (json.JSONDecodeError, AttributeError):
          if '불합격' in qa_result or 'fail' in qa_result.lower():
            passed = False
            failure_reason = qa_result[:300]

        if passed:
          await self._emit('qa', '검수 통과 ✅', 'response')
          break
        else:
          await self._emit('qa', f'검수 불합격: {failure_reason[:200]}', 'response')
          if attempt < 1:
            # 재작업 요청
            self._state = OfficeState.WORKING
            self._active_agent = agent_name
            await self._emit('teamlead', f'{profile_names.get(agent_name, agent_name)}, 보완 부탁합니다.', 'response')
            revision_prompt = f'{prompt}\n\n[QA 피드백 — 반드시 반영할 것]\n{failure_reason}\n\n[이전 결과물]\n{result}'
            result = await agent.handle(revision_prompt, context='\n\n'.join(ctx_parts))

    # 산출물 저장
    saved_paths = []
    try:
      file_path = 'quick-task/result.md'
      self.workspace.write_artifact(file_path, result)
      saved_paths.append(f'{self.workspace.task_id}/{file_path}')
    except Exception:
      pass

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
    teamlead_agent = self.agents.get('teamlead')
    review_response = await teamlead_agent.handle(review_prompt) if teamlead_agent else '[PASS]'
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
        pass

    # 팀장 최종 보고 — 사용자에게 결과 요약 + 산출물 링크
    report_prompt = (
      f'[사용자 원본 요구사항]\n{prompt[:500]}\n\n'
      f'[완성된 산출물 요약]\n{result[:3000]}\n\n'
      f'팀장으로서 사용자에게 최종 보고하세요.\n'
      f'- 누가 어떤 작업을 했는지 (이 경우 {profile_names.get(agent_name, agent_name)}이 단독 수행)\n'
      f'- 핵심 결과 요약 (3~5줄)\n'
      f'- 추가 검토가 필요한 사항이 있으면 언급\n'
      f'간결하게 보고하세요.'
    )
    teamlead_agent = self.agents.get('teamlead')
    try:
      report = await teamlead_agent.handle(report_prompt) if teamlead_agent else ''
    except Exception:
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
        message=f'{profile_names.get(agent_name, agent_name)} 작업 완료했습니다.\n\n{summary}',
        data={'artifacts': saved_paths},
      ))

    # 프로젝트 세션 종료
    if self._active_project_id:
      from db.task_store import archive_project
      archive_project(self._active_project_id)
      await self._emit('system', '📂 프로젝트 완료', 'project_close')
      self._active_project_id = None
      self._active_project_title = ''

    self._state = OfficeState.COMPLETED
    self._active_agent = ''
    self._work_started_at = ''
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

    # 2. 팀장이 회의 결과에서 확인 필요한 사항을 사용자에게 질문
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

    # phases가 전달되지 않으면 기존 호환 로직 (웹 개발 기본)
    if phases is not None:
      PHASES = phases
      # project_type은 phases의 output_format으로 추론
      project_type = 'web_development'
      for p in phases:
        if p.get('output_format', '').endswith('+pdf'):
          project_type = 'document'
          break
    else:
      project_type = self.improvement_engine.qa_adapter.classify_project_type(user_input)
      PHASES = self.improvement_engine.workflow_optimizer.get_phase_dicts(project_type, user_input)

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
          if not remaining_in_group and current_group == '디자인':
            # Stitch 시안이 아직 없으면 생성
            # 전체 workspace에서 Stitch 시안 검색
            has_stitch = False
            workspace_root = self.workspace.task_dir.parent
            for ws_dir in workspace_root.iterdir():
              sd = ws_dir / 'stitch'
              if sd.exists() and any(sd.iterdir()):
                has_stitch = True
                break
            if not has_stitch:
              await self._generate_stitch_mockup(all_results, user_input)
            else:
              await self._emit('designer', '이전에 생성된 Stitch 시안이 있습니다. 그대로 사용합니다. 🎨', 'response')
          continue
      except Exception:
        pass

      self._state = OfficeState.WORKING
      self._active_agent = agent_name
      self._work_started_at = datetime.now(timezone.utc).isoformat()
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
        f'중요: 반드시 모든 섹션을 끝까지 완성하세요. 절대 중간에 끊지 마세요.'
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
        pass

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
                pass
          except Exception:
            pass

      # md+code 포맷: Python/JS 코드블록 추출
      if output_format == 'md+code':
        code_blocks = _re.findall(r'```(?:python|py)\s*\n([\s\S]*?)\n```', content)
        for i, code in enumerate(code_blocks):
          code_filename = f'{phase_name}/code_{i}.py'
          try:
            self.workspace.write_artifact(code_filename, code)
            phase_artifacts.append(f'{self.workspace.task_id}/{code_filename}')
          except Exception:
            pass

      all_results[phase_name] = content
      prev_phase_result = content

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

      # 다른 팀원의 전문 의견 (40% 확률)
      await self._work_commentary(agent_name, phase_name, content)

      # 다른 팀원 리액션 (가벼운 반응으로 실제 오피스 느낌)
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
                  await self._emit(target_id, '네, 확인했습니다.', 'response')
          self._user_mid_feedback.append(feedback_msg)
          await self._emit('teamlead', f'말씀하신 내용 반영하여 다음 단계 진행하겠습니다.', 'response')
        elif user_directive.get('message'):
          # 사용자 지시를 다음 소단계 프롬프트에 반영
          self._user_mid_feedback.append(user_directive['message'])
          meeting_summary += f'\n\n[사용자 중간 지시]\n{user_directive["message"]}'
          await self._emit('teamlead', f'말씀하신 내용 반영하여 다음 단계 진행하겠습니다.', 'response')

      # QA 검수 — 그룹의 마지막 소단계에서만 실행
      current_group = phase.get('group', phase_name)
      remaining_in_group = [p for p in PHASES[PHASES.index(phase)+1:] if p.get('group') == current_group]
      if not remaining_in_group:
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
            pass
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

        # 디자인 그룹 완료 시 → Stitch로 시안 생성
        if current_group == '디자인':
          await self._generate_stitch_mockup(all_results, user_input)

    # 퍼블리싱이 포함된 프로젝트(사이트 구축)인지 판단
    has_publishing = any('퍼블리싱' in k for k in all_results)

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

    # 프로젝트 세션 종료
    if self._active_project_id:
      from db.task_store import archive_project
      archive_project(self._active_project_id)
      await self._emit('system', '📂 프로젝트 완료', 'project_close')
      self._active_project_id = None
      self._active_project_title = ''

    self._state = OfficeState.COMPLETED
    self._active_agent = ''
    self._work_started_at = ''
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
      pass  # 자가개선 실패가 프로젝트 완료를 막지 않음

    return {
      'state': self._state.value,
      'response': '프로젝트 완료',
      'artifacts': phase_artifacts,
    }

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
      response = await run_claude_isolated(prompt, timeout=120.0)
      text = response.strip()
      if text.upper().startswith('[SKIP]') or text.upper() == 'SKIP':
        return ''
      return text
    except Exception:
      return ''

  async def _run_planner_distribute(
    self,
    user_input: str,
    analysis: str,
    meeting_summary: str,
    reference_context: str,
    task_graph: TaskGraph,
  ) -> None:
    '''기획자가 회의 내용을 바탕으로 태스크를 분배한다.'''
    planner = self.agents['planner']
    system = planner._build_system_prompt(task_hint=user_input)

    ref_section = f'[참조 자료]\n{reference_context[:4000]}\n\n' if reference_context else ''

    prompt = (
      f'[사용자 지시]\n{user_input}\n\n'
      f'[팀장 분석]\n{analysis}\n\n'
      f'[팀 회의 내용]\n{meeting_summary}\n\n'
      f'{ref_section}'
      f'회의에서 나온 의견을 반영하여 구체적인 태스크를 분배하세요.\n\n'
      f'[응답 형식]\n'
      f'반드시 아래 JSON 형식으로 응답하세요:\n'
      f'{{\n'
      f'  "tasks": [\n'
      f'    {{\n'
      f'      "task_id": "task-1",\n'
      f'      "description": "구체적 작업 내용 (최소 3문장)",\n'
      f'      "requirements": "완료 기준",\n'
      f'      "assigned_to": "developer",\n'
      f'      "depends_on": []\n'
      f'    }}\n'
      f'  ]\n'
      f'}}\n'
      f'assigned_to는 planner, designer, developer, qa 중 하나.'
    )

    try:
      raw = await run_claude_isolated(f'{system}\n\n---\n\n{prompt}')
    except Exception:
      raw = await run_gemini(prompt=prompt, system=system)
    from runners.json_parser import parse_json
    result = parse_json(raw)

    if result and isinstance(result, dict) and 'tasks' in result:
      for task_data in result['tasks']:
        task_id = task_data.get('task_id', f'task-{id(task_data)}')
        deps = task_data.get('depends_on', [])
        if isinstance(deps, str):
          deps = [deps] if deps else []
        elif not isinstance(deps, list):
          deps = []
        try:
          payload = TaskRequestPayload(
            task_id=task_id,
            description=task_data.get('description', ''),
            requirements=task_data.get('requirements', ''),
            assigned_to=task_data.get('assigned_to', 'developer'),
            depends_on=deps,
          )
          task_graph.add_task(payload)
        except Exception:
          continue
    else:
      # 파싱 실패 시 기본 태스크
      fallback = TaskRequestPayload(
        task_id='task-fallback',
        description=user_input,
        requirements=user_input,
        assigned_to='developer',
        depends_on=[],
      )
      task_graph.add_task(fallback)

    # 내부 처리 완료 — 채팅에 표시 안 함

  async def _execute_tasks(
    self,
    task_graph: TaskGraph,
    reference_context: str,
  ) -> dict[str, str]:
    '''태스크 그래프에 따라 작업을 실행하고 QA 중간검수를 한다.'''
    worker_results: dict[str, str] = {}

    while True:
      ready = task_graph.ready_tasks()
      if not ready:
        break

      for node in ready:
        task_graph.update_status(node.task_id, TaskStatus.PROCESSING)

        # 에이전트 실행
        agent = self.agents.get(node.assigned_to)
        if not agent:
          task_graph.update_status(node.task_id, TaskStatus.FAILED, failure_reason=f'{node.assigned_to} 에이전트 없음')
          continue

        ref_section = reference_context[:4000] if reference_context else ''
        prompt = (
          f'[작업 지시]\n{node.description}\n\n'
          f'[원본 요구사항]\n{node.requirements}\n\n'
          f'위 지시에 따라 실무에서 바로 활용할 수 있는 수준으로 상세하게 작성하세요.\n'
          f'마크다운 형식으로 작성하세요. JSON으로 감싸지 마세요.'
        )
        content = await agent.handle(prompt, context=ref_section)

        # workspace에 저장
        filename = f'{node.task_id}/{node.task_id}.md'
        saved_paths = []
        try:
          self.workspace.write_artifact(filename, content)
          saved_paths.append(filename)
        except Exception:
          pass

        worker_results[node.task_id] = (
          f'[{node.assigned_to}] {node.description}\n결과:\n{content}\n'
        )

        # QA 중간검수
        self._state = OfficeState.QA_REVIEW
        qa_agent = self.agents['qa']
        qa_passed = await self._run_qa_check(qa_agent, node, content)

        if not qa_passed:
          # 보완 (최대 2회 — 내부 처리)
          for retry in range(1, 3):
            revision_prompt = (
              f'{node.requirements}\n\n'
              f'[이전 제출물]\n{content[:2000]}\n\n'
              f'[QA 불합격 사유]\n{node.failure_reason}\n\n'
              f'위 불합격 사유를 반영하여 수정·보완하세요.'
            )
            content = await agent.handle(revision_prompt, context=ref_section)
            try:
              self.workspace.write_artifact(filename, content)
            except Exception:
              pass
            worker_results[node.task_id] = f'[{node.assigned_to}] 보완완료:\n{content}\n'

            qa_passed = await self._run_qa_check(qa_agent, node, content)
            if qa_passed:
              break

        if qa_passed:
          task_graph.update_status(node.task_id, TaskStatus.DONE, artifact_paths=saved_paths)
          agent.record_experience(node.task_id, True, f'작업 완료: {node.description[:100]}', ['success'])
        else:
          task_graph.update_status(node.task_id, TaskStatus.FAILED, failure_reason=node.failure_reason)
          agent.record_experience(node.task_id, False, f'QA 불합격: {node.failure_reason}', ['qa_fail'])

        self._state = OfficeState.WORKING

    return worker_results

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
    '''소단계 완료 후 다른 팀원이 AI 생성 리액션을 한다 (오피스 분위기).'''
    import random

    profile_names = {'teamlead': '오상식 팀장', 'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}

    # 작업자 외 팀원 중 1~2명이 리액션
    others = [n for n in ('teamlead', 'planner', 'designer', 'developer', 'qa') if n != worker]
    reactors = random.sample(others, min(random.choice([1, 1, 2]), len(others)))

    summary_section = f'\n[작업 결과 요약]\n{content_summary[:300]}\n' if content_summary else ''

    first_reaction_text = ''
    for reactor in reactors:
      try:
        prompt = (
          f'당신은 {profile_names.get(reactor, reactor)}입니다.\n'
          f'{profile_names.get(worker, worker)}이(가) "{phase_name}" 작업을 완료했습니다.\n'
          f'{summary_section}'
          f'동료로서 당신의 전문 관점에서 리액션 한마디 해주세요.\n'
          f'20자 이내, 이모지 1개 포함, 메신저 톤. 마크다운 금지.\n'
          f'예: "구조 잘 잡혔네요 👍", "접근성도 체크해볼게요 🔍"'
        )
        response = await run_claude_isolated(
          prompt,
          model='claude-haiku-4-5-20251001',
          timeout=15.0,
        )
        text = response.strip().split('\n')[0][:30]
        if text:
          await self._emit(reactor, text, 'response')
          if not first_reaction_text:
            first_reaction_text = text
          # 업무 관련 피드백 수집
          if any(kw in text for kw in ('체크', '확인', '검토', '반영', '수정', '추가', '고려', '필요', '개선')):
            self._phase_feedback.append({
              'from': profile_names.get(reactor, reactor),
              'phase': phase_name,
              'content': text,
            })
      except Exception:
        pass

    # 30% 확률로 AI 생성 잡담
    if random.random() < 0.3:
      meme_sender = random.choice(others)
      try:
        response = await run_claude_isolated(
          f'당신은 {profile_names.get(meme_sender, meme_sender)}입니다.\n'
          f'팀이 "{phase_name}" 작업을 진행 중입니다.\n'
          f'동료들에게 가볍게 잡담 한마디 해주세요 (커피, 날씨, 야근, 회식 등).\n'
          f'15자 이내, 이모지 1개, 메신저 톤. 마크다운 금지.',
          model='claude-haiku-4-5-20251001',
          timeout=15.0,
        )
        meme = response.strip().split('\n')[0][:25]
        if meme:
          await self._emit(meme_sender, meme, 'response')
      except Exception:
        pass

    # 대화 체인: 첫 리액터 리액션 후 30% 확률로 다른 에이전트가 응답
    if first_reaction_text and random.random() < 0.3:
      chain_candidates = [n for n in others if n != reactors[0]]
      if chain_candidates:
        chain_responder = random.choice(chain_candidates)
        try:
          response = await run_claude_isolated(
            f'당신은 {profile_names.get(chain_responder, chain_responder)}입니다.\n'
            f'동료 {profile_names.get(reactors[0], reactors[0])}이(가) "{first_reaction_text}"라고 했습니다.\n'
            f'이에 대해 가볍게 한마디 응답하세요. 15자 이내, 메신저 톤. 마크다운 금지.',
            model='claude-haiku-4-5-20251001',
            timeout=15.0,
          )
          chain_text = response.strip().split('\n')[0][:25]
          if chain_text:
            await self._emit(chain_responder, chain_text, 'response')
        except Exception:
          pass

  async def _handoff_comment(self, from_agent: str, to_agent: str, phase_name: str) -> None:
    '''그룹 전환 시 이전 담당자가 다음 담당자에게 인수인계 코멘트를 남긴다.'''
    profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}
    from_name = profile_names.get(from_agent, from_agent)
    to_name = profile_names.get(to_agent, to_agent)
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
      pass

  async def _task_acknowledgment(self, agent_name: str, phase_name: str) -> None:
    '''업무 수령 시 담당자가 간단한 확인 메시지를 보낸다.'''
    profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}
    try:
      response = await run_claude_isolated(
        f'당신은 {profile_names.get(agent_name, agent_name)}입니다.\n'
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
      await self._emit(agent_name, '네, 확인했습니다. 시작하겠습니다.', 'response')

  async def _contextual_reaction(self, reactor: str, phase_name: str, worker: str) -> str:
    '''Haiku로 해당 캐릭터가 할 법한 문맥 리액션 한마디 생성 (15자 이내).'''
    profile_names = {'teamlead': '오상식 팀장', 'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}
    try:
      response = await run_claude_isolated(
        f'당신은 {profile_names.get(reactor, reactor)}입니다.\n'
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
      return ''

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
    profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}

    try:
      response = await run_claude_isolated(
        f'당신은 {profile_names.get(commenter, commenter)}입니다.\n'
        f'{profile_names.get(worker, worker)}이(가) "{phase_name}" 작업을 완료했습니다.\n'
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
      pass

  async def _phase_intro(self, agent_name: str, phase_name: str) -> None:
    '''프로젝트 각 단계 시작 시 담당 에이전트가 작업 포부/계획을 한마디 한다.'''
    profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율'}
    fallback_intros = {
      'planner': '기획 구조 잡아볼게요 📋',
      'designer': '디자인 방향 잡겠습니다 🎨',
      'developer': '코드 작성 들어갑니다 💻',
      'qa': '검수 기준 세우겠습니다 🔍',
    }
    try:
      response = await run_claude_isolated(
        f'당신은 {profile_names.get(agent_name, agent_name)}입니다.\n'
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
      pass
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
      return

    # @멘션 파싱
    mentions = re.findall(r'@([가-힣A-Za-z]+(?:님)?)', msg)
    profile_names = {'planner': '장그래', 'designer': '안영이', 'developer': '김동식', 'qa': '한석율', 'teamlead': '오상식 팀장'}

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
              f'당신은 팀장 오상식입니다. 팀이 작업 중인데 사용자가 이렇게 말했습니다:\n'
              f'"{msg}"\n짧게 1~2문장으로 응답하세요 (메신저 톤, 마크다운 금지).',
              model='claude-haiku-4-5-20251001',
              timeout=15.0,
            )
            await self._emit('teamlead', response.strip(), 'response')
          except Exception:
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
            pass
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
      pass

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
      f'합격이면 첫 줄에 [PASS]를, 불합격이면 [FAIL]을 적고 이유를 적으세요.'
    )

    response = await run_claude_isolated(prompt, timeout=120.0)
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
