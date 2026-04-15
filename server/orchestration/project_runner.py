# 프로젝트 실행 파이프라인 — office.py에서 분리 (P1 로드맵 4단계)
#
# 원칙: 행동 변경 금지. self.* → office.* 기계적 치환만.
# 12개 메서드: _handle_quick_task, _handle_project, _continue_project,
# _plan_project_phases, _default_phases, _execute_project, _auto_export,
# _cross_review, _quick_task_second_opinion, _run_qa_check,
# _run_planner_synthesize, _teamlead_final_review.
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.team import (
  TEAM, BY_ID, AGENT_IDS, WORKER_IDS,
  display_name, display_with_role, profile_names,
)
from orchestration.intent import IntentType, classify_intent, classify_project_type
from orchestration.phase_registry import ProjectType, get_phases, get_meeting_participants
from orchestration.agent import Agent
from orchestration.meeting import Meeting
from orchestration.task_graph import TaskGraph, TaskNode, TaskStatus
from memory.team_memory import SharedLesson, TeamDynamic, ProjectSummary
from log_bus.event_bus import LogEvent
from runners.claude_runner import run_claude_isolated
from runners.gemini_runner import run_gemini
from bus.payloads import TaskRequestPayload, TaskResultPayload
from workspace.manager import WorkspaceManager
from db.task_store import get_task
from harness.file_reader import resolve_references
from harness.code_runner import run_code
from harness.rejection_analyzer import record_rejection, get_past_rejections
from harness.stitch_client import designer_generate_with_context
from improvement.engine import ImprovementEngine
from improvement.metrics import MetricsCollector, ProjectMetrics, PhaseMetrics
from improvement.qa_adapter import QAAdapter

logger = logging.getLogger(__name__)


async def _handle_quick_task(
  office,
  user_input: str,
  agent_name: str,
  analysis: str,
  reference_context: str,
) -> dict[str, Any]:
  '''단순 작업 — 팀원 한 명이 처리'''
  agent = office.agents.get(agent_name)
  if not agent:
    return {'state': 'error', 'response': f'{agent_name} 에이전트를 찾을 수 없습니다.', 'artifacts': []}

  office._state = OfficeState.WORKING
  office._active_agent = agent_name

  # 업무 수신 확인    await office._emit('teamlead', f'알겠습니다. {display_name(agent_name)}에게 맡기겠습니다.', 'response')

  # 담당자 업무 수령 확인
  await office._task_acknowledgment(agent_name, analysis or user_input)

  prompt = analysis or user_input
  # 사용자 중간 피드백이 있으면 프롬프트에 주입
  if office._user_mid_feedback:
    feedback_text = '\n'.join(f'- {fb}' for fb in office._user_mid_feedback)
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
  if office._context_summary:
    ctx_parts.append(f'[이전 대화 요약]\n{office._context_summary}')
  if reference_context:
    ctx_parts.append(reference_context)
  result = await agent.handle(prompt, context='\n\n'.join(ctx_parts))

  # 보완 전문 기여 — 관련 역할 에이전트가 전문 내용 제공 후 담당자가 결과물 보강
  result = await office._quick_task_second_opinion(agent_name, prompt, result, agent, ctx_parts)

  # QA 검수 (최대 3회: 초기 + 2회 보완)
  qa_agent = office.agents.get('qa')
  accumulated_feedback: list[str] = []
  if qa_agent and agent_name != 'qa':
    for attempt in range(3):
      office._state = OfficeState.QA_REVIEW
      office._active_agent = 'qa'
      await office._emit('qa', '산출물 검수를 시작합니다.', 'response')

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
        await office._emit('qa', msg, 'response')
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
        await office._emit('qa', f'검수 불합격 [{severity}]: {failure_reason[:200]}', 'response')
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
          office._state = OfficeState.WORKING
          office._active_agent = agent_name
          await office._emit('teamlead', f'{display_name(agent_name)}, 보완 부탁합니다.', 'response')
          all_feedback = '\n'.join(f'- {fb}' for fb in accumulated_feedback)
          revision_prompt = f'{prompt}\n\n[QA 피드백 — 반드시 반영할 것]\n{all_feedback}\n\n[이전 결과물]\n{result}'
          result = await agent.handle(revision_prompt, context='\n\n'.join(ctx_parts))

  # 산출물 저장
  saved_paths = []
  try:
    file_path = 'quick-task/result.md'
    office.workspace.write_artifact(file_path, result)
    saved_paths.append(f'{office.workspace.task_id}/{file_path}')
  except Exception:
    logger.warning("퀵태스크 산출물 저장 실패", exc_info=True)

  # 팀장 최종 검수 (최대 1회 보완)
  office._state = OfficeState.TEAMLEAD_REVIEW
  office._active_agent = 'teamlead'
  await office._emit('teamlead', '최종 검수하겠습니다.', 'response')

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
    await office._emit('teamlead', f'보완이 필요합니다: {feedback[:200]}', 'response')

    office._state = OfficeState.WORKING
    office._active_agent = agent_name
    revision_prompt = f'{prompt}\n\n[팀장 보완 지시 — 반드시 반영할 것]\n{feedback}\n\n[이전 결과물]\n{result}'
    result = await agent.handle(revision_prompt, context='\n\n'.join(ctx_parts))

    # 보완된 결과물 재저장
    try:
      office.workspace.write_artifact(file_path, result)
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
  teamlead_agent = office.agents.get('teamlead')
  try:
    report = await teamlead_agent.handle(report_prompt) if teamlead_agent else ''
  except Exception:
    logger.warning("팀장 최종 보고 생성 실패", exc_info=True)
    report = ''

  if report:
    await office.event_bus.publish(LogEvent(
      agent_id='teamlead',
      event_type='response',
      message=report,
      data={'artifacts': saved_paths},
    ))
  else:
    # 보고 생성 실패 시 fallback
    summary = '\n'.join(result.strip().split('\n')[:8])
    await office.event_bus.publish(LogEvent(
      agent_id='teamlead',
      event_type='response',
      message=f'{display_name(agent_name)} 작업 완료했습니다.\n\n{summary}',
      data={'artifacts': saved_paths},
    ))

  # 프로젝트 세션 종료
  if office._active_project_id:
    from db.task_store import archive_project
    archive_project(office._active_project_id)
    await office._emit('system', '📂 프로젝트 완료', 'project_close')
    office._active_project_id = None
    office._active_project_title = ''
    office._current_project_type = ''

  office._state = OfficeState.COMPLETED
  office._active_agent = ''
  office._work_started_at = ''
  office._current_phase = ''
  office._user_mid_feedback = []  # 피드백 초기화
  return {
    'state': office._state.value,
    'response': result,
    'artifacts': saved_paths,
  }



async def _handle_project(
  office,
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
  if office._context_summary:
    briefing = f'{analysis}\n\n[이전 논의 요약]\n{office._context_summary}'

  # 프로젝트 유형 분류 — 대화 맥락 포함
  type_context = office._context_summary or analysis
  project_type = await classify_project_type(user_input, context=type_context[:500])
  phases = get_phases(project_type)
  participants = get_meeting_participants(project_type)

  # 업무 수신 확인
  await office._emit('teamlead', f'알겠습니다. 확인하고 팀원들과 논의해보겠습니다. (프로젝트 유형: {project_type.value})', 'response')

  # 1. 회의 소집 — 방향 잡기
  office._state = OfficeState.MEETING
  await office._emit('teamlead', '팀원들 의견을 모아볼게요.', 'response')

  meeting = Meeting(
    topic=user_input,
    briefing=briefing,
    agents=office.agents,
    participants=participants,
    event_bus=office.event_bus,
  )
  await meeting.run()
  meeting_summary = meeting.get_summary()

  # 2. 팀장이 회의 결과를 바탕으로 프로젝트 단계를 동적 설계
  dynamic_phases = await office._plan_project_phases(user_input, analysis, meeting_summary)
  if dynamic_phases:
    phases = dynamic_phases
    await office._emit('teamlead', f'프로젝트를 {len(phases)}단계로 진행하겠습니다.', 'response')
  # dynamic_phases가 None이면 기존 get_phases() 결과를 그대로 사용

  # 3. 팀장이 회의 결과에서 확인 필요한 사항을 사용자에게 질문
  questions = await office._extract_user_questions(user_input, meeting_summary)
  if questions:
    # @마스터가 안 붙어 있으면 앞에 추가
    if not questions.startswith('@마스터'):
      questions = f'@마스터 {questions}'
    await office.event_bus.publish(LogEvent(
      agent_id='teamlead',
      event_type='response',
      message=questions,
      data={'needs_input': True},
    ))
    # 질문을 던지고 현재 상태 저장 — 사용자 응답 후 이어서 진행
    office._pending_project = {
      'user_input': user_input,
      'analysis': analysis,
      'meeting_summary': meeting_summary,
      'reference_context': reference_context,
      'briefing': briefing,
      'project_type': project_type.value,
      'phases': phases,
    }
    # DB에도 컨텍스트 저장 (서버 재시작 시 복구용)
    office._pending_task_id = getattr(office, '_current_task_id', '')
    if office._pending_task_id:
      from db.task_store import update_task_state
      update_task_state(office._pending_task_id, 'waiting_input', context=office._pending_project)
    office._state = OfficeState.IDLE
    return {
      'state': 'waiting_input',
      'response': questions,
      'artifacts': [],
    }

  # 질문 없으면 바로 전체 진행
  return await office._execute_project(
    user_input, analysis, meeting_summary, reference_context, briefing,
    phases=phases,
  )



async def _continue_project(office, user_answer: str) -> dict[str, Any]:
  '''사용자 답변을 받아 중단된 프로젝트를 이어서 진행한다.'''
  pending = office._pending_project
  if not pending:
    return {'state': 'error', 'response': '진행 중인 프로젝트가 없습니다.', 'artifacts': []}

  # 사용자 답변을 컨텍스트에 추가
  meeting_summary = pending['meeting_summary'] + f'\n\n[사용자 확인사항]\n{user_answer}'

  # 저장된 phases 복원
  phases = pending.get('phases')

  office._pending_project = None

  return await office._execute_project(
    pending['user_input'],
    pending['analysis'],
    meeting_summary,
    pending['reference_context'],
    pending['briefing'],
    phases=phases,
  )



async def _plan_project_phases(
  office,
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



def _default_phases(office, user_input: str) -> tuple[list[dict], str]:
  '''기본 단계 반환 — phases 미전달 시 하위호환용.'''
  project_type = office.improvement_engine.qa_adapter.classify_project_type(user_input)
  phases = office.improvement_engine.workflow_optimizer.get_phase_dicts(project_type, user_input)
  return phases, project_type



async def _execute_project(
  office,
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
    PHASES, project_type = office._default_phases(user_input)
  office._current_project_type = project_type

  # 팀원 피드백 초기화
  office._phase_feedback = []

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
    agent = office.agents[agent_name]

    # 이미 완료된 단계는 스킵 (서버 재시작 후 중복 실행 방지)
    # 현재 workspace + 전체 workspace에서 가장 최신 산출물 검색
    existing_file = f'{phase_name}/{agent_name}-result.md'
    existing_content = ''
    found_task_id = ''
    try:
      # 1) 현재 workspace에서 먼저 찾기
      existing_path = office.workspace.task_dir / existing_file
      if existing_path.exists():
        existing_content = existing_path.read_text(encoding='utf-8')
        found_task_id = office.workspace.task_id

      # 2) 없으면 전체 workspace에서 가장 최신 찾기
      if not existing_content or len(existing_content) < 100:
        workspace_root = office.workspace.task_dir.parent
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
        await office._emit('teamlead', f'{phase_name} 단계는 이미 완료되어 있습니다. 다음 단계로 넘어갑니다.', 'response')

        # 스킵해도 그룹 마지막이면 Stitch 시안 생성 체크
        current_group = phase.get('group', phase_name)
        remaining_in_group = [p for p in PHASES[PHASES.index(phase)+1:] if p.get('group') == current_group]
        _has_design_group = any(p.get('group') == '디자인' for p in PHASES)
        if not remaining_in_group and _has_design_group and current_group == '디자인':
          # Stitch 시안이 아직 없으면 생성
          # 전체 workspace에서 Stitch 시안 검색
          has_stitch = False
          workspace_root = office.workspace.task_dir.parent
          for ws_dir in workspace_root.iterdir():
            sd = ws_dir / 'stitch'
            if sd.exists() and any(sd.iterdir()):
              has_stitch = True
              break
          if not has_stitch and office._current_project_type in ('web_development', 'website'):
            await office._generate_stitch_mockup(all_results, user_input)
          elif has_stitch:
            await office._emit('designer', '이전에 생성된 Stitch 시안이 있습니다. 그대로 사용합니다. 🎨', 'response')
        continue
    except Exception:
      logger.debug("그룹 전환 처리 실패: %s", phase_name, exc_info=True)

    office._state = OfficeState.WORKING
    office._active_agent = agent_name
    office._work_started_at = datetime.now(timezone.utc).isoformat()
    office._current_phase = phase_name
    _phase_started_at = datetime.now(timezone.utc).isoformat()
    _phase_revision_count = 0
    await office._emit('teamlead', f'{phase_name} 단계를 시작합니다.', 'response')
    await office._emit(agent_name, '', 'typing')

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
        guide = await office._create_handoff_guide(g, group_results, phase_name)
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

    # 팀원 피드백 주입 — high priority 우선
    if office._phase_feedback:
      recent_fb = office._phase_feedback[-5:]
      recent_fb = sorted(recent_fb, key=lambda f: 0 if f.get('priority') == 'high' else 1)
      feedback_lines = [f'- {fb["from"]}: {fb["content"][:100]}' for fb in recent_fb]
      phase_prompt += f'\n[팀원 피드백 — 가능한 반영할 것]\n' + '\n'.join(feedback_lines) + '\n\n'

    # 그룹 전환 시 인수인계 코멘트
    if _prev_group and current_group != _prev_group and _prev_agent != agent_name:
      await office._handoff_comment(_prev_agent, agent_name, phase_name)
    _prev_group = current_group
    _prev_agent = agent_name

    # 담당자 포부 한마디 + 착수 메시지
    await office._phase_intro(agent_name, phase_name)

    # 업무 수령 확인
    await office._task_acknowledgment(agent_name, phase_name)

    # 사용자 중간 피드백이 있으면 프롬프트에 주입
    if office._user_mid_feedback:
      feedback_text = '\n'.join(f'- {fb}' for fb in office._user_mid_feedback)
      phase_prompt += f'\n\n[사용자 중간 피드백 — 반드시 반영할 것]\n{feedback_text}\n'

    content = await agent.handle(phase_prompt)

    # 저장
    filename = f'{phase_name}/{agent_name}-result.md'
    try:
      office.workspace.write_artifact(filename, content)
      phase_artifacts.append(f'{office.workspace.task_id}/{filename}')
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
          html_file_path = office.workspace.write_artifact(html_filename, html_code)
          phase_artifacts.append(f'{office.workspace.task_id}/{html_filename}')
          html_url = f'/api/artifacts/{office.workspace.task_id}/{html_filename}'
          await office.event_bus.publish(LogEvent(
            agent_id=agent_name,
            event_type='response',
            message=f'{phase_name} HTML 산출물 생성 완료 👇\n{html_url}',
            data={'artifacts': [f'{office.workspace.task_id}/{html_filename}']},
          ))
          # PDF 변환
          if '+pdf' in output_format:
            try:
              from harness.pdf_converter import html_to_pdf
              pdf_path = html_to_pdf(html_file_path)
              pdf_rel = f'{phase_name}/result.pdf'
              phase_artifacts.append(f'{office.workspace.task_id}/{pdf_rel}')
              await office.event_bus.publish(LogEvent(
                agent_id=agent_name,
                event_type='response',
                message=f'{phase_name} PDF 생성 완료 📄',
                data={'artifacts': [f'{office.workspace.task_id}/{pdf_rel}']},
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
          office.workspace.write_artifact(code_filename, code)
          phase_artifacts.append(f'{office.workspace.task_id}/{code_filename}')
        except Exception:
          logger.debug("코드 블록 저장 실패: %s", code_filename, exc_info=True)

    # HTML 출력 그룹 완료 시 멀티페이지 사이트 빌더 실행
    _is_html_output = phase.get('output_format', '') in ('html', 'html+pdf')
    if (current_group == '퍼블리싱' or _is_html_output) and office._current_project_type in ('web_development', 'website'):
      try:
        ia_content = next((v for k, v in all_results.items() if 'IA' in k), '')
        design_content = '\n'.join(v for k, v in all_results.items() if '디자인' in k)
        if ia_content:
          from harness.site_builder import build_multipage_site
          site_result = await build_multipage_site(
            ia_content=ia_content,
            design_specs=design_content,
            stitch_html=content if '<html' in content.lower() else None,
            workspace_dir=office.workspace.task_dir,
            project_brief=user_input[:500],
          )
          if site_result.get('pages'):
            for page_path in site_result['pages']:
              phase_artifacts.append(f'{office.workspace.task_id}/{page_path}')
            await office._emit('developer', f'멀티페이지 사이트 생성 완료 ({len(site_result["pages"])}페이지) 🌐', 'response')
      except Exception:
        logger.warning("멀티페이지 사이트 빌드 실패", exc_info=True)

    all_results[phase_name] = content
    prev_phase_result = content

    # 에이전트 간 @멘션 자동 라우팅 — 산출물에서 다른 에이전트에게 질문 감지
    try:
      await office._route_agent_mentions(agent_name, content[:3000])
    except Exception:
      logger.debug("에이전트 간 멘션 라우팅 실패: %s", phase_name, exc_info=True)

    # 단계 결과를 채팅에 요약 + 산출물 카드로 보고
    summary_lines = content.strip().split('\n')[:5]
    summary = '\n'.join(summary_lines)
    artifact_path = f'{office.workspace.task_id}/{filename}'
    await office.event_bus.publish(LogEvent(
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
      consultation_feedback = await office._consult_peers(agent_name, group_content, phase, all_results)
      if consultation_feedback:
        # 자문 결과를 담당자에게 전달하여 보완 기회 제공
        await office._emit('teamlead', '자문 결과를 반영합니다.', 'response')
        office._user_mid_feedback.append(f'[팀원 자문 결과]\n{consultation_feedback}')

      # 2) 피어 리뷰 (실질적 피드백)
      peer_reviews = await office._peer_review(agent_name, phase_name, group_content, user_input)

      # 피어 리뷰에서 보완된 결과가 있으면 반영
      for review in peer_reviews:
        if review.get('revised') and review.get('content'):
          content = review['content']
          all_results[phase_name] = content
          try:
            office.workspace.write_artifact(filename, content)
          except Exception:
            logger.warning("피어 리뷰 보완 결과 저장 실패: %s", filename, exc_info=True)
          break
    else:
      # ── 소단계 중간: 경량 리액션 유지 ──
      await office._work_commentary(agent_name, phase_name, content)
      content_summary = '\n'.join(content.strip().split('\n')[:5])
      await office._team_reaction(agent_name, phase_name, content_summary=content_summary)

    # 사용자 중간 지시 확인 — 최근 채팅에서 사용자 메시지 체크
    user_directive = await office._check_user_directive()
    if user_directive:
      if user_directive.get('action') == 'stop':
        await office._emit('teamlead', '작업을 중단합니다. 여기까지의 산출물은 저장되어 있습니다.', 'response')
        office._state = OfficeState.COMPLETED
        office._active_agent = ''
        office._work_started_at = ''
        office._current_phase = ''
        return {
          'state': office._state.value,
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
            await office._emit('teamlead', '네, 확인했습니다. 반영하겠습니다.', 'response')
          else:
            mention_agent = office.agents.get(target_id)
            if mention_agent:
              try:
                resp = await run_claude_isolated(
                  f'{mention_agent._build_system_prompt()}\n\n---\n\n'
                  f'작업 중인데 사용자가 이렇게 말했습니다:\n"{feedback_msg}"\n'
                  f'짧게 1~2문장으로 응답하세요 (메신저 톤, 마크다운 금지).',
                  model='claude-haiku-4-5-20251001', timeout=15.0,
                )
                await office._emit(target_id, resp.strip(), 'response')
              except Exception:
                logger.debug("멘션 대상 응답 생성 실패: %s", target_id, exc_info=True)
                await office._emit(target_id, '네, 확인했습니다.', 'response')
        office._user_mid_feedback.append(feedback_msg)
        await office._emit('teamlead', f'말씀하신 내용 반영하여 다음 단계 진행하겠습니다.', 'response')
      elif user_directive.get('message'):
        # 사용자 지시를 다음 소단계 프롬프트에 반영
        office._user_mid_feedback.append(user_directive['message'])
        meeting_summary += f'\n\n[사용자 중간 지시]\n{user_directive["message"]}'
        await office._emit('teamlead', f'말씀하신 내용 반영하여 다음 단계 진행하겠습니다.', 'response')

    # QA 검수 — 그룹의 마지막 소단계에서만 실행 (current_group, _is_group_last는 위에서 계산됨)
    if _is_group_last:
      # 그룹 마지막 → QA 검수
      office._state = OfficeState.QA_REVIEW
      office._active_agent = 'qa'
      await office._emit('qa', '', 'typing')
      qa_agent = office.agents['qa']
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
      qa_passed = await office._run_qa_check(qa_agent, node, group_content)
      if not qa_passed:
        await office._emit('qa', f'{current_group} 검수 불합격: {node.failure_reason[:200]}', 'response')

        _phase_revision_count += 1
        # 보완 1회 — 불합격 사유를 담당 에이전트에게 전달하여 수정
        await office._emit('teamlead', f'{current_group} 보완 요청합니다.', 'response')
        office._state = OfficeState.REVISION
        office._active_agent = agent_name
        await office._emit(agent_name, '', 'typing')

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
          office.workspace.write_artifact(filename, revised)
        except Exception:
          logger.warning("QA 보완 결과 저장 실패: %s", filename, exc_info=True)
        all_results[phase_name] = revised
        prev_phase_result = revised

        await office.event_bus.publish(LogEvent(
          agent_id=agent_name,
          event_type='response',
          message=f'{current_group} 보완 완료했습니다.',
          data={'artifacts': [f'{office.workspace.task_id}/{filename}']},
        ))
        await office._team_reaction(agent_name, f'{current_group}-보완')
      else:
        await office._emit('qa', f'{current_group} 검수 통과 ✅', 'response')

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
      await office._cross_review(current_group, all_results)

      # 디자인 그룹 완료 시 → 웹 개발 프로젝트만 Stitch 시안 생성
      _has_design_phases = any(p.get('group') == '디자인' for p in PHASES)
      if _has_design_phases and current_group == '디자인' and office._current_project_type in ('web_development', 'website'):
        await office._generate_stitch_mockup(all_results, user_input)

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
        await office.event_bus.publish(LogEvent(
          agent_id='teamlead',
          event_type='response',
          message=confirm_msg,
          data={'needs_input': True},
        ))
        # 상태 저장 — 재개 시 _execute_project 재호출, 완료 단계는 자동 스킵
        office._pending_project = {
          'user_input': user_input,
          'analysis': analysis,
          'meeting_summary': meeting_summary,
          'reference_context': reference_context,
          'briefing': briefing,
          'project_type': office._current_project_type,
          'phases': PHASES,
        }
        office._pending_task_id = getattr(office, '_current_task_id', '')
        if office._pending_task_id:
          from db.task_store import update_task_state
          update_task_state(office._pending_task_id, 'waiting_input', context=office._pending_project)
        office._state = OfficeState.IDLE
        office._active_agent = ''
        office._work_started_at = ''
        office._current_phase = ''
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
    await office._emit('teamlead', '최종 보고서를 작성하고 있습니다.', 'response')
    office._active_agent = 'teamlead'

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
    await office.event_bus.publish(LogEvent(
      agent_id='teamlead',
      event_type='response',
      message='\n'.join(report_lines),
      data={'artifacts': final_artifacts},
    ))
  else:
    # 문서/분석 프로젝트 → 기획자가 최종 보고서 취합
    await office._emit('teamlead', '기획자에게 최종 보고서 작성을 요청합니다.', 'response')
    office._active_agent = 'planner'
    await office._emit('planner', '', 'typing')
    await office._run_planner_synthesize(user_input, all_results)

    # 팀장 최종 검수
    office._state = OfficeState.TEAMLEAD_REVIEW
    office._active_agent = 'teamlead'
    passed = await office._teamlead_final_review(user_input, None)

    if not passed:
      for _ in range(office.MAX_REVISION_ROUNDS):
        office._revision_count += 1
        await office._run_planner_synthesize(
          user_input, all_results, revision_feedback=office._last_review_feedback,
        )
        passed = await office._teamlead_final_review(user_input, None)
        if passed:
          break

  # 팀 회고 — 프로젝트 완료 후 각 에이전트가 배운 점 공유
  try:
    await office._team_retrospective(
      project_title=office._active_project_title or '프로젝트',
      project_type=project_type,
      all_results=all_results,
      user_input=user_input,
      duration=_total_dur if '_total_dur' in dir() else 0.0,
    )
  except Exception:
    logger.debug("팀 회고 실행 실패", exc_info=True)

  # 프로젝트 세션 종료
  if office._active_project_id:
    from db.task_store import archive_project
    archive_project(office._active_project_id)
    await office._emit('system', '📂 프로젝트 완료', 'project_close')
    office._active_project_id = None
    office._active_project_title = ''
    office._current_project_type = ''

  office._state = OfficeState.COMPLETED
  office._active_agent = ''
  office._work_started_at = ''
  office._current_phase = ''
  office._pending_project = None
  office._interrupted_instruction = None
  office._user_mid_feedback = []  # 피드백 초기화

  # 현재 task를 completed로 마킹 (서버 재시작 시 "이어하겠습니다" 방지)
  from db.task_store import update_task_state as _update_task
  task_id = getattr(office, '_current_task_id', '') or ''
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
    final_review_rounds=office._revision_count,
  )
  try:
    await office.improvement_engine.on_project_complete(project_metrics)
  except Exception:
    logger.warning("자가개선 메트릭 수집 실패", exc_info=True)  # 자가개선 실패가 프로젝트 완료를 막지 않음

  # ── 자동 내보내기 — 산출물 PDF/DOCX/ZIP 생성 ──
  try:
    await office._auto_export(phase_artifacts)
  except Exception:
    logger.warning("자동 내보내기 실패", exc_info=True)

  return {
    'state': office._state.value,
    'response': '프로젝트 완료',
    'artifacts': phase_artifacts,
  }



async def _auto_export(office, phase_artifacts: list[str]) -> None:
  '''프로젝트 완료 후 주요 산출물을 PDF/ZIP으로 자동 내보내기.'''
  from harness.export_engine import md_to_pdf, folder_to_zip

  task_dir = office.workspace.task_dir
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
    await office._emit('system', f'📦 산출물 내보내기 완료: {files_text}', 'response')

# 그룹별 크로스리뷰 매핑: 그룹 → (리뷰어, 관점)
_CROSS_REVIEW_MAP: dict[str, tuple[str, str]] = {
  '기획': ('designer', 'UX/사용자 경험 관점에서 기획 산출물을 검토'),
  '디자인': ('developer', '기술 구현 가능성 관점에서 디자인 산출물을 검토'),
  '퍼블리싱': ('designer', '디자인 명세 준수 여부를 검토'),
}



async def _cross_review(office, group_name: str, all_results: dict[str, str]) -> None:
  '''그룹 완료 후 다른 역할의 에이전트가 간단히 크로스리뷰한다.'''
  review_config = office._CROSS_REVIEW_MAP.get(group_name)
  if not review_config:
    return

  reviewer_name, perspective = review_config
  reviewer = office.agents.get(reviewer_name)
  if not reviewer:
    return

  # 해당 그룹의 산출물 수집
  group_content = '\n\n'.join(
    f'[{k}]\n{v[:2000]}' for k, v in all_results.items() if group_name in k or k.startswith(group_name)
  )
  if not group_content:
    return

  try:
    await office._emit(reviewer_name, '', 'typing')
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
      await office._emit(reviewer_name, f'[{group_name} 크로스리뷰] {feedback[:300]}', 'response')
    else:
      await office._emit(reviewer_name, f'{group_name} 산출물 확인했습니다 ✅', 'response')
  except Exception:
    logger.debug("크로스리뷰 실패: %s", group_name, exc_info=True)



async def _quick_task_second_opinion(
  office,
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
  config = office._resolve_reviewer(worker, prompt)
  if not config:
    return result

  reviewer_name, perspective = config
  reviewer = office.agents.get(reviewer_name)
  if not reviewer:
    return result

  # ── Step 1: 리뷰어가 전문 내용 기여 ──
  try:
    await office._emit(reviewer_name, '', 'typing')
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
    await office._emit(reviewer_name, '내용 충실하네요 👍', 'response')
    return result

  # 채팅에 기여 사실 알림
  await office._emit(
    reviewer_name,
    f'{perspective} 관점에서 보완 내용 추가했습니다.',
    'response',
  )

  # ── Step 2: 담당자가 기여 내용을 반영해 결과물 보강 ──
  if not worker_agent:
    return result

  try:
    office._active_agent = worker
    await office._emit(worker, '', 'typing')
    revise_prompt = (
      f'[원본 요청]\n{prompt}\n\n'
      f'[현재 산출물]\n{result}\n\n'
      f'[{display_name(reviewer_name)}의 보완 내용]\n{contribution}\n\n'
      f'위 보완 내용을 산출물에 자연스럽게 통합하여 완성본을 작성하세요.\n'
      f'원본 구조를 유지하면서 보완 내용을 적절한 위치에 녹여 넣으세요.'
    )
    ctx = '\n\n'.join(ctx_parts) if ctx_parts else ''
    updated = await worker_agent.handle(revise_prompt, context=ctx)
    await office._emit(
      worker,
      f'{display_name(reviewer_name)} 의견 반영해서 보강했습니다.',
      'response',
    )
    return updated
  except Exception:
    logger.warning("보완 내용 반영 실패: %s", worker, exc_info=True)
    return result



async def _run_qa_check(office, qa_agent: Agent, node: TaskNode, content: str) -> bool:
  '''QA 에이전트가 산출물을 검수한다 (내부 처리 — 채팅에 안 보임).'''
  ac_section = ''
  if getattr(node, 'acceptance_criteria', None):
    ac_lines = '\n'.join(f'- {c}' for c in node.acceptance_criteria)
    ac_section = (
      f'\n[완료 기준 (Acceptance Criteria) — 각 항목을 하나씩 검증]\n{ac_lines}\n'
      f'AC 항목 중 하나라도 미달이면 status=fail.\n'
    )
  qa_prompt = (
    f'[원본 요구사항]\n{node.requirements}\n'
    f'{ac_section}\n'
    f'[작업 결과물]\n{content}\n\n'
    f'위 요구사항과 완료 기준 대비 결과물을 검수하세요.'
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
  office,
  user_input: str,
  worker_results: dict[str, str],
  revision_feedback: str = '',
) -> None:
  '''기획자가 작업 결과를 취합하여 최종 산출물을 작성한다.'''
  planner = office.agents['planner']
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
    office.workspace.write_artifact('final/result.md', content)
  except Exception:
    logger.warning("최종 산출물 저장 실패", exc_info=True)



async def _teamlead_final_review(office, user_input: str, task_graph: TaskGraph) -> bool:
  '''팀장(Claude)이 최종 산출물을 검수한다.'''
  final_path = office.workspace.task_dir / 'final' / 'result.md'
  if not final_path.exists():
    office._last_review_feedback = '최종 산출물 파일이 없습니다.'
    return False

  final_content = final_path.read_text(encoding='utf-8')
  if len(final_content) < 500:
    office._last_review_feedback = f'산출물이 너무 짧습니다 ({len(final_content)}자). 최소 3000자 이상 필요.'
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
    office._last_review_feedback = ''
    # 보완 사유 분석 및 기록
    if office._revision_count > 0:
      record_rejection(office._last_review_feedback, 'final_review', str(office._memory_root))
    return True

  # 불합격
  office._last_review_feedback = text.replace('[FAIL]', '').strip()[:500]
  record_rejection(office._last_review_feedback, 'final_review', str(office._memory_root))
  return False

# ──────────────────────────────────────────────────────────────
# 에이전트 간 자율 대화 라우팅 (Phase 1)
# ──────────────────────────────────────────────────────────────

