# 팀원 간 상호작용 — office.py에서 분리 (P1 로드맵 3단계)
#
# 원칙: 행동 변경 금지. self.* → office.* 기계적 치환만.
# 10개 메서드: _team_chat, _team_reaction, _consult_peers, _peer_review,
# _handoff_comment, _task_acknowledgment, _contextual_reaction, _resolve_reviewer,
# _work_commentary, _phase_intro. Office는 forwarder 유지.
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone

from config.team import (
  AGENT_IDS, WORKER_IDS, BY_ID,
  display_name, display_with_role,
)
from log_bus.event_bus import LogEvent
from memory.team_memory import SharedLesson, TeamDynamic
from runners.claude_runner import run_claude_isolated
from runners.gemini_runner import run_gemini

logger = logging.getLogger(__name__)


async def _team_chat(office, user_input: str, chat_subtype: str = 'casual', teamlead_response: str = '') -> None:
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
        await office._emit(responder, text, 'response')
    except Exception:
      logger.debug("인사 리액션 생성 실패", exc_info=True)
    return

  # question: 관련 에이전트 1명만 답변 (나머지 PASS)
  if chat_subtype == 'question':
    for name in ('planner', 'designer', 'developer', 'qa'):
      agent = office.agents.get(name)
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
          await office._emit(name, content, 'response')
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
  if office._context_summary:
    base_thread.append(f'[이전 대화 맥락]\n{office._context_summary}')
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
    agent = office.agents.get(name)
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
      await office._emit(name, '', 'typing')
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
          await office._emit(name, chat_part, 'response')
          thread_after_r1.append(f'[{name}] {chat_part}')
          responded.append(name)
        continue
    await office._emit(name, content, 'response')
    thread_after_r1.append(f'[{name}] {content}')
    responded.append(name)

  # 업무 감지 → 팀장 전환
  if task_detected:
    await office._emit(
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
    agent = office.agents[fallback_name]
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
      await office._emit(fallback_name, content, 'response')
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
      await office._emit(name, content, 'response')



async def _team_reaction(office, worker: str, phase_name: str, content_summary: str = '') -> None:
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
      agent = office.agents.get(reactor_name)
      system = agent._build_system_prompt() if agent else ''
      prompt = (
        f'{display_name(worker)}이(가) [{phase_name}] 작업을 완료했습니다.\n'
        f'{summary_section}'
        f'당신({display_name(reactor_name)})의 성격으로 동료로서 1문장 반응하세요.\n'
        f'40~120자, 구체 근거 1개(수치·섹션명·기법명·파일명) 포함, 이모지 1개, 메신저 톤. 마크다운 금지.\n'
        f'개선 필요점이 있으면 마지막에 `[건의] 한줄 요약` 라벨을 붙이세요.'
      )
      full = f'{system}\n\n---\n\n{prompt}' if system else prompt
      response = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=20.0)
      return reactor_name, response.strip().split('\n')[0][:200]
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
    await office._emit(reactor_name, text, 'response')
    if not first_reaction_text:
      first_reaction_text = text
      first_reactor = reactor_name
    # [건의] 라벨 감지 → pending 등록
    has_suggestion_label = '[건의]' in text
    # 업무 관련 피드백 수집
    if has_suggestion_label or any(kw in text for kw in ('체크', '확인', '검토', '반영', '수정', '추가', '고려', '필요', '개선')):
      office._phase_feedback.append({
        'from': display_name(reactor_name),
        'phase': phase_name,
        'content': text,
        'priority': 'high' if has_suggestion_label else 'normal',
      })
    if has_suggestion_label:
      try:
        await office._file_reaction_suggestion(reactor_name, phase_name, text)
      except Exception:
        logger.debug('리액션 건의 등록 실패', exc_info=True)

  # 15% 확률로 잡담 (Haiku 생성) — 작업 맥락 농담만
  if random.random() < 0.15:
    meme_sender = random.choice(others)
    try:
      agent = office.agents.get(meme_sender)
      system = agent._build_system_prompt() if agent else ''
      prompt = (
        f'팀이 방금 "{phase_name}" 작업을 진행했습니다.\n'
        f'그 작업 맥락에 걸친 가벼운 농담 한마디 (도구·기법·코드 소재 허용).\n'
        f'커피·점심·날씨·야근·회식·출퇴근 등 물리 경험 소재는 절대 금지.\n'
        f'30자 이내, 이모지 1개, 메신저 톤. 마크다운 금지.'
      )
      full = f'{system}\n\n---\n\n{prompt}' if system else prompt
      response = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=15.0)
      meme = response.strip().split('\n')[0][:40]
      if meme and not any(h in meme for h in (
        '커피', '점심', '날씨', '야근', '회식', '퇴근', '출근', '지하철', '버스',
      )):
        await office._emit(meme_sender, meme, 'response')
    except Exception:
      logger.debug("잡담 생성 실패", exc_info=True)

  # 대화 체인: 첫 리액터 이후 30% 확률로 다른 에이전트가 응답
  if first_reaction_text and random.random() < 0.3:
    chain_candidates = [n for n in others if n != first_reactor]
    if chain_candidates:
      chain_responder = random.choice(chain_candidates)
      try:
        agent = office.agents.get(chain_responder)
        system = agent._build_system_prompt() if agent else ''
        prompt = (
          f'동료 {display_name(first_reactor)}이(가) "{first_reaction_text}"라고 했습니다.\n'
          f'이에 대해 15~30자로 구체 응답(동의+근거, 반론, 추가 정보 중 하나). '
          f'"굿굿/맞아요/좋네요/기대돼요" 같은 빈 맞장구면 [PASS]만 출력하세요.\n'
          f'메신저 톤. 마크다운 금지.'
        )
        full = f'{system}\n\n---\n\n{prompt}' if system else prompt
        response = await run_claude_isolated(full, model='claude-haiku-4-5-20251001', timeout=15.0)
        chain_text = response.strip().split('\n')[0][:50]
        if (
          chain_text
          and '[PASS]' not in chain_text.upper()
          and len(chain_text) >= 15
          and not any(p in chain_text for p in (
            '굿굿', '맞아요', '좋네요', '좋아요', '든든하', '기대돼',
          ))
        ):
          await office._emit(chain_responder, chain_text, 'response')
      except Exception:
        logger.debug("대화 체인 응답 생성 실패", exc_info=True)



async def _consult_peers(
  office,
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

      agent = office.agents.get(target)
      if not agent:
        continue

      target_name_kr = display_name(target)
      worker_name_kr = display_name(worker_name)

      try:
        await office._emit(target, '', 'typing')
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
          await office._emit(target, answer_text, 'response')
          consultation_results.append(f'{target_name_kr}: {answer_text}')
          # 피드백 수집
          office._phase_feedback.append({
            'from': target_name_kr,
            'phase': phase.get('name', ''),
            'content': answer_text[:100],
          })
          # 협업 관찰 기록 — 작업자 → 자문 대상 의존 관계
          office._record_dynamic(
            from_agent=worker_name,
            to_agent=target,
            dynamic_type='consulted',
            description=f'[{phase.get("name", "")}] {question[:80]}',
          )
      except Exception:
        logger.debug("팀원 자문 실행 실패: %s", target, exc_info=True)

    return '\n'.join(consultation_results)

  except Exception:
    logger.debug("자문 필요 여부 판단 실패", exc_info=True)
    return ''



async def _peer_review(
  office,
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
  reviewer_ids = office._PEER_REVIEWERS.get(worker_name, ['planner', 'developer'])
  # 최대 2명
  reviewer_ids = reviewer_ids[:2]

  reviews = []
  concern_detected = False

  for reviewer_id in reviewer_ids:
    reviewer_name_kr = display_name(reviewer_id)
    worker_name_kr = display_name(worker_name)

    try:
      await office._emit(reviewer_id, '', 'typing')
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
        await office._emit(reviewer_id, feedback, 'response')
        has_concern = '[CONCERN]' in feedback
        if has_concern:
          concern_detected = True
        reviews.append({
          'reviewer': reviewer_id,
          'feedback': feedback.replace('[CONCERN]', '').strip(),
          'concern': has_concern,
        })
        # 피드백 수집
        office._phase_feedback.append({
          'from': reviewer_name_kr,
          'phase': phase_name,
          'content': feedback.replace('[CONCERN]', '').strip(),
        })
        # 협업 관찰 기록 — 리뷰어 → 작업자 상호작용
        office._record_dynamic(
          from_agent=reviewer_id,
          to_agent=worker_name,
          dynamic_type='peer_concern' if has_concern else 'peer_approved',
          description=f'[{phase_name}] {feedback.replace("[CONCERN]", "").strip()[:80]}',
        )
    except Exception:
      logger.debug("피어 리뷰 실행 실패: %s", reviewer_id, exc_info=True)

  # [CONCERN] 감지 시 담당자에게 보완 기회 1회 제공
  if concern_detected:
    concern_items = [r['feedback'] for r in reviews if r.get('concern')]
    concern_text = '\n'.join(f'- {item}' for item in concern_items)
    worker_name_kr = display_name(worker_name)
    await office._emit('teamlead', f'{worker_name_kr}, 피어 리뷰에서 우려 사항이 나왔습니다. 확인 부탁합니다.', 'response')

    try:
      agent = office.agents.get(worker_name)
      if agent:
        await office._emit(worker_name, '', 'typing')
        revision_prompt = (
          f'[프로젝트] {user_input[:500]}\n\n'
          f'[당신의 산출물] {content[:3000]}\n\n'
          f'[피어 리뷰 우려사항]\n{concern_text}\n\n'
          f'위 우려사항을 반영하여 산출물을 보완하세요.\n'
          f'전체를 다시 작성하되, 우려사항을 해결하세요.'
        )
        revised = await agent.handle(revision_prompt)
        if revised and len(revised) > 100:
          await office._emit(worker_name, f'{phase_name} 피어 리뷰 반영 완료했습니다.', 'response')
          reviews.append({'revised': True, 'content': revised})
    except Exception:
      logger.warning("피어 리뷰 우려사항 보완 실패: %s", worker_name, exc_info=True)

  return reviews



async def _handoff_comment(office, from_agent: str, to_agent: str, phase_name: str) -> None:
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
      await office._emit(from_agent, text, 'response')
      # 인수인계 코멘트도 피드백에 수집
      office._phase_feedback.append({
        'from': from_name,
        'phase': phase_name,
        'content': text,
      })
  except Exception:
    logger.debug("인수인계 코멘트 생성 실패: %s → %s", from_agent, to_agent, exc_info=True)



async def _task_acknowledgment(office, agent_name: str, phase_name: str) -> None:
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
      await office._emit(agent_name, text, 'response')
  except Exception:
    logger.debug("업무 수령 확인 생성 실패: %s", agent_name, exc_info=True)
    await office._emit(agent_name, '네, 확인했습니다. 시작하겠습니다.', 'response')



async def _contextual_reaction(office, reactor: str, phase_name: str, worker: str) -> str:
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



def _resolve_reviewer(office, worker: str, prompt: str) -> tuple[str, str] | None:
  '''업무 내용 키워드 기반으로 리뷰어를 결정한다. 자기 자신은 제외.'''
  for keywords, reviewer, perspective in office._KEYWORD_REVIEWER_MAP:
    if reviewer == worker:
      continue  # 자기 자신에게 자문 요청 불가
    if any(kw in prompt for kw in keywords):
      return reviewer, perspective
  # 키워드 매칭 없으면 기본 매핑 사용
  config = office._SECOND_OPINION_MAP.get(worker)
  if config and config[0] != worker:
    return config
  return None



async def _work_commentary(office, worker: str, phase_name: str, result_preview: str) -> None:
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
      await office._emit(commenter, text, 'response')
  except Exception:
    logger.debug("작업 코멘터리 생성 실패", exc_info=True)



async def _phase_intro(office, agent_name: str, phase_name: str) -> None:
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
      await office._emit(agent_name, text, 'response')
      return
  except Exception:
    logger.debug("단계 시작 포부 생성 실패: %s", agent_name, exc_info=True)
  # 폴백
  await office._emit(agent_name, fallback_intros.get(agent_name, '시작하겠습니다 🚀'), 'response')



async def _route_agent_mentions(office, speaker: str, content: str) -> None:
  '''에이전트 산출물/발언에서 @멘션을 감지하고 대상 에이전트가 응답하게 한다.

  작업 중 에이전트끼리 자연스럽게 질문/토론하는 효과.
  '''
  from orchestration.meeting import MENTION_MAP
  from runners.claude_runner import run_claude_isolated as _run_claude_isolated
  mentions = re.findall(
    r'@([가-힣A-Za-z]+(?:님)?)[,.]?\s*([^@\n]{5,150})',
    content,
  )
  if not mentions:
    return

  seen_targets = set()
  for raw_target, question_text in mentions[:3]:
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
      try:
        response = await _run_claude_isolated(
          f'당신은 팀장입니다. {display_name(speaker)}이(가) 작업 중 질문했습니다:\n'
          f'"{question}"\n짧게 1~2문장으로 답변하세요 (메신저 톤, 마크다운 금지).',
          model='claude-haiku-4-5-20251001', timeout=20.0,
        )
        await office._emit('teamlead', response.strip()[:150], 'response')
      except Exception:
        logger.debug("에이전트→팀장 질문 라우팅 실패", exc_info=True)
    else:
      agent = office.agents.get(target_id)
      if agent:
        try:
          await office._emit(target_id, '', 'typing')
          answer = await agent.respond_to(display_name(speaker), question)
          if answer:
            await office._emit(target_id, answer[:200], 'response')

            try:
              await office._file_commitment_suggestion(
                committer_id=target_id,
                message=answer,
                source_speaker=speaker,
                source_message=question,
              )
            except Exception:
              logger.debug('멘션 응답 다짐 등록 실패', exc_info=True)

            try:
              office.team_memory.add_dynamic(TeamDynamic(
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
