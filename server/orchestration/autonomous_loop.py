# 자율 활동 루프 + 리액션 상호작용 — office.py에서 분리 (P1 로드맵 2단계)
#
# 원칙: 행동 변경 금지. self.* → office.* 기계적 치환만.
# Office 클래스의 public/private 메서드는 forwarder로 유지되어 내부 호출 경로 보존.
from __future__ import annotations

import asyncio
import json
import logging
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.team import WORKER_IDS, display_name
from log_bus.event_bus import LogEvent
from runners.gemini_runner import run_gemini

logger = logging.getLogger(__name__)

_DIGEST_PATH = Path(__file__).parent.parent / 'data' / 'team_digests.json'


def load_digest_state(office: Any) -> dict:
  try:
    data: dict = json.loads(_DIGEST_PATH.read_text())
    return data
  except Exception:
    return {'last_reviewed_ts': '', 'last_summary': '', 'history': []}


def save_digest_state(office: Any, state: dict) -> None:
  try:
    _DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DIGEST_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))
  except Exception:
    logger.debug('digest 저장 실패', exc_info=True)


def stop_loop(office: Any) -> None:
  '''자발적 활동 루프를 중단한다.'''
  office._autonomous_running = False


# 자율 대화 결정 트리 (한눈에 보는 흐름)
# ─────────────────────────────────────────────────────────────
# 1. run_loop iteration: 작업 중(state != IDLE/COMPLETED)이면 60s sleep 후 재시도
# 2. react_to_received_reactions: user 긍정 리액션에 감사 한마디 (10%, 쿨다운)
# 3. agents_react_to_peers: LLM 없이 키워드 매핑 이모지 자동 리액션
# 4. _gather_conversation_context: 팀장 요약 + 최근 로그 → recent_context + recent
# 5. _detect_topic_stuck: 3회 반복 키워드 2개 이상 → stuck=True (강제 전환)
# 6. _gather_real_seeds: 미처리 건의 / 축적 교훈 / 최근 프로젝트 조합
# 7. _choose_topic: stuck ? 신선 토픽 / seed 있으면 의논 주제 / 아니면 맥락 유지
# 8. _pick_speakers: 최근 2회 이상 말한 사람 제외, 1~2명 (75% 1명)
# 9. _load_code_context: 최근 커밋 + diff stat → 개선 모드 시드용
# 10. 각 speaker: agent.reflect → 자동 건의 등록 + 다짐 감지 + 1단/2단 체인
# 11. _maybe_teamlead_closing: 체인 있음 50% / 없음 10% 팀장 관찰
# 12. 5~15분 sleep 후 iteration 반복
#
# 재시도 정책
# - Gemini/Claude 오류는 run_gemini / run_claude_isolated 내부에서 2회 자동 재시도.
# - 그 후에도 실패하면 빈 문자열 반환 → 이 루프는 해당 단계를 조용히 건너뛰고
#   다음 iteration(5~15분 후)에 복귀. 사용자 관측성이 낮아 향후 관측 이벤트 추가 여지.


async def _gather_conversation_context(office: Any) -> tuple[str, list[dict]]:
  '''최근 대화 맥락 문자열 + raw log 리스트.

  팀장 요약(digest)이 있으면 압축본 + 직전 5건, 없으면 raw 10건.
  '''
  digest = getattr(office, 'latest_digest_summary', '') or load_digest_state(office).get('last_summary', '')
  recent: list[dict] = []
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
    last_raw = '\n'.join(chat_lines[-5:]) if chat_lines else ''
    if digest:
      recent_context = (
        f'[팀장 요약 — 이전 대화 압축본]\n{digest}\n\n'
        f'[직전 대화 5건]\n{last_raw}' if last_raw else
        f'[팀장 요약 — 이전 대화 압축본]\n{digest}'
      )
    else:
      recent_context = '\n'.join(chat_lines[-10:]) if chat_lines else '(조용한 사무실)'
  except Exception:
    recent_context = '(조용한 사무실)'
  return recent_context, recent


def _detect_topic_stuck(recent_context: str) -> tuple[bool, list[str]]:
  '''같은 키워드가 3회 이상 반복되며 2개 이상이면 고착으로 판정.'''
  from orchestration.office import _extract_keywords
  if not recent_context:
    return False, []
  from collections import Counter
  ctx_counter: Counter = Counter()
  for line in recent_context.split('\n'):
    for kw in _extract_keywords(line):
      if len(kw) >= 3:
        ctx_counter[kw] += 1
  repeated = [k for k, n in ctx_counter.items() if n >= 3]
  stuck = len(repeated) >= 2
  if stuck:
    logger.info('자율 대화 주제 고착 감지 — 강제 전환. 반복 키워드: %s', repeated[:5])
  return stuck, repeated


def _gather_recent_topic_blocklist(office: Any) -> list[str]:
  '''최근 5시간 autonomous 발언 + pending 건의 제목에서 재발 주제 추출.

  - autonomous 12건 + pending suggestion 전체 제목에서 3+글자 키워드 빈도 집계
  - 2회 이상 등장한 키워드를 "이미 다뤄진 주제"로 반환 (최대 12개)
  - stuck 여부 무관하게 _choose_topic에 전달되어 발화에서 제외됨
  '''
  from orchestration.office import _extract_keywords
  from collections import Counter
  bag: Counter[str] = Counter()
  try:
    from db.log_store import load_logs
    logs = load_logs(limit=40)
    for log in logs:
      if log.get('event_type') != 'autonomous':
        continue
      for kw in _extract_keywords(log.get('message', '')):
        if len(kw) >= 3:
          bag[kw] += 1
  except Exception:
    pass
  try:
    from db.suggestion_store import list_suggestions
    for s in list_suggestions(status='pending')[:20]:
      for kw in _extract_keywords(s.get('title', '')):
        if len(kw) >= 3:
          bag[kw] += 2  # 건의는 가중치 2배 — 이미 공식화된 주제
  except Exception:
    pass
  return [kw for kw, n in bag.most_common(30) if n >= 2][:12]


def _team_recent_lines(
  recent: list[dict], speaker_name: str, own_limit: int = 5, peer_limit: int = 2,
) -> list[str]:
  '''speaker 본인 own_limit건 + 동료별 peer_limit건씩 autonomous 발언 라인.

  같은 기법/주제를 동료가 이미 얘기했는지 speaker가 인지하도록 프롬프트에 주입.
  '''
  from collections import defaultdict
  buckets: dict[str, list[str]] = defaultdict(list)
  for log in recent:
    aid = log.get('agent_id', '')
    if aid not in ('planner', 'designer', 'developer', 'qa', 'teamlead'):
      continue
    if log.get('event_type') not in ('autonomous', 'response'):
      continue
    msg = (log.get('message') or '').strip()
    if not msg:
      continue
    buckets[aid].append(msg[:140])

  lines: list[str] = []
  own = buckets.get(speaker_name, [])[:own_limit]
  lines.extend(own)
  for peer, msgs in buckets.items():
    if peer == speaker_name:
      continue
    for m in msgs[:peer_limit]:
      lines.append(f'[{peer}] {m}')
  return lines[:12]


def _gather_real_seeds(office: Any, recent_context: str) -> str:
  '''미처리 건의 + 축적 교훈 + 최근 프로젝트에서 구체 시드 조합.'''
  from orchestration.office import _extract_keywords
  seed_parts: list[str] = []
  try:
    from db.suggestion_store import list_suggestions as _list_sugg
    pendings_all = _list_sugg(status='pending')
    recent_blob = (recent_context or '').lower()
    filtered: list[dict] = []
    for s in pendings_all:
      title = (s.get('title') or '')
      tokens = [t for t in _extract_keywords(title) if len(t) >= 3]
      if tokens and any(t.lower() in recent_blob for t in tokens):
        continue
      filtered.append(s)
      if len(filtered) >= 3:
        break
    if filtered:
      seed_parts.append(
        '[아직 미해결 건의]\n'
        + '\n'.join(f'- ({s["category"]}) {s["title"]}' for s in filtered)
      )
  except Exception:
    pass
  try:
    lessons = office.team_memory.get_all_lessons(limit=3)
    if lessons:
      seed_parts.append(
        '[팀 축적 교훈]\n' + '\n'.join(f'- {l.lesson}' for l in lessons)
      )
  except Exception:
    pass
  try:
    recents_mem = office.team_memory.get_recent_projects(limit=2)
    if recents_mem:
      seed_parts.append(
        '[최근 프로젝트]\n'
        + '\n'.join(f'- {p.title} ({p.outcome})' for p in recents_mem)
      )
  except Exception:
    pass
  return '\n\n'.join(seed_parts)


def _choose_topic(
  stuck: bool,
  repeated: list[str],
  concrete_seed: str,
  recent_context: str,
  project_context: str,
  recent_topic_blocklist: list[str] | None = None,
) -> str:
  '''주제 선택 — stuck/seed 존재/신선도에 따라 분기.

  recent_topic_blocklist는 stuck 여부 무관하게 "최근 반복 + 건의화된 주제"로
  매 호출 주입되어, 에이전트가 이미 다룬 소재를 다시 꺼내지 않게 한다.
  '''
  fresh_topics = [
    '본인 전문 영역의 구체적 기법/도구 공유 (버전, 수치 포함)',
    '현재 진행 중인 업무 흐름에서 발견한 병목이나 낭비',
    '다른 팀원 전문 영역에 던지는 열린 질문',
    '과거 프로젝트 교훈 중 재적용 가능한 것',
    '본인이 최근 학습한 새 기법/라이브러리',
    '팀 내 역할 경계에서 오해 소지가 있는 지점',
  ]
  # stuck 발동 키워드 + 블록리스트 병합 (중복 제거)
  all_banned: list[str] = []
  seen: set[str] = set()
  for kw in (repeated if stuck else []):
    if kw not in seen:
      seen.add(kw)
      all_banned.append(kw)
  for kw in (recent_topic_blocklist or []):
    if kw not in seen:
      seen.add(kw)
      all_banned.append(kw)

  banned_kws = ''
  if all_banned:
    header = (
      '[절대 금지: 최근 5시간 내 반복되었거나 이미 건의로 올라간 주제/키워드]'
      if not stuck else
      '[절대 금지: 최근에 반복된 + 이미 건의로 올라간 주제/키워드]'
    )
    banned_kws = (
      f'\n\n{header}\n'
      f'- {", ".join(all_banned[:15])}\n'
      f'(같은 키워드/기법명/커밋해시 한 번만 더 나와도 [PASS] 처리. '
      f'이미 다룬 주제의 재탕은 진전이 아니다.)'
    )

  use_fresh = stuck or random.random() < 0.3
  if concrete_seed and (stuck or random.random() < 0.5):
    return (
      f'[의논 주제 — 아래 중 하나를 골라 한 사람에게 구체 질문/반론/제안하라]\n'
      f'(건의 내용을 업무에 즉시 반영하지 말고, 찬반·보완·반론으로만 토론하라)\n\n'
      f'{concrete_seed}\n{banned_kws}'
    )
  if use_fresh:
    seed = random.choice(fresh_topics)
    return (
      f'[완전히 새 주제] {seed}\n'
      f'(이전 대화에 이어가지 말고 새 이야기를 꺼내세요){banned_kws}'
    )
  base = f'{recent_context}\n{project_context}' if project_context else recent_context
  return f'{base}{banned_kws}'


def _pick_speakers(recent: list[dict]) -> tuple[list[str], list[str]]:
  '''(speakers, candidates) 반환. 최근 2회 이상 말한 에이전트 제외, 1~2명 선택.'''
  recent_speaker_count: dict[str, int] = {}
  for l in recent[-8:]:
    if l.get('agent_id') in ('planner', 'designer', 'developer', 'qa'):
      recent_speaker_count[l['agent_id']] = recent_speaker_count.get(l['agent_id'], 0) + 1

  all_candidates = ['planner', 'designer', 'developer', 'qa']
  candidates = [c for c in all_candidates if recent_speaker_count.get(c, 0) < 2]
  if not candidates:
    candidates = all_candidates
  num_speakers = random.choice([1, 1, 1, 2])
  speakers = random.sample(candidates, min(num_speakers, len(candidates)))
  return speakers, candidates


def _load_code_context() -> str:
  '''최근 커밋 로그 + diff stat (개선 모드 시드용, 한 iteration당 1회).'''
  try:
    import subprocess as _sp
    from pathlib import Path as _P
    root = _P(__file__).parent.parent.parent
    log_out = _sp.run(
      ['git', 'log', '--oneline', '-n', '8'],
      cwd=str(root), capture_output=True, text=True, timeout=3,
    ).stdout.strip()
    diff_out = _sp.run(
      ['git', 'diff', '--stat', 'HEAD~5..HEAD'],
      cwd=str(root), capture_output=True, text=True, timeout=3,
    ).stdout.strip()
    if log_out or diff_out:
      return f'[최근 커밋]\n{log_out}\n\n[최근 5커밋 변경 파일]\n{diff_out[:2000]}'
  except Exception:
    pass
  return ''


async def _run_speaker_chain(
  office: Any,
  speaker_name: str,
  topic: str,
  candidates: list[str],
  code_ctx: str,
  recent_logs: list[dict] | None = None,
) -> str:
  '''한 speaker의 발화 → 1단 반응 → 2단 결론 체인 실행.

  반환: first_reactor 이름 (체인이 돌았으면). 못 돌면 빈 문자열.
  '''
  agent = office.agents.get(speaker_name)
  if not agent:
    return ''

  # 트렌드 리서치 모드 — speaker가 자기 전문 영역의 최신 트렌드를 검색해
  # 본인 또는 동료의 프롬프트를 강화한다. 발화로 끝나므로 체인은 돌지 않음.
  if random.random() < 0.12:
    try:
      from orchestration import trend_research
      did = await trend_research.maybe_research(office, speaker_name)
      if did:
        return ''
    except Exception:
      logger.debug('trend_research 실패: %s', speaker_name, exc_info=True)

  # 본인 5개 + 동료 각 2개 — 같은 주제 반복 방지용. recent_logs 있으면 재사용.
  own_recent: list[str] = []
  try:
    if recent_logs is None:
      from db.log_store import load_logs as _load_logs
      recent_logs = _load_logs(limit=60)
    own_recent = _team_recent_lines(recent_logs, speaker_name)
  except Exception:
    pass

  mode = 'joke' if random.random() < 0.3 else 'improvement'
  message = await agent.reflect(topic, own_recent=own_recent, mode=mode, code_context=code_ctx)
  if not message:
    return ''

  # autonomous_mode를 LogEvent.data에 표기 — 건의 등록/검색/UI에서 모드 필터 가능
  speaker_event = LogEvent(
    agent_id=speaker_name, event_type='autonomous', message=message,
    data={'autonomous_mode': mode},
  )
  await office.event_bus.publish(speaker_event)

  # mode=joke 발화는 filer 3종 모두 조기 return — 오탐 구조적 차단
  try:
    await office._auto_file_suggestion(
      speaker_name, message, source_log_id=speaker_event.id, mode=mode,
    )
  except Exception:
    logger.debug('자동 건의 등록 실패', exc_info=True)
  try:
    await office._file_commitment_suggestion(
      committer_id=speaker_name, message=message, source_log_id=speaker_event.id, mode=mode,
    )
  except Exception:
    logger.debug('자발 다짐 등록 실패', exc_info=True)
  try:
    await office._file_capability_gap_suggestion(
      speaker_id=speaker_name, message=message, source_log_id=speaker_event.id, mode=mode,
    )
  except Exception:
    logger.debug('능력 부족 등록 실패', exc_info=True)

  # 1단 반응 (50%) — 반응은 구조상 "상대 발언에 대한 동의/보완"이므로
  # 새로운 실행 요구로 보기 어렵다. mode='reaction' 태깅으로 filer 중
  # auto_file/capability_gap은 skip, commitment만 통과시켜 다짐은 포착.
  first_reactor = ''
  if random.random() < 0.5:
    reactors = [n for n in candidates if n != speaker_name]
    if reactors:
      first_reactor = random.choice(reactors)
      first_reply = await autonomous_react(
        reactor_name=first_reactor, prior_speaker=speaker_name, prior_message=message,
      )
      if first_reply:
        reactor_event = LogEvent(
          agent_id=first_reactor, event_type='autonomous', message=first_reply,
          data={'autonomous_mode': 'reaction'},
        )
        await office.event_bus.publish(reactor_event)
        try:
          # 다짐은 reaction에서도 포착 (commitment는 mode 무관 — 아이브의
          # "~하겠습니다" 같은 실행 추적이 필요하기 때문)
          await office._file_commitment_suggestion(
            committer_id=first_reactor, message=first_reply,
            source_speaker=speaker_name, source_message=message,
            source_log_id=reactor_event.id,
          )
        except Exception:
          logger.debug('리액터 다짐 등록 실패', exc_info=True)
        try:
          await office._file_capability_gap_suggestion(
            speaker_id=first_reactor, message=first_reply,
            source_log_id=reactor_event.id, mode='reaction',
          )
        except Exception:
          logger.debug('리액터 능력 부족 등록 실패', exc_info=True)
        # 2단 결론 (30%) — 원 발언자의 재반론/수용. mode='closing'.
        if random.random() < 0.3:
          closing = await autonomous_closing(
            original_speaker=speaker_name, original_message=message,
            challenger=first_reactor, challenge=first_reply,
          )
          if closing:
            closing_event = LogEvent(
              agent_id=speaker_name, event_type='autonomous', message=closing,
              data={'autonomous_mode': 'closing'},
            )
            await office.event_bus.publish(closing_event)
            try:
              await office._file_commitment_suggestion(
                committer_id=speaker_name, message=closing,
                source_speaker=first_reactor, source_message=first_reply,
                source_log_id=closing_event.id,
              )
            except Exception:
              logger.debug('클로징 다짐 등록 실패', exc_info=True)
            try:
              await office._file_capability_gap_suggestion(
                speaker_id=speaker_name, message=closing,
                source_log_id=closing_event.id, mode='closing',
              )
            except Exception:
              logger.debug('클로징 능력 부족 등록 실패', exc_info=True)
      else:
        first_reactor = ''
  return first_reactor


async def _maybe_teamlead_closing(
  office: Any, recent_context: str, speaker_name: str, first_reactor: str,
) -> None:
  '''체인이 돌았으면 50%, 아니면 10% 확률로 팀장 관찰 한 문장.'''
  teamlead_chance = 0.5 if first_reactor else 0.1
  if random.random() >= teamlead_chance:
    return

  try:
    chain_hint = ''
    if first_reactor:
      chain_hint = (
        f'\n[방금 돈 의논]\n{display_name(speaker_name)} → {display_name(first_reactor)} 순으로 '
        f'반박·보완이 오갔다.\n'
        f'논의 내용에 대한 관찰·관점 한 문장. 결론이 모호하면 [PASS].\n'
      )
    teamlead_msg = await run_gemini(
      prompt=(
        f'당신은 팀장 잡스입니다. AI 에이전트로 물리 경험 없음.\n'
        f'최근 팀 상황:\n{recent_context}\n{chain_hint}\n'
        f'[절대 금지 — 어기면 [PASS]]\n'
        f'- 선언형 명령 금지: "~진행합니다", "~적용합니다", "~결정합니다", "~최우선 과제로", '
        f'"~을 지시합니다", "~체계를 수립합니다"\n'
        f'  (실제 프로젝트/태스크는 사용자가 지시할 때만 시작된다. 자발적 대화에서는 작업을 개시할 권한이 없다.)\n'
        f'- 빈 응원/감탄/맞장구 금지 ("시너지 최고", "기대된다", "굿굿" 등)\n'
        f'- 커피/점심/날씨 등 물리 소재 금지\n'
        f'[허용]\n'
        f'- 관찰 공유: "~점이 흥미롭다", "~경향이 보인다"\n'
        f'- 의견 제시: "~이 더 효과적일 것 같다", "~을 검토해볼 가치가 있다"\n'
        f'- 우려 표명: "~부분이 걱정된다", "~리스크가 있어 보인다"\n'
        f'- 질문/토론 유도: "~에 대해 어떻게 생각하는가?"\n'
        f'[출력]\n'
        f'- 30자 이상, 구체 근거 포함. 없거나 선언형이면 [PASS]. 90%는 [PASS]가 정답.'
      ),
    )
    text = teamlead_msg.strip()
    first_line = text.split('\n')[0].strip()
    declarative_patterns = (
      '진행합니다', '적용합니다', '결정합니다', '지시합니다', '수립합니다',
      '최우선 과제', '최우선과제', '즉시 도입', '즉시도입',
      '반영하겠습니다', '시행합니다', '착수합니다',
    )
    is_declarative = any(p in text for p in declarative_patterns)
    if (
      text and '[PASS]' not in text.upper()
      and len(first_line) >= 30
      and not is_declarative
      and not any(p in text for p in (
        '굿굿', '맞아요', '기대된', '즐겁게', '시너지', '커피', '점심', '날씨',
      ))
    ):
      await office.event_bus.publish(LogEvent(
        agent_id='teamlead', event_type='autonomous', message=text,
      ))
    elif is_declarative:
      logger.info('팀장 선언형 발언 드랍: %s', first_line[:80])
  except Exception:
    logger.debug("팀장 자발적 활동 실패", exc_info=True)


async def run_loop(office: Any) -> None:
  '''에이전트 자발적 활동 백그라운드 루프. idle 상태에서만 5~15분 간격.

  단계: react_to_received_reactions → agents_react_to_peers →
  gather_context → detect_stuck → gather_seeds → choose_topic →
  pick_speakers → load_code_context → speaker_chain(들) → teamlead_closing.
  상세 결정 트리는 모듈 상단 주석 참고.
  '''
  from orchestration.state import OfficeState

  office._autonomous_running = True
  await asyncio.sleep(random.randint(120, 300))

  while office._autonomous_running:
    try:
      if office._state not in (OfficeState.IDLE, OfficeState.COMPLETED):
        await asyncio.sleep(60)
        continue

      await react_to_received_reactions(office)
      await agents_react_to_peers(office)

      recent_context, recent = await _gather_conversation_context(office)

      # 최근 프로젝트 경험 — topic fallback용
      project_context = ''
      try:
        projects = office.team_memory.get_recent_projects(limit=2)
        if projects:
          project_context = '\n'.join(
            f'- 최근 프로젝트: {p.title} ({p.outcome})' for p in projects
          )
      except Exception:
        pass

      stuck, repeated = _detect_topic_stuck(recent_context)
      concrete_seed = _gather_real_seeds(office, recent_context)
      topic_blocklist = _gather_recent_topic_blocklist(office)
      topic = _choose_topic(
        stuck, repeated, concrete_seed, recent_context, project_context,
        recent_topic_blocklist=topic_blocklist,
      )

      speakers, candidates = _pick_speakers(recent)
      code_ctx = _load_code_context()

      # speaker chain에서 팀 발언 참조용으로 더 깊은 로그 1회 로딩
      deep_logs: list[dict] = []
      try:
        from db.log_store import load_logs as _load_logs_deep
        deep_logs = _load_logs_deep(limit=60)
      except Exception:
        deep_logs = recent

      first_reactor = ''
      speaker_name = ''
      for speaker_name in speakers:
        first_reactor = await _run_speaker_chain(
          office, speaker_name, topic, candidates, code_ctx,
          recent_logs=deep_logs,
        )

      await _maybe_teamlead_closing(office, recent_context, speaker_name, first_reactor)

    except Exception:
      logger.debug("자발적 활동 루프 에러", exc_info=True)

    await asyncio.sleep(random.randint(300, 900))


async def react_to_received_reactions(office: Any) -> None:
  '''내(에이전트) 최근 메시지에 리액션이 달렸으면 감사/답례 한마디.

  **무한 루프 방지:**
  - 답례 대상은 response/message만 (autonomous 제외) — 답례 메시지에 또 답례 X
  - 연속 발언 쿨다운: 같은 에이전트가 최근 5개 중 2회 이상이면 스킵
  - 동일 log_id는 data.thanked 플래그로 재진입 차단
  '''
  from db.log_store import load_logs, DB_PATH

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

    agent = office.agents.get(agent_id)
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
      text = thanks.strip()
      first_line = text.split('\n')[0].strip()
      # 빈 답례 재차 필터 (LLM이 규칙 무시하고 내놓을 수 있음)
      if (
        text and '[PASS]' not in text.upper()
        and len(first_line) >= 20
        and not any(p in text for p in (
          '감사합니다', '감사해요', '천만에', '기대에 부응', '화이팅', '파이팅',
          '좋습니다', '굿굿', '든든', '시너지',
        ))
      ):
        await office.event_bus.publish(LogEvent(
          agent_id=agent_id,
          event_type='autonomous',
          message=text,  # 전체 보존
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


async def agents_react_to_peers(office: Any) -> None:
  '''동료의 최근 메시지에 에이전트가 이모지로 리액션을 단다 (Task #10).

  LLM 호출 없이 키워드 기반 heuristic으로 판단 — 토큰 비용 0.
  '''
  from db.log_store import load_logs, update_log_reactions

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
    reacted_agents: set[str] = set()
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
        await office.event_bus.publish(LogEvent(
          agent_id='system',
          event_type='reaction_update',
          message='',
          data={'log_id': target['id'], 'reactions': reactions},
        ))
    except Exception:
      logger.debug('에이전트 피어 리액션 실패', exc_info=True)


async def autonomous_react(
  reactor_name: str,
  prior_speaker: str,
  prior_message: str,
) -> str:
  '''자발적 대화 1단 반응 — 구체 보완/반론만, 빈 맞장구는 [PASS].'''
  try:
    react_resp = await run_gemini(
      prompt=(
        f'당신은 {display_name(reactor_name)}입니다. AI 에이전트이며 물리 경험 없음.\n'
        f'동료 {display_name(prior_speaker)}의 발언: "{prior_message}"\n\n'
        f'[반응 규칙 — 엄격]\n'
        f'- "맞아요/굿굿/든든/기대돼요/좋네요" 등 빈 맞장구 절대 금지 → [PASS]\n'
        f'- 커피/점심/날씨 등 물리 경험 언급 금지 → [PASS]\n'
        f'- 오직 허용: 본인 전문 영역에서 구체적 보완/반론/추가 정보 (수치·파일명·기법)\n'
        f'- 30자 이상, 구체 근거 포함. 없으면 [PASS].\n'
        f'70%는 [PASS]가 정답.'
      ),
    )
    react_text = react_resp.strip().split('\n')[0].strip()
    if (
      react_text
      and '[PASS]' not in react_text.upper()
      and len(react_text) >= 30
      and not any(p in react_text for p in (
        '굿굿', '맞아요', '좋네요', '좋아요', '든든하', '기대돼',
        '커피', '점심', '날씨', '퇴근', '출근',
      ))
    ):
      return react_text
  except Exception:
    logger.debug('자발적 1단 반응 실패: %s', reactor_name, exc_info=True)
  return ''


async def autonomous_closing(
  original_speaker: str,
  original_message: str,
  challenger: str,
  challenge: str,
) -> str:
  '''자발적 대화 2단 — 원 발언자의 재반론/수용 결론.'''
  try:
    resp = await run_gemini(
      prompt=(
        f'당신은 {display_name(original_speaker)}입니다. AI 에이전트.\n'
        f'당신의 원 발언: "{original_message}"\n'
        f'동료 {display_name(challenger)}의 반박/보완: "{challenge}"\n\n'
        f'[규칙]\n'
        f'- 수용 또는 재반론 중 하나를 선택. 30자 이상, 근거 필수.\n'
        f'- "감사합니다", "좋은 지적", "맞네요" 같은 빈 수용 금지 → [PASS]\n'
        f'- 수용한다면 무엇을 어떻게 바꾸겠다는지 구체로. 재반론이면 어느 지점에 동의 못하는지.\n'
        f'- 근거 없으면 [PASS].'
      ),
    )
    text = resp.strip().split('\n')[0].strip()
    if (
      text
      and '[PASS]' not in text.upper()
      and len(text) >= 30
      and not any(p in text for p in (
        '굿굿', '맞아요', '좋네요', '좋은 지적', '든든하', '감사합니다', '감사해요',
        '커피', '점심', '날씨',
      ))
    ):
      return text
  except Exception:
    logger.debug('자발적 2단 결론 실패: %s', original_speaker, exc_info=True)
  return ''
