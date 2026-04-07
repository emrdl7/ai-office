# Office — 진짜 사무실처럼 동작하는 오케스트레이션 시스템
from __future__ import annotations
# 팀장이 판단하고, 팀원이 협업하고, 회의를 통해 프로젝트를 진행한다.
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from orchestration.intent import IntentType, classify_intent
from orchestration.agent import Agent
from orchestration.meeting import Meeting
from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
from runners.groq_runner import GroqRunner
from runners.claude_runner import run_claude_isolated
from runners.opencode_runner import run_opencode
from bus.message_bus import MessageBus
from bus.payloads import TaskRequestPayload, TaskResultPayload
from log_bus.event_bus import EventBus, LogEvent
from workspace.manager import WorkspaceManager
from harness.file_reader import resolve_references
from harness.code_runner import run_code
from harness.rejection_analyzer import record_rejection, get_past_rejections
from harness.stitch_client import designer_generate_with_context

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

    # Groq 러너 (디자이너, QA용)
    self.groq_runner = GroqRunner()

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
    from db.task_store import get_resumable_tasks, update_task_state

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
      summary = await run_opencode(prompt=prompt, system=system)
      self._context_summary = summary.strip()
      # 각 에이전트의 대화 기록도 초기화
      for agent in self.agents.values():
        agent._conversation_history = []
    except Exception:
      pass

  async def _team_chat(self, user_input: str) -> None:
    '''팀 채널 대화 — 각 팀원이 자기가 반응할지 스스로 판단한다.

    필요 없으면 [PASS]로 넘기고, 할 말이 있을 때만 응답한다.
    아무도 안 답하면 랜덤 한 명이 대표로 답변한다.
    '''
    from runners.groq_runner import MODEL as GROQ_MODEL
    agent_model_map = {
      'planner': 'Gemini CLI',
      'designer': 'Claude Sonnet',
      'developer': 'Gemini CLI',
      'qa': 'Claude Haiku 4.5',
    }

    responded: list[str] = []
    for name in ('planner', 'designer', 'developer', 'qa'):
      agent = self.agents.get(name)
      if not agent:
        continue
      system = agent._build_system_prompt()
      my_model = agent_model_map.get(name, '알 수 없음')
      prompt = (
        f'팀 채팅방에서 사용자(팀장의 상사)가 이렇게 말했습니다:\n\n'
        f'"{user_input}"\n\n'
        f'당신은 {name}입니다. 당신이 사용하는 AI 모델/러너는 "{my_model}"입니다.\n'
        f'모델이나 자기소개를 물어보면 이 정보를 기반으로 답하세요.\n\n'
        f'이 메시지에 당신이 반응해야 하는지 판단하세요.\n\n'
        f'판단 기준:\n'
        f'- 당신의 전문 영역과 관련이 있는가?\n'
        f'- 당신을 지목했거나 당신이 대답해야 자연스러운가?\n'
        f'- 전체 인사(안녕, 수고 등)라도 모두가 답할 필요는 없다\n\n'
        f'반응할 필요가 없으면 [PASS] 한 단어만 출력하세요.\n'
        f'반응할 필요가 있으면 짧게 1~2문장으로 답하세요 (메신저 대화처럼, 마크다운 금지).'
      )
      try:
        response = await self.groq_runner.generate(prompt, system=system)
        content = response.strip()
        # 마크다운 펜스 제거
        if content.startswith('```'):
          lines = content.split('\n')
          lines = lines[1:]
          if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
          content = '\n'.join(lines)
        # [PASS]면 넘기기
        if content.upper().startswith('[PASS]') or content.upper() == 'PASS':
          continue
        responded.append(name)
        await self._emit(name, content, 'response')
      except Exception:
        pass

    # 아무도 안 답하면 랜덤 한 명이 답변 (왕따 방지)
    if not responded:
      import random
      fallback_name = random.choice(['planner', 'designer', 'developer', 'qa'])
      agent = self.agents[fallback_name]
      system = agent._build_system_prompt()
      prompt = (
        f'팀 채팅방에서 사용자가 "{user_input}"라고 했는데 아무도 답을 안 했습니다.\n'
        f'당신이 대표로 한마디 해주세요. 짧고 자연스럽게. 마크다운 금지.'
      )
      try:
        response = await self.groq_runner.generate(prompt, system=system)
        content = response.strip()
        if content.startswith('```'):
          lines = content.split('\n')
          lines = lines[1:]
          if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
          content = '\n'.join(lines)
        await self._emit(fallback_name, content, 'response')
      except Exception:
        pass

  async def receive(self, user_input: str) -> dict[str, Any]:
    '''사용자 입력을 받아 처리한다.

    Returns:
      {'state': str, 'response': str, 'artifacts': list[str]}
    '''
    self._state = OfficeState.TEAMLEAD_THINKING

    # 0. 대기 중인 프로젝트가 있으면 사용자 답변으로 이어서 진행
    if hasattr(self, '_pending_project') and self._pending_project:
      return await self._continue_project(user_input)

    # 0-1. 중단된 작업이 있고 사용자가 재개를 요청하면 원래 instruction으로 재실행
    if hasattr(self, '_interrupted_instruction') and self._interrupted_instruction:
      resume_keywords = ('진행', '이어서', '계속', '재개', '다시', 'ㅇㅇ', '응', '네', 'yes', 'ok')
      if any(kw in user_input.lower() for kw in resume_keywords):
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
            from workspace.manager import WorkspaceManager
            WORKSPACE_ROOT = Path(__file__).parent.parent.parent / 'workspace'
            self.workspace = WorkspaceManager(task_id=original_task_id, workspace_root=str(WORKSPACE_ROOT))
          return await self.receive(original)
      else:
        # 다른 입력이면 중단 작업 폐기
        self._interrupted_instruction = None
        self._interrupted_task_id = None
        self._interrupted_confirmed = False

    # 1. 파일 참조 해석
    reference_context = resolve_references(user_input)

    # 2. 팀장 판단
    intent_result = await classify_intent(user_input)

    # 2. 업무 시작 시 이전 대화 압축
    if intent_result.intent in (IntentType.QUICK_TASK, IntentType.PROJECT):
      if self._task_count > 0:
        await self._compress_history()
      self._task_count += 1
      self._revision_count = 0

    # 3. 의도별 분기
    if intent_result.intent == IntentType.CONVERSATION:
      response = intent_result.direct_response or ''
      await self._emit('teamlead', response, 'response')

      # 팀 채널 대화면 팀원들도 각자 반응
      await self._team_chat(user_input)

      self._state = OfficeState.COMPLETED
      self._active_agent = ''
      self._work_started_at = ''
      return {
        'state': self._state.value,
        'response': response,
        'artifacts': [],
      }

    if intent_result.intent == IntentType.QUICK_TASK:
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

    prompt = analysis or user_input
    # 이전 대화 요약 + 참조 자료를 컨텍스트로 전달
    ctx_parts = []
    if self._context_summary:
      ctx_parts.append(f'[이전 대화 요약]\n{self._context_summary}')
    if reference_context:
      ctx_parts.append(reference_context)
    result = await agent.handle(prompt, context='\n\n'.join(ctx_parts))

    # 결과를 workspace에 저장
    saved_paths = []
    try:
      file_path = 'quick-task/result.md'
      self.workspace.write_artifact(file_path, result)
      saved_paths.append(f'{self.workspace.task_id}/{file_path}')
    except Exception:
      pass

    self._state = OfficeState.COMPLETED
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

    # 1. 회의 소집 — 방향 잡기
    self._state = OfficeState.MEETING
    await self._emit('teamlead', '팀원들 의견을 모아볼게요.', 'response')

    meeting = Meeting(
      topic=user_input,
      briefing=briefing,
      agents=self.agents,
      participants=['planner', 'designer', 'developer'],
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
    )

  async def _continue_project(self, user_answer: str) -> dict[str, Any]:
    '''사용자 답변을 받아 중단된 프로젝트를 이어서 진행한다.'''
    pending = self._pending_project
    if not pending:
      return {'state': 'error', 'response': '진행 중인 프로젝트가 없습니다.', 'artifacts': []}

    # 사용자 답변을 컨텍스트에 추가
    meeting_summary = pending['meeting_summary'] + f'\n\n[사용자 확인사항]\n{user_answer}'
    self._pending_project = None

    return await self._execute_project(
      pending['user_input'],
      pending['analysis'],
      meeting_summary,
      pending['reference_context'],
      pending['briefing'],
    )

  async def _execute_project(
    self,
    user_input: str,
    analysis: str,
    meeting_summary: str,
    reference_context: str,
    briefing: str,
  ) -> dict[str, Any]:
    '''프로젝트 전체 실행 — 기획 → 디자인 → 개발 단계별 진행.'''

    PHASES = [
      # 기획 — 3단계로 분리
      {
        'name': '기획-IA설계',
        'description': '사용자 유형별 정보구조(IA) 트리를 설계하세요. GNB, 서브메뉴, 사용자 동선을 포함.',
        'assigned_to': 'planner',
        'group': '기획',
      },
      {
        'name': '기획-와이어프레임',
        'description': '메인화면 와이어프레임을 설계하세요. 섹션 배치, 콘텐츠 영역, CTA 위치를 명시.',
        'assigned_to': 'planner',
        'group': '기획',
      },
      {
        'name': '기획-콘텐츠요구사항',
        'description': '각 섹션별 필요 콘텐츠, 데이터 소스, 갱신 주기를 정의하세요.',
        'assigned_to': 'planner',
        'group': '기획',
      },
      # 디자인 — 3단계
      {
        'name': '디자인-시스템',
        'description': '디자인 시스템을 정의하세요. 컬러 팔레트(hex), 타이포그래피(폰트/사이즈), 간격 체계, 아이콘 스타일.',
        'assigned_to': 'designer',
        'group': '디자인',
      },
      {
        'name': '디자인-레이아웃',
        'description': '메인화면 레이아웃을 설계하세요. 반응형(모바일/태블릿/데스크탑) 브레이크포인트별 구성.',
        'assigned_to': 'designer',
        'group': '디자인',
      },
      {
        'name': '디자인-컴포넌트',
        'description': '주요 UI 컴포넌트 명세를 작성하세요. 헤더, 히어로, 카드, 네비게이션, 푸터의 상세 스펙.',
        'assigned_to': 'designer',
        'group': '디자인',
      },
      # 퍼블리싱 — Stitch 시안 + 디자인 명세 기반 HTML/CSS/JS 통합
      {
        'name': '퍼블리싱',
        'description': '디자인 시안(Stitch HTML)과 디자인 명세를 기반으로 완성된 퍼블리싱 파일을 작성하세요. 단일 index.html 파일에 HTML 구조 + CSS 스타일 + JS 인터랙션(메뉴, 슬라이더 등)을 모두 포함. 시맨틱 마크업, 반응형(모바일/태블릿/데스크탑), 접근성(WCAG 2.1 AA)을 반영.',
        'assigned_to': 'developer',
        'group': '퍼블리싱',
      },
    ]

    all_results: dict[str, str] = {}
    phase_artifacts: list[str] = []
    prev_phase_result = ''

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
            stitch_dir = self.workspace.task_dir / 'stitch'
            has_stitch = stitch_dir.exists() and any(stitch_dir.iterdir()) if stitch_dir.exists() else False
            if not has_stitch:
              await self._generate_stitch_mockup(all_results, user_input)
          continue
      except Exception:
        pass

      self._state = OfficeState.WORKING
      self._active_agent = agent_name
      self._work_started_at = datetime.now(timezone.utc).isoformat()
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

      phase_prompt += (
        f'위 내용을 바탕으로 {phase_name} 작업을 수행하세요.\n'
        f'실무에서 바로 활용할 수 있는 수준으로 상세하게 작성하세요.\n'
        f'마크다운 형식으로 작성하세요.\n'
        f'중요: 반드시 모든 섹션을 끝까지 완성하세요. 절대 중간에 끊지 마세요.'
      )

      content = await agent.handle(phase_prompt)

      # 저장
      filename = f'{phase_name}/{agent_name}-result.md'
      try:
        self.workspace.write_artifact(filename, content)
        phase_artifacts.append(f'{self.workspace.task_id}/{filename}')
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

      # 다른 팀원 리액션 (가벼운 반응으로 실제 오피스 느낌)
      await self._team_reaction(agent_name, phase_name)

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

        # 디자인 그룹 완료 시 → Stitch로 시안 생성
        if current_group == '디자인':
          await self._generate_stitch_mockup(all_results, user_input)

    # 기획자 최종 취합
    await self._emit('planner', '', 'typing')
    await self._run_planner_synthesize(user_input, all_results)

    # 팀장 최종 검수
    self._state = OfficeState.TEAMLEAD_REVIEW
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

    self._state = OfficeState.COMPLETED if passed else OfficeState.ESCALATED

    # 최종 산출물
    final_content = ''
    try:
      final_path = self.workspace.task_dir / 'final' / 'result.md'
      if final_path.exists():
        final_content = final_path.read_text(encoding='utf-8')
    except Exception:
      pass

    phase_artifacts.append(f'{self.workspace.task_id}/final/result.md')

    return {
      'state': self._state.value,
      'response': final_content,
      'artifacts': phase_artifacts if final_content else [],
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
    system = planner._build_system_prompt()

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

    raw = await run_opencode(prompt=prompt, system=system)
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

  async def _team_reaction(self, worker: str, phase_name: str) -> None:
    '''소단계 완료 후 다른 팀원이 가볍게 리액션한다 (오피스 분위기).'''
    import random

    # 리액션 풀 — 에이전트별 성격 반영 (대량 + 상황별)
    REACTIONS: dict[str, list[str]] = {
      'teamlead': [
        '좋습니다 👍', '잘 진행되고 있네요', '확인했습니다', 'ㅎㅎ 수고했어요',
        '깔끔하네요 ✨', '이 속도면 괜찮겠는데요', '방향 잘 잡혔습니다',
        '한 단계 완료! 다음도 부탁합니다', '기대 이상이네요', '멋지게 나왔네요 👏',
        '팀워크 좋습니다', '이러다 칼퇴하는 거 아닙니까 ㅎㅎ', '완벽합니다',
        '프로의 냄새가 나는군요', '착착 진행되니까 보기 좋네요',
      ],
      'planner': [
        '기획 의도 잘 반영됐네요', '이 방향 좋습니다 👏', '다음 단계도 기대됩니다',
        'ㅎㅎ 빠르네요', '📋 체크리스트 확인 완료', '사용자 관점에서 딱이에요',
        '요구사항 대비 잘 맞아떨어지네요', 'IA 구조와 일관성 좋습니다',
        '이 흐름이면 사용자 동선 문제없을 듯', '벤치마킹 결과를 잘 녹였네요',
        '기획서에 이거 반영해둘게요 📝', '전환율 올라갈 듯 ㅎㅎ',
        '과업지시서 요구사항 충족!', '구조가 탄탄하네요', '논리적이라 좋습니다',
      ],
      'designer': [
        '디자인적으로 괜찮아 보여요', '레이아웃 확인했습니다 🎨', '컬러 밸런스 좋네요',
        '간격 체크할게요', '🖌️ 디테일 살펴볼게요', '비주얼 완성도 높네요',
        '여백 처리가 센스 있어요', '타이포 위계가 잘 잡혔네요',
        'ㅎㅎ 이거 실제로 보면 예쁠 듯', '접근성도 고려됐네요 👍',
        'UI 패턴이 익숙해서 사용자 학습 비용 낮겠네요', '그리드 시스템 깔끔!',
        '모바일에서도 잘 나올 것 같아요 📱', '브랜드 톤 잘 살렸습니다',
        'CTA 배치 좋아요, 눈에 잘 띄네요',
      ],
      'developer': [
        '구현 가능합니다 💪', '기술적으로 문제없어요', '이 구조면 개발 편하겠네요',
        'ㅎㅎ 코드 짜기 좋은 명세', '🔥 바로 착수할게요', '컴포넌트 분리하기 좋겠네요',
        '시맨틱 마크업으로 갈게요', '반응형 구현 문제없어 보입니다',
        'Next.js로 하면 더 좋을 듯 ㅎㅎ', 'API 연동도 깔끔하게 되겠네요',
        '성능 최적화도 같이 챙길게요 ⚡', '이거 빌드하면 진짜 멋지겠다',
        '코드 리뷰 기대됩니다', 'SEO도 같이 잡아볼게요', '라이트하우스 100점 가능?',
      ],
      'qa': [
        '검수 준비 중... 👀', '꼼꼼히 볼게요', '기준 대비 확인하겠습니다',
        '품질 체크 ✅', '요구사항 매칭 중...', '이상 없어 보이는데 한번 더 볼게요',
        '빠짐없이 다 들어갔네요', '테스트 시나리오 만들어볼게요',
        'ㅎㅎ 할 게 없으면 좋겠지만... 찾아볼게요', '크로스 브라우징도 체크할게요',
        '접근성 검수도 포함합니다', '엣지 케이스 한번 살펴볼게요',
      ],
    }

    # 잡담/이모지 풀
    MEMES = [
      '☕ 커피 한 잔 하면서 다음 단계 준비~', '🎵 작업 BGM 틀어놓고~',
      '💡 아이디어 떠올랐는데 나중에 공유할게요', '🍕 야근 안 해도 되겠죠...?',
      '🚀 순항 중!', '😎 이 페이스면 일찍 끝나겠는데요', '🎯 목표 달성까지 화이팅',
      '🙌 팀워크 최고', '✌️ 오늘 컨디션 좋네요', '🍜 점심 뭐 먹죠?',
      '🏃 스프린트 완주까지 조금만 더!', '🎪 이 프로젝트 끝나면 회식 각?',
      '🌟 오늘 MVP는 누구?', '📚 참고 자료 공유해둘게요', '🔋 충전 완료!',
      '🎨 이거 포트폴리오에 넣어야겠다 ㅎㅎ', '💻 코딩하기 좋은 날씨네요',
      '🤔 잠깐 생각 좀...', '🎉 한 고비 넘겼다!', '☕ 아아 한 잔 더...',
    ]

    # 중복 방지 — 최근 사용한 리액션 추적
    if not hasattr(self, '_recent_reactions'):
      self._recent_reactions: list[str] = []

    # 작업자 외 팀원 중 1~2명이 리액션
    others = [n for n in ('teamlead', 'planner', 'designer', 'developer', 'qa') if n != worker]
    reactors = random.sample(others, min(random.choice([1, 1, 2]), len(others)))

    for reactor in reactors:
      pool = REACTIONS.get(reactor, ['👍'])
      # 최근 사용하지 않은 것 중에서 선택
      available = [r for r in pool if r not in self._recent_reactions]
      if not available:
        self._recent_reactions = []  # 풀 소진 시 리셋
        available = pool
      msg = random.choice(available)
      self._recent_reactions.append(msg)
      if len(self._recent_reactions) > 30:
        self._recent_reactions = self._recent_reactions[-15:]
      await self._emit(reactor, msg, 'response')

    # 30% 확률로 누군가 잡담/이모지 공유
    if random.random() < 0.3:
      meme_sender = random.choice(others)
      available_memes = [m for m in MEMES if m not in self._recent_reactions]
      if available_memes:
        meme = random.choice(available_memes)
        self._recent_reactions.append(meme)
        await self._emit(meme_sender, meme, 'response')

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
    system = planner._build_system_prompt()
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

    raw = await run_opencode(prompt=prompt, system=system)
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
