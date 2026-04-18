# Office — 진짜 사무실처럼 동작하는 오케스트레이션 시스템
from __future__ import annotations
# 팀장이 판단하고, 팀원이 협업하고, 회의를 통해 프로젝트를 진행한다.
import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

from core import paths
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
  project_runner,
  suggestion_filer,
)
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


from orchestration.state import OfficeState  # re-export for main.py, tests


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
    memory_root: str | Path | None = None,
  ):
    if memory_root is None:
      memory_root = paths.MEMORY_ROOT
    self.bus = bus
    self.event_bus = event_bus
    self.workspace = workspace
    self._state = OfficeState.IDLE
    self._revision_count = 0
    self._memory_root = Path(memory_root)
    self._context_summary = ''  # 기획자가 압축한 이전 대화 요약
    self._task_count = 0        # 업무 횟수 카운터
    self._pending_project = None  # 사용자 확인 대기 중인 프로젝트
    self._pending_job: dict | None = None  # 필드 입력 대기 중인 Job
    self._discovery_state: Any = None     # DiscoveryState | None
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
    self._current_task_id: str = ''
    self._user_mid_feedback: list[str] = []  # 작업 중 사용자 피드백 축적
    self._phase_feedback: list[dict] = []   # 팀원 리액션/인수인계 피드백
    self._current_project_type: str = ''    # 현재 프로젝트 유형 (phase_registry)

    # 자가개선 엔진
    self.improvement_engine = ImprovementEngine(event_bus=event_bus)

    # 팀 공유 메모리
    self.team_memory = TeamMemory(memory_root=memory_root)

    # 자발적 활동 제어
    self._autonomous_running = False
    self._autonomous_task: asyncio.Task[None] | None = None

    # receive() 중복 실행 방지
    self._receive_lock: asyncio.Lock = asyncio.Lock()
    # _context_summary 동시 쓰기 방지
    self._context_lock: asyncio.Lock = asyncio.Lock()

    # 팀장 배치 리뷰 (main.py 기동 시 주입)
    self._review_running = False
    self._review_lock: asyncio.Lock | None = None
    self._teamlead_review_task: asyncio.Task[None] | None = None
    self.latest_digest_summary: str = ''

    # 팀원 초기화
    self.agents: dict[str, Agent] = {}
    for name in ('planner', 'designer', 'developer', 'qa'):
      self.agents[name] = Agent(
        name=name,
        event_bus=event_bus,
        memory_root=memory_root,
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
        self.workspace = WorkspaceManager(task_id=task_id, workspace_root=str(paths.WORKSPACE_ROOT))
        await self._emit(
          'teamlead',
          f'@마스터 이전에 확인 요청드린 사항이 있습니다. 답변해 주시면 이어서 진행하겠습니다.',
          'response',
        )
      elif state == 'running':
        # 프로젝트 컨텍스트(context_json)가 있는 'running'만 실제 중단 복구 대상.
        # 단순 채팅("어흥" 등)도 잠시 running으로 올라가므로, context 없으면
        # 조용히 cancelled 처리하고 재개 프롬프트를 띄우지 않는다.
        if not ctx:
          update_task_state(task_id, 'cancelled')
          continue
        update_task_state(task_id, 'interrupted')
        self._interrupted_instruction = instruction
        self._interrupted_task_id = task_id
        from workspace.manager import WorkspaceManager
        self.workspace = WorkspaceManager(task_id=task_id, workspace_root=str(paths.WORKSPACE_ROOT))
        await self._emit(
          'teamlead',
          f'@마스터 서버 재시작으로 중단된 작업이 있습니다: "{instruction_preview}..."\n이어서 진행하려면 말씀해 주세요.',
          'response',
        )

  async def _emit(self, agent_id: str, message: str, event_type: str = 'message', data: dict | None = None) -> LogEvent:
    '''이벤트 버스에 로그 발행. 후속 건의 등록 등에서 추적용으로 event를 반환.'''
    event = LogEvent(agent_id=agent_id, event_type=event_type, message=message, data=data or {})
    await self.event_bus.publish(event)
    return event

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
      from runners.model_router import run as router_run
      summary, _ = await router_run(tier='nano', prompt=f'{system}\n\n---\n\n{prompt}', timeout=60.0)
      async with self._context_lock:
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
    self._context_summary = '\n'.join(updated[-15:])  # GIL 보호 — CPython 단일 바인딩은 atomic


  async def receive(self, user_input: str) -> dict[str, Any]:
    '''사용자 입력을 받아 처리한다.

    Returns:
      {'state': str, 'response': str, 'artifacts': list[str]}
    '''
    if not self._receive_lock.locked():
      async with self._receive_lock:
        return await self._receive_inner(user_input)

    # 락 잠김 — 대화/Discovery 응답이 완료될 때까지 최대 10초 대기
    try:
      async with asyncio.timeout(10.0):
        async with self._receive_lock:
          return await self._receive_inner(user_input)
    except asyncio.TimeoutError:
      await self._emit(
        'teamlead',
        '현재 다른 요청을 처리 중입니다. 잠시 후 다시 말씀해 주세요.',
        'response',
      )
      return {'state': self._state.value, 'response': '', 'artifacts': []}

  async def _receive_inner(self, user_input: str) -> dict[str, Any]:
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

    # -1. Discovery 대화 진행 중 — 멀티턴 요구사항 수집
    if self._discovery_state is not None:
      from orchestration.discovery import continue_discovery
      result = await continue_discovery(self, self._discovery_state, user_input)
      self._discovery_state = result
      self._state = OfficeState.COMPLETED
      self._active_agent = ''
      self._work_started_at = ''
      return {'state': self._state.value, 'response': '', 'artifacts': []}

    # 0. 대기 중인 Job 필드 입력 — 이전 턴에서 누락 필드를 물었을 때
    if hasattr(self, '_pending_job') and self._pending_job:
      pending = self._pending_job
      self._pending_job = None
      spec_id = pending['spec_id']
      job_input = dict(pending['job_input'])
      orig_input = pending.get('orig_input', user_input)
      attachments = pending.get('attachments_text', '')

      if 'clarifying_fields' in pending:
        # Haiku가 자유응답을 field→value로 파싱
        parsed = await _parse_clarification_answer(user_input, pending['clarifying_fields'])
        job_input.update(parsed)
      else:
        # required 필드 단순 채우기
        job_input[pending['missing'][0]] = user_input.strip()

      return await self._handle_job(spec_id, job_input, orig_input,
                                    attachments_text=attachments, skip_clarify=True)

    # 0-1. 대기 중인 프로젝트가 있으면 사용자 답변으로 이어서 진행
    if hasattr(self, '_pending_project') and self._pending_project:
      return await project_runner._continue_project(self, user_input)

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
          ws_root = str(paths.WORKSPACE_ROOT)
          self.workspace = WorkspaceManager(task_id=original_task_id, workspace_root=ws_root)
        return await self._receive_inner(original)
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
    recent_logs: list = []
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
          workspace_root=str(paths.WORKSPACE_ROOT),
        )
        if self._current_task_id:
          update_task_project(self._current_task_id,self._active_project_id)
        await self._emit('system', f'📂 프로젝트 이어가기: {self._active_project_title}', 'project_update')
      else:
        # 새 프로젝트 시작 — 이전 프로젝트 컨텍스트 초기화 (다른 프로젝트 대화 오염 방지)
        self._context_summary = ''
        self._user_mid_feedback = []
        self._phase_feedback = []
        for agent in self.agents.values():
          agent._conversation_history = []
        if self._active_project_id:
          archive_project(self._active_project_id)

        ws_root = str(paths.WORKSPACE_ROOT)
        new_pid = str(uuid.uuid4())
        title = await generate_project_title(user_input)

        create_project(new_pid, title)
        self._active_project_id = new_pid
        self._active_project_title = title
        self.workspace = WorkspaceManager(task_id=new_pid, workspace_root=ws_root)
        if self._current_task_id:
          update_task_project(self._current_task_id,new_pid)
        await self._emit('system', f'📂 새 프로젝트: {title}', 'project_update')

    # 3. 의도별 분기
    if intent_result.intent == IntentType.CONVERSATION:
      from orchestration.intent import generate_teamlead_reply, DEEP_THINK_KEYWORDS

      # 딥씽크 키워드 감지 → Opus, 아니면 Gemini
      deep = any(kw in user_input for kw in DEEP_THINK_KEYWORDS)

      # 최근 대화를 메모리 컨텍스트로 전달 (최근 6턴, 각 150자)
      memory_ctx = '\n'.join(
        f'[{l["agent_id"]}] {l["message"][:150]}'
        for l in recent_logs[-6:]
        if l.get('event_type') in ('response', 'message') and l.get('agent_id') != 'system'
      )

      response = await generate_teamlead_reply(user_input, memory_ctx, deep=deep)

      await self._emit('teamlead', response, 'response')
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

    if intent_result.intent in (IntentType.QUICK_TASK, IntentType.PROJECT, IntentType.CONTINUE_PROJECT):
      # 첨부파일 블록 분리
      _ATTACH_SEP = '\n\n[첨부된 참조 자료]\n'
      if _ATTACH_SEP in user_input:
        clean_input, chat_attachments = user_input.split(_ATTACH_SEP, 1)
      else:
        clean_input, chat_attachments = user_input, ''

      from orchestration.discovery import should_enter_discovery, start_discovery
      if should_enter_discovery(clean_input, chat_attachments):
        # Discovery 모드 — 대화부터 시작, 나중에 Job 매핑
        self._discovery_state = await start_discovery(self, clean_input, chat_attachments)
        self._state = OfficeState.COMPLETED
        self._active_agent = ''
        self._work_started_at = ''
        return {'state': self._state.value, 'response': '', 'artifacts': []}

      # 명확한 요청 — 바로 Job 매핑 후 등록
      from orchestration.intent import map_to_job_spec
      spec_id, job_input, conf = await map_to_job_spec(clean_input, combined_context)
      if not spec_id or conf < 0.5:
        spec_id = 'research'
        job_input = {'topic': clean_input[:500]}
      return await self._handle_job(spec_id, job_input, clean_input, attachments_text=chat_attachments)

    if intent_result.intent == IntentType.JOB:
      # JOB 처리 로직 → job_handler 모듈로 위임 (4-1)
      from orchestration.job_handler import dispatch as _job_dispatch
      return await _job_dispatch(self, intent_result, user_input)

    # 기본값
    self._state = OfficeState.COMPLETED
    return {'state': self._state.value, 'response': '처리할 수 없는 입력입니다.', 'artifacts': []}

  async def _handle_job(
    self,
    spec_id: str,
    job_input: dict[str, Any],
    user_input: str,
    attachments_text: str = '',
    skip_clarify: bool = False,
  ) -> dict[str, Any]:
    '''Job 파이프라인을 생성하고 팀장이 결과를 알린다.'''
    from jobs.registry import get as get_spec
    from jobs.runner import submit as job_submit

    self._state = OfficeState.TEAMLEAD_THINKING
    self._active_agent = 'teamlead'
    self._work_started_at = datetime.now(timezone.utc).isoformat()

    spec = get_spec(spec_id)
    if not spec:
      await self._emit(
        'teamlead',
        f'"{spec_id}" Job 스펙을 찾을 수 없습니다. Job Board에서 직접 생성해 주세요.',
        'response',
      )
      self._state = OfficeState.COMPLETED
      self._active_agent = ''
      self._work_started_at = ''
      return {'state': self._state.value, 'response': '', 'artifacts': []}

    # 필수 입력 필드 누락 확인 (빈 문자열도 누락으로 처리)
    missing = [f for f in spec.required_fields if not job_input.get(f, '').strip()]
    if missing:
      field = missing[0]
      field_labels = {
        'topic': '어떤 주제로 리서치할까요?',
        'product': '어떤 제품/서비스인가요?',
        'goals': '목표가 무엇인가요?',
        'project': '어떤 프로젝트인가요?',
        'screen': '어떤 화면을 퍼블리싱할까요?',
        'spec': '화면 명세를 알려주세요.',
        'artifact': '검토할 산출물을 알려주세요.',
      }
      question = field_labels.get(field, f'{field}를 알려주세요.')
      await self._emit('teamlead', f'**{spec.title}** 작업을 등록하겠습니다. {question}', 'response')
      # 다음 턴에서 이어서 처리할 수 있도록 상태 저장
      self._pending_job = {
        'spec_id': spec_id,
        'job_input': job_input,
        'missing': missing,
        'orig_input': user_input,
        'attachments_text': attachments_text,
      }
      self._state = OfficeState.COMPLETED
      self._active_agent = ''
      self._work_started_at = ''
      return {'state': self._state.value, 'response': '', 'artifacts': []}

    # 이전 잡 산출물 자동 주입 제거 — 주제가 다른 잡 산출물이 오염되는 문제 방지.

    # 채팅 경유 clarification — Haiku가 활성 툴 + spec 보고 동적으로 질문 생성
    if not skip_clarify:
      already_answered = set(k for k, v in job_input.items() if str(v).strip())
      questions = await _generate_clarification_questions(spec, job_input, already_answered)
      # 이미 입력된 필드는 제외
      questions = [q for q in questions if not str(job_input.get(q['field'], '')).strip()]
      if questions:
        lines = [f'{i + 1}. {q["question"]}' for i, q in enumerate(questions)]
        await self._emit(
          'teamlead',
          f'**{spec.title}** 작업 등록 전에 몇 가지 확인할게요.\n\n' + '\n'.join(lines),
          'response',
        )
        self._pending_job = {
          'spec_id': spec_id,
          'job_input': job_input,
          'clarifying_fields': [q['field'] for q in questions],
          'orig_input': user_input,
          'attachments_text': attachments_text,
        }
        self._state = OfficeState.COMPLETED
        self._active_agent = ''
        self._work_started_at = ''
        return {'state': self._state.value, 'response': '', 'artifacts': []}

    job_title = await _generate_job_title(spec.title, job_input, user_input)
    job = await job_submit(spec, job_input, title=job_title, attachments_text=attachments_text)

    await self._emit(
      'teamlead',
      f'**{spec.title}** 작업을 작업보드에 등록했습니다.',
      'response',
      data={'job_id': job.id, 'spec_id': spec.id, 'job_title': job.title},
    )
    self._state = OfficeState.COMPLETED
    self._active_agent = ''
    self._work_started_at = ''
    return {'state': self._state.value, 'response': '', 'artifacts': []}


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


async def _generate_clarification_questions(
  spec: Any, job_input: dict, already_answered: set[str]
) -> list[dict[str, str]]:
  """Haiku가 활성 툴 + spec 정보를 보고 clarification 질문을 동적으로 생성한다.

  Returns:
    [{"field": "output_format", "question": "...결과물 형식은?..."}, ...]
    최대 3개, 빈 리스트면 즉시 제출.
  """
  from runners.claude_runner import run_claude_isolated
  from jobs.tool_registry import list_tools
  import json as _json

  # 활성(사용 가능) 툴만 추림
  all_tools = list_tools()
  active_tools = [
    f"- {t['id']}: {t['description']}"
    for t in all_tools
    if t.get('enabled') or t.get('token_set')
  ]
  tools_text = '\n'.join(active_tools) if active_tools else '(없음)'

  # spec 스텝들이 사용하는 툴
  spec_tools = sorted({t for s in spec.steps for t in getattr(s, 'tools', [])})

  # spec에 정의된 field_questions 힌트
  hints = '\n'.join(f'- {f}: {q}' for f, q in spec.field_questions.items()) if spec.field_questions else '(없음)'

  # 이미 채워진 입력값
  filled = {k: v for k, v in job_input.items() if v and k not in already_answered}

  prompt = (
    f'아래 Job 실행 전에 사용자에게 물어볼 clarification 질문 목록을 생성하세요.\n\n'
    f'=== Job 정보 ===\n'
    f'제목: {spec.title}\n'
    f'설명: {spec.description}\n'
    f'이 Job이 사용하는 툴: {", ".join(spec_tools) if spec_tools else "없음"}\n\n'
    f'=== 현재 시스템에서 활성화된 툴 ===\n{tools_text}\n\n'
    f'=== 이미 입력된 값 ===\n'
    + '\n'.join(f'- {k}: {v}' for k, v in filled.items() if k not in ('_attachments',))
    + f'\n\n=== spec 권장 질문 힌트 ===\n{hints}\n\n'
    f'규칙:\n'
    f'1. 활성화된 툴이 지원하는 출력 형식(HTML/마크다운/다이어그램/SVG/이미지 등) 중 가능한 것을 선택지로 제시하는 output_format 질문은 반드시 포함하세요.\n'
    f'2. 이미 입력된 값은 다시 묻지 마세요.\n'
    f'3. 최대 3개 질문만 생성하세요 (꼭 필요한 것만).\n'
    f'4. 반드시 JSON 배열만 출력 (설명 없이):\n'
    f'[{{"field": "output_format", "question": "결과물을 어떤 형식으로 받고 싶으세요? (선택지: ...)"}}]'
  )

  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=15.0)
    m = re.search(r'\[[\s\S]*\]', raw)
    if m:
      items = _json.loads(m.group())
      return [
        {'field': str(x['field']), 'question': str(x['question'])}
        for x in items
        if isinstance(x, dict) and 'field' in x and 'question' in x
      ][:3]
  except Exception:
    logger.debug('_generate_clarification_questions 실패', exc_info=True)

  # 폴백: 최소 output_format 하나는 반환
  return [{'field': 'output_format', 'question': '결과물 형식은 어떻게 드릴까요? (마크다운 / HTML)'}]


async def _parse_clarification_answer(user_answer: str, fields: list[str]) -> dict[str, str]:
  """사용자의 자유응답을 field→value dict로 파싱한다 (Haiku 사용)."""
  from runners.claude_runner import run_claude_isolated
  import json as _json

  fields_str = ', '.join(fields)
  example = '{' + ', '.join(f'"{f}": ""' for f in fields) + '}'
  prompt = (
    f'사용자가 아래 필드들에 대한 답변을 자유롭게 했습니다.\n'
    f'필드 목록: {fields_str}\n\n'
    f'사용자 답변: "{user_answer}"\n\n'
    f'각 필드에 해당하는 값을 JSON으로 추출하세요. '
    f'언급하지 않은 필드는 빈 문자열("")로 두세요.\n'
    f'반드시 JSON만 출력 (설명 없이):\n'
    f'{example}'
  )
  try:
    raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=15.0)
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
      parsed = _json.loads(m.group())
      return {k: str(v) for k, v in parsed.items() if k in fields and v}
  except Exception:
    pass
  # 파싱 실패 시 전체 응답을 첫 번째 필드에 넣기
  return {fields[0]: user_answer.strip()} if fields else {}


async def _generate_job_title(spec_title: str, job_input: dict, user_input: str) -> str:
  """Job 제목을 LLM으로 생성한다. 실패 시 spec 제목 + 핵심 키워드 조합으로 대체."""
  from runners.claude_runner import run_claude_isolated

  # job_input에서 핵심 값 추출 (첫 번째 non-empty 값)
  main_value = next((str(v)[:60] for v in job_input.values() if v and str(v).strip()), '')
  context = main_value or user_input[:80]

  prompt = (
    f'아래 작업 정보를 보고 간결한 작업 제목을 한 줄로 만들어주세요.\n\n'
    f'작업 유형: {spec_title}\n'
    f'핵심 내용: {context}\n\n'
    f'규칙:\n'
    f'- 15자 이내, 명사형으로 끝내기\n'
    f'- 구체적이고 핵심만 담기 (예: "2026 컬러 트렌드 리서치", "메인 화면 UX 기획")\n'
    f'- 제목만 출력, 따옴표나 부연 설명 없이'
  )
  try:
    title = await run_claude_isolated(
      prompt, model='claude-haiku-4-5-20251001', timeout=10.0, max_turns=1,
    )
    title = title.strip().strip('"\'「」').strip()
    if title and len(title) <= 40:
      return title
  except Exception:
    pass

  # 폴백: spec 제목 + 핵심 키워드
  if main_value:
    return f'{spec_title} — {main_value[:20]}'
  return spec_title

