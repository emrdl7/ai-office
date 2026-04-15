# 건의게시판 자동 등록 — office.py에서 분리 (P1 로드맵 5단계)
#
# 원칙: 행동 변경 금지. self.* → office.* 기계적 치환만.
# 3개 메서드: _file_reaction_suggestion, _auto_file_suggestion,
# _file_commitment_suggestion. PromptEvolver/건의게시판 자동화의 감지 레이어.
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from config.team import display_name
from log_bus.event_bus import LogEvent

logger = logging.getLogger(__name__)


async def _file_reaction_suggestion(office, agent_id: str, phase_name: str, message: str) -> None:
  '''소단계 리액션의 [건의] 라벨을 건의게시판에 등록. _auto_file_suggestion의 dedup을 재사용.'''
  from db.suggestion_store import create_suggestion, list_suggestions

  # [건의] 이후 문구를 제목으로
  label_idx = message.find('[건의]')
  if label_idx < 0:
    return
  tail = message[label_idx + len('[건의]'):].strip()
  title_text = (tail or message)[:40].replace('\n', ' ').strip()
  if not title_text:
    return

  # 카테고리 매칭 — _auto_file_suggestion patterns 재사용
  patterns: list[tuple[str, list[str]]] = [
    ('프로세스 개선', ['워크플로', '프로세스', 'QA 기준', '보고서', '인수인계', '리뷰', '테스트', '문서화']),
    ('도구 부족', ['도구', '자동화', '스크립트', 'API', '접근 권한']),
    ('정보 부족', ['데이터', '가정', '추정', '레퍼런스', '확인할 수 없']),
  ]
  matched_category = '아이디어'
  for category, kws in patterns:
    if any(kw in message for kw in kws):
      matched_category = category
      break

  # dedup
  try:
    all_suggestions = list_suggestions(status='')
    msg_keywords = _extract_keywords(message)
    for s in all_suggestions[:30]:
      if s['agent_id'] == agent_id and s['category'] == matched_category and s['status'] == 'pending':
        return
      s_keywords = _extract_keywords(s.get('title', '') + ' ' + s.get('content', ''))
      if msg_keywords and s_keywords:
        overlap = len(msg_keywords & s_keywords)
        smaller = min(len(msg_keywords), len(s_keywords))
        if smaller == 0:
          continue
        ratio = overlap / smaller
        threshold = 0.4 if s['category'] == matched_category else 0.55
        if ratio >= threshold:
          return
  except Exception:
    pass

  from db.suggestion_store import detect_target_agent
  target = detect_target_agent(message, speaker=agent_id)
  target_line = f'대상 에이전트: {display_name(target)}\n' if target else ''
  content = (
    f'[소단계 리액션 중 감지]\n'
    f'단계: {phase_name}\n'
    f'{display_name(agent_id)}의 발언: "{message}"\n\n'
    f'카테고리: {matched_category}\n'
    f'{target_line}'
    f'\n(자동 등록된 건의입니다. 실제 조치가 필요한지 검토 바랍니다.)'
  )
  try:
    created = create_suggestion(
      agent_id=agent_id,
      title=title_text,
      content=content,
      category=matched_category,
      target_agent=target,
    )
    await office._emit(
      'teamlead',
      f'💡 {display_name(agent_id)}의 의견을 건의게시판에 등록했습니다: "{title_text[:30]}..."',
      'system_notice',
    )
    logger.info('리액션 건의 등록: %s | %s | %s', agent_id, matched_category, title_text)
    try:
      from main import auto_triage_new_suggestion
      asyncio.create_task(auto_triage_new_suggestion(created['id']))
    except Exception:
      logger.debug('auto_triage 호출 실패', exc_info=True)
  except Exception:
    logger.debug('create_suggestion 실패', exc_info=True)



async def _auto_file_suggestion(office, agent_id: str, message: str, source_log_id: str = '') -> None:
  '''자발적 대화 중 개선 제안/도구 요구가 감지되면 건의게시판에 자동 등록.

  키워드 기반 heuristic (LLM 호출 없음 → 비용 0).
  같은 에이전트+카테고리 조합이 최근 10건 내 pending 상태면 중복 방지.
  '''
  from db.suggestion_store import create_suggestion, list_suggestions

  # 토론/질문/제안 회상 시그널 — 하나라도 있으면 건의 아님 (우선순위)
  discussion_markers = (
    '?', '까요', '까?', '실까', '을까', '는지요', '는지 궁금', '궁금',
    '여쭤', '물어', '문의', '확인 부탁', '의견이', '알려주세요',
    '듣고 싶', '공유 부탁', '알고 계신', '혹시', '어떠신', '어떨까', '어떻게 생각',
    '고민해', '고민하', '보면 좋겠', '좋을 것 같', '좋겠습니다', '좋겠어요',
    '논의해', '논의에서', '논의를', '함께 ', '함께,', '같이 ', '다 같이',
    '제안된 방안', '제안된 내용', '제안된 방법', '이야기해', '얘기해',
    '의견 주', '의견을 주', '피드백',
  )
  if any(m in message for m in discussion_markers):
    return  # 토론/질문형이면 건의 아님

  # 강한 제안 시그널 — 확실한 실행 요구여야 건의 등록
  strong_proposal = (
    '도입하자', '도입해야', '도입합시다',
    '적용하자', '적용해야', '적용합시다',
    '반영하자', '반영해야', '반영합시다',
    '추가하자', '추가해야', '변경해야', '바꿔야', '바꾸자',
    '채택하자', '채택해야', '의무화', '금지한다', '금지해야',
    '필수로', '필수적으로', '규칙으로 정하', '원칙으로 정하',
    '정해야 한다', '정해야한다', '정하자',
    '~해야 합니다', '되어야 합니다',
  )
  if not any(m in message for m in strong_proposal):
    return  # 강한 제안 시그널 없으면 건의 아님

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

  # 대상 에이전트 감지 (맥락 가드 적용) + 제목/내용 조립
  from db.suggestion_store import detect_target_agent, is_duplicate, log_event
  target = detect_target_agent(message, speaker=agent_id)
  title = message[:40].replace('\n', ' ').strip()
  target_line = f'대상 에이전트: {display_name(target)}\n' if target else ''
  content = (
    f'[자발적 대화 중 감지]\n'
    f'{display_name(agent_id)}의 발언: "{message}"\n\n'
    f'트리거 키워드: "{matched_keyword}"\n'
    f'카테고리: {matched_category}\n'
    f'{target_line}'
    f'\n(자동 등록된 건의입니다. 실제 조치가 필요한지 검토 바랍니다.)'
  )

  # 통합 의미 기반 dedup
  dup, reason = is_duplicate(title, content)
  if dup:
    logger.info('자동 건의 중복 skip: %s | reason=%s', title[:30], reason)
    # dedup 스킵 이벤트는 대상 없이 기록 (분석/튜닝용)
    try:
      log_event('(skipped)', 'dedup_skipped', {
        'reason': reason, 'title': title, 'speaker': agent_id,
      })
    except Exception:
      pass
    return

  try:
    created = create_suggestion(
      agent_id=agent_id,
      title=title,
      content=content,
      category=matched_category,
      target_agent=target,
      source_log_id=source_log_id,
    )
    log_event(created['id'], 'auto_filed', {
      'speaker': agent_id, 'target_agent': target,
      'category': matched_category, 'trigger_keyword': matched_keyword,
      'source_log_id': source_log_id,
    })
    target_hint = f' → {display_name(target)}에게 적용' if target else ''
    await office._emit(
      'teamlead',
      f'💡 {display_name(agent_id)}의 의견을 건의게시판에 등록했습니다{target_hint}: "{title[:30]}..."',
      'system_notice',
    )
    logger.info('자동 건의 등록: %s | %s | %s | target=%s', agent_id, matched_category, title, target or '(본인)')
    # 자동 판정 트리거
    try:
      from main import auto_triage_new_suggestion
      asyncio.create_task(auto_triage_new_suggestion(created['id']))
    except Exception:
      logger.debug('auto_triage 호출 실패', exc_info=True)
  except Exception:
    logger.debug('create_suggestion 실패', exc_info=True)



async def _file_commitment_suggestion(
  office,
  committer_id: str,
  message: str,
  source_speaker: str = '',
  source_message: str = '',
  source_log_id: str = '',
) -> None:
  '''에이전트가 "~하겠습니다" 류 자기 다짐을 하면 건의게시판에 등록.

  멘션 응답이든 자발적 발언이든, committer 본인이 수행하기로 약속한 경우
  target_agent=committer로 pending 등록하여 실제 실행 궤적을 남긴다.
  말로만 "반영하겠습니다" 하고 끝나는 것을 방지.
  '''
  if not message or len(message.strip()) < 15:
    return

  # 자기 다짐 시그널 — 본인이 무언가 하겠다는 1인칭 약속
  commit_markers = (
    '반영하겠', '적용하겠', '도입하겠', '추가하겠',
    '수정하겠', '개선하겠', '변경하겠', '바꾸겠',
    '정리하겠', '만들겠', '만들어보겠', '작성하겠',
    '업데이트하겠', '보완하겠', '진행하겠', '처리하겠',
    '반영할게', '적용할게', '도입할게', '추가할게',
    '수정할게', '개선할게', '정리할게',
  )
  if not any(m in message for m in commit_markers):
    return

  # 회피/불확실 시그널 — 있으면 다짐 아님
  uncertain_markers = ('할 수도', '해볼까', '고려해', '검토만', '상의 후', '여쭤', '~해도 될지')
  if any(m in message for m in uncertain_markers):
    return

  from db.suggestion_store import create_suggestion, is_duplicate, log_event

  first_line = message.strip().split('\n')[0][:80]
  title = f'[다짐] {display_name(committer_id)}: {first_line[:50]}'

  content_parts = []
  if source_speaker and source_message:
    content_parts.append(f'**요청자**: {display_name(source_speaker)}')
    content_parts.append(f'**요청**: {source_message.strip()[:300]}')
  content_parts.append(f'**다짐 발화**: "{message.strip()[:500]}"')
  content_parts.append('')
  content_parts.append(
    f'_{display_name(committer_id)}의 자기 다짐을 자동 등록했습니다. '
    f'승인 시 실제 반영 추적, 거절 시 다짐 철회._'
  )
  content = '\n'.join(content_parts)

  # 같은 committer가 같은 주제를 반복하면 — 기존 draft가 있으면 pending 승격하고
  # 새로 등록하지 않음 (draft 승격 조건 c).
  from db.suggestion_store import list_suggestions, promote_draft
  topic_key = first_line[:30]
  existing_by_committer = []
  try:
    for prev in list_suggestions(status=''):
      if prev.get('agent_id') != committer_id:
        continue
      if topic_key in (prev.get('title') or ''):
        existing_by_committer.append(prev)
  except Exception:
    logger.debug('다짐 반복 감지 실패', exc_info=True)

  if existing_by_committer:
    # 반복 다짐 — 기존 draft를 모두 pending으로 승격
    promoted_any = False
    for prev in existing_by_committer:
      if prev.get('status') == 'draft' and promote_draft(prev['id']):
        promoted_any = True
        try:
          from main import auto_triage_new_suggestion
          asyncio.create_task(auto_triage_new_suggestion(prev['id']))
        except Exception:
          logger.debug('재다짐 auto_triage 호출 실패', exc_info=True)
    if promoted_any:
      logger.info('재다짐 감지 — 기존 draft 승격: %s / %s', committer_id, topic_key)
    return

  dup, reason = is_duplicate(title, content)
  if dup:
    logger.info('다짐 건의 중복 skip: %s | reason=%s', title[:30], reason)
    return
  initial_status = 'draft'

  try:
    created = create_suggestion(
      agent_id=committer_id,
      title=title,
      content=content,
      category='프로세스 개선',
      target_agent=committer_id,
      status=initial_status,
      source_log_id=source_log_id,
    )
    log_event(created['id'], 'auto_filed', {
      'speaker': committer_id, 'target_agent': committer_id,
      'kind': 'self_commitment',
      'source_speaker': source_speaker,
      'initial_status': initial_status,
      'source_log_id': source_log_id,
    })
    status_label = '다짐(draft)' if initial_status == 'draft' else '다짐'
    await office._emit(
      'teamlead',
      f'📌 {display_name(committer_id)}의 {status_label}를 건의게시판에 등록했습니다: "{first_line[:40]}..."',
      'system_notice',
    )
    logger.info('다짐 건의 등록: %s | status=%s | %s', committer_id, initial_status, first_line[:60])
    # 협업 관찰 기록 — committer가 source_speaker 요청에 약속 이행
    if source_speaker:
      office._record_dynamic(
        from_agent=committer_id,
        to_agent=source_speaker,
        dynamic_type='committed_to_request',
        description=first_line[:80],
      )
    # draft는 auto_triage 대상 아님 — 승격 후 호출됨
    if initial_status == 'pending':
      try:
        from main import auto_triage_new_suggestion
        asyncio.create_task(auto_triage_new_suggestion(created['id']))
      except Exception:
        logger.debug('auto_triage 호출 실패', exc_info=True)
  except Exception:
    logger.debug('다짐 create_suggestion 실패', exc_info=True)
