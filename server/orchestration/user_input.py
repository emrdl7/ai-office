# 사용자 중간 입력 라우팅 — 작업 진행 중 사용자 메시지 처리.
#
# 원칙: 행동 변경 금지. office.py에서 기계적으로 이관.
from __future__ import annotations

import logging
import re

from orchestration.state import OfficeState
from runners.claude_runner import run_claude_isolated

logger = logging.getLogger(__name__)

# 중단 키워드 + 부정형 가드.
# "중단하지마/취소 아님/don't stop" 같은 부정 표현은 중단 명령으로 오인 금지.
_STOP_NEGATION_RE = re.compile(
  r"(중단|멈추|멈춰|그만|취소|스탑|stop)\s*"
  r"(하지|말|마|안|않|아니|아님|no\b|n[’']?t)",
  re.IGNORECASE,
)
_STOP_DONT_RE = re.compile(r"do\s*n[’']?t\s+stop", re.IGNORECASE)
_STOP_KEYWORDS = ('중단', '멈춰', '멈춰라', '그만', '스탑', 'stop', '취소')


def _is_stop_command(msg: str) -> bool:
  lowered = msg.lower()
  if _STOP_NEGATION_RE.search(lowered) or _STOP_DONT_RE.search(lowered):
    return False
  return any(kw in lowered for kw in _STOP_KEYWORDS)


async def handle_mid_work_input(office, user_input: str) -> None:
  '''작업 진행 중 사용자가 보낸 메시지를 처리한다.

  3가지 경우 판단:
    1. 중단 키워드 → IDLE 전환
    2. @멘션 → 해당 에이전트/팀장이 즉시 응답
    3. 일반 의견 → 팀장 확인 + 작업 컨텍스트 누적
  '''
  from orchestration.meeting import MENTION_MAP

  msg = user_input.strip()

  if _is_stop_command(msg):
    await office._emit('teamlead', '작업을 중단하겠습니다.', 'response')
    office._state = OfficeState.IDLE
    office._active_agent = ''
    office._work_started_at = ''
    office._current_phase = ''
    return

  mentions = re.findall(r'@([가-힣A-Za-z]+(?:님)?)', msg)
  if mentions:
    for raw_mention in mentions:
      target_id = MENTION_MAP.get(raw_mention)
      if not target_id:
        target_id = MENTION_MAP.get(raw_mention.rstrip('님'))
      if not target_id or target_id == 'user':
        continue

      if target_id == 'teamlead':
        try:
          response = await run_claude_isolated(
            f'당신은 팀장 잡스입니다. 팀이 작업 중인데 사용자가 이렇게 말했습니다:\n'
            f'"{msg}"\n짧게 1~2문장으로 응답하세요 (메신저 톤, 마크다운 금지).',
            model='claude-haiku-4-5-20251001',
            timeout=15.0,
          )
          response_text = response.strip()
        except Exception:
          logger.debug("팀장 멘션 응답 생성 실패", exc_info=True)
          response_text = '네, 확인했습니다. 반영하겠습니다.'
        await office._emit('teamlead', response_text, 'response')
        await _record_commitment(office, 'teamlead', response_text, msg)
      else:
        agent = office.agents.get(target_id)
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
            response_text = response.strip()
          except Exception:
            logger.debug("에이전트 멘션 응답 생성 실패: %s", target_id, exc_info=True)
            response_text = '네, 확인했습니다. 반영하겠습니다.'
          await office._emit(target_id, response_text, 'response')
          await _record_commitment(office, target_id, response_text, msg)

    office._user_mid_feedback.append(msg)
    return

  office._user_mid_feedback.append(msg)
  default_ack = '말씀 확인했습니다. 작업에 반영하겠습니다.'
  await office._emit('teamlead', default_ack, 'response')
  await _record_commitment(office, 'teamlead', default_ack, msg)


async def _record_commitment(office, committer_id: str, response_text: str, user_msg: str) -> None:
  # 팀장/에이전트 응답에 다짐 마커("반영하겠" 등)가 있으면 다짐 게시판 등록.
  # _file_commitment_suggestion 내부에서 마커 매칭·중복 가드 처리.
  try:
    await office._file_commitment_suggestion(
      committer_id=committer_id,
      message=response_text,
      source_speaker='user',
      source_message=user_msg,
    )
  except Exception:
    logger.debug("사용자 개입 응답 다짐 등록 실패: %s", committer_id, exc_info=True)
