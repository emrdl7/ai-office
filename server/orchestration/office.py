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
from orchestration import (
  agent_interactions,
  autonomous_loop,
  project_runner,
  suggestion_filer,
  teamlead_review,
)
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
    return await agent_interactions._team_chat(self, user_input, chat_subtype, teamlead_response)

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

  async def _handle_quick_task(self, *args, **kwargs):
    return await project_runner._handle_quick_task(self, *args, **kwargs)

  async def _handle_project(self, *args, **kwargs):
    return await project_runner._handle_project(self, *args, **kwargs)

  async def _continue_project(self, user_answer: str) -> dict[str, Any]:
    return await project_runner._continue_project(self, user_answer)

  async def _plan_project_phases(self, *args, **kwargs):
    return await project_runner._plan_project_phases(self, *args, **kwargs)

  def _default_phases(self, user_input: str) -> tuple[list[dict], str]:
    return project_runner._default_phases(self, user_input)

  async def _execute_project(self, *args, **kwargs):
    return await project_runner._execute_project(self, *args, **kwargs)

  async def _auto_export(self, phase_artifacts: list[str]) -> None:
    return await project_runner._auto_export(self, phase_artifacts)

  async def _cross_review(self, group_name: str, all_results: dict[str, str]) -> None:
    return await project_runner._cross_review(self, group_name, all_results)

  async def _extract_user_questions(self, user_input: str, meeting_summary: str) -> str:
    return await project_runner._extract_user_questions(self, user_input, meeting_summary)

  async def _check_user_directive(self) -> dict | None:
    return await project_runner._check_user_directive(self)

  async def _team_reaction(self, worker: str, phase_name: str, content_summary: str = '') -> None:
    return await agent_interactions._team_reaction(self, worker, phase_name, content_summary)

  async def _consult_peers(self, *args, **kwargs):
    return await agent_interactions._consult_peers(self, *args, **kwargs)

  def _record_dynamic(
    self,
    from_agent: str,
    to_agent: str,
    dynamic_type: str,
    description: str,
  ) -> None:
    '''팀 다이나믹 기록 래퍼 — 상호작용 후처리 훅.

    dynamic_type: 'peer_concern' | 'peer_approved' | 'consulted'
                | 'committed_to_request' | 'needs_clarification' | 그 외 자유.
    기록 실패는 조용히 무시 (본 작업 영향 방지).
    '''
    if not from_agent or not to_agent or from_agent == to_agent:
      return
    try:
      self.team_memory.add_dynamic(TeamDynamic(
        from_agent=from_agent,
        to_agent=to_agent,
        dynamic_type=dynamic_type,
        description=description[:100],
        timestamp=datetime.now(timezone.utc).isoformat(),
      ))
    except Exception:
      logger.debug('팀 다이나믹 기록 실패: %s→%s (%s)', from_agent, to_agent, dynamic_type, exc_info=True)

  # 피어 리뷰어 매핑: 작업자 역할 → 리뷰어 목록
  _PEER_REVIEWERS: dict[str, list[str]] = {
    'planner': ['designer', 'developer'],
    'designer': ['developer', 'planner'],
    'developer': ['designer', 'planner'],
  }

  async def _peer_review(self, worker_name: str, phase_name: str, content: str, user_input: str) -> list[dict]:
    return await agent_interactions._peer_review(self, worker_name, phase_name, content, user_input)

  async def _handoff_comment(self, from_agent: str, to_agent: str, phase_name: str) -> None:
    return await agent_interactions._handoff_comment(self, from_agent, to_agent, phase_name)

  async def _task_acknowledgment(self, agent_name: str, phase_name: str) -> None:
    return await agent_interactions._task_acknowledgment(self, agent_name, phase_name)

  async def _contextual_reaction(self, reactor: str, phase_name: str, worker: str) -> str:
    return await agent_interactions._contextual_reaction(self, reactor, phase_name, worker)

  def _resolve_reviewer(self, worker: str, prompt: str) -> tuple[str, str] | None:
    return agent_interactions._resolve_reviewer(self, worker, prompt)

  async def _quick_task_second_opinion(self, *args, **kwargs):
    return await project_runner._quick_task_second_opinion(self, *args, **kwargs)

  async def _work_commentary(self, worker: str, phase_name: str, result_preview: str) -> None:
    return await agent_interactions._work_commentary(self, worker, phase_name, result_preview)

  async def _phase_intro(self, agent_name: str, phase_name: str) -> None:
    return await agent_interactions._phase_intro(self, agent_name, phase_name)

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
    return await project_runner._create_handoff_guide(self, group_name, group_results, target_phase)

  async def _generate_stitch_mockup(self, all_results: dict, user_input: str) -> None:
    return await project_runner._generate_stitch_mockup(self, all_results, user_input)

  async def _run_qa_check(self, qa_agent: Agent, node: TaskNode, content: str) -> bool:
    return await project_runner._run_qa_check(self, qa_agent, node, content)

  async def _run_planner_synthesize(self, *args, **kwargs):
    return await project_runner._run_planner_synthesize(self, *args, **kwargs)

  async def _teamlead_final_review(self, user_input: str, task_graph: TaskGraph) -> bool:
    return await project_runner._teamlead_final_review(self, user_input, task_graph)

  async def _route_agent_mentions(self, speaker: str, content: str) -> None:
    return await agent_interactions._route_agent_mentions(self, speaker, content)

  # ──────────────────────────────────────────────────────────────
  # 자발적 활동 시스템 (Phase 2)
  # ──────────────────────────────────────────────────────────────

  _DIGEST_PATH = Path(__file__).parent.parent / 'data' / 'team_digests.json'

  async def start_autonomous_loop(self) -> None:
    '''자율 활동 루프 — autonomous_loop 모듈로 위임.'''
    return await autonomous_loop.run_loop(self)

  def stop_autonomous_loop(self) -> None:
    '''자발적 활동 루프를 중단한다.'''
    autonomous_loop.stop_loop(self)

  def _load_digest_state(self) -> dict:
    return autonomous_loop.load_digest_state(self)

  def _save_digest_state(self, state: dict) -> None:
    autonomous_loop.save_digest_state(self, state)

  async def start_teamlead_review_loop(self) -> None:
    '''팀장 배치 리뷰 루프 — teamlead_review 모듈로 위임.'''
    return await teamlead_review.run_loop(self)

  async def _run_single_review(self, force: bool = False) -> None:
    '''배치 리뷰 1회 실행 — teamlead_review 모듈로 위임. main.py 어드민 엔드포인트 호환.'''
    return await teamlead_review.run_single(self, force=force)

  def stop_teamlead_review_loop(self) -> None:
    teamlead_review.stop_loop(self)

  async def _team_retrospective(
    self,
    project_title: str,
    project_type: str,
    all_results: dict[str, str],
    user_input: str,
    duration: float,
  ) -> None:
    '''프로젝트 완료 회고 — teamlead_review 모듈로 위임.'''
    return await teamlead_review.run_retrospective(
      self, project_title, project_type, all_results, user_input, duration,
    )
  # ──────────────────────────────────────────────────────────────
  # 리액션 기반 상호작용 (Task #9, #10)
  # ──────────────────────────────────────────────────────────────

  async def _react_to_received_reactions(self) -> None:
    '''리액션 답례 — autonomous_loop 모듈로 위임.'''
    return await autonomous_loop.react_to_received_reactions(self)

  async def _agents_react_to_peers(self) -> None:
    '''피어 이모지 리액션 — autonomous_loop 모듈로 위임.'''
    return await autonomous_loop.agents_react_to_peers(self)

  async def _autonomous_react(
    self,
    reactor_name: str,
    prior_speaker: str,
    prior_message: str,
  ) -> str:
    '''자발 1단 반응 — autonomous_loop 모듈로 위임.'''
    return await autonomous_loop.autonomous_react(reactor_name, prior_speaker, prior_message)

  async def _autonomous_closing(
    self,
    original_speaker: str,
    original_message: str,
    challenger: str,
    challenge: str,
  ) -> str:
    '''자발 2단 결론 — autonomous_loop 모듈로 위임.'''
    return await autonomous_loop.autonomous_closing(original_speaker, original_message, challenger, challenge)


  async def _file_reaction_suggestion(self, agent_id: str, phase_name: str, message: str) -> None:
    return await suggestion_filer._file_reaction_suggestion(self, agent_id, phase_name, message)

  async def _auto_file_suggestion(self, agent_id: str, message: str) -> None:
    return await suggestion_filer._auto_file_suggestion(self, agent_id, message)

  async def _file_commitment_suggestion(self, committer_id: str, message: str, source_speaker: str = '', source_message: str = '') -> None:
    return await suggestion_filer._file_commitment_suggestion(self, committer_id, message, source_speaker, source_message)
