"""Job Discovery 대화 모드 — 먼저 대화하고, 충분하면 등록 제안."""
from __future__ import annotations

import logging
import re
import json
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from orchestration.office import Office

logger = logging.getLogger(__name__)

# ── 진입 조건 ──────────────────────────────────────────────────────────────────

_DISCOVERY_KEYWORDS = [
    '알아보자', '이야기해보자', '생각해봐', '논의', '어떻게 할지', '어떻게 할까',
    '방향을 잡', '방향성', '검토해보자', '살펴보자', '같이 생각', '함께 논의',
    '상담', '조언', '제안해줘', '추천해줘', '얘기해보자', '이야기 해보자',
    '민감한데', '관심 있는데', '궁금한데', '알고 싶은데',
]

_CONFIRM_PHRASES = [
    '등록해', '등록하자', '등록할게', '그래', '응', 'ㅇㅇ', '좋아', '맞아',
    '넣어줘', '진행해', 'ㄱㄱ', '오케이', 'ok', 'OK', '예', '네',
    '이대로 해', '이대로 등록', '확인', '완료', '해줘',
]

_CANCEL_PHRASES = [
    '취소', '그냥 됐어', '다음에', '나중에', '안 해도 돼', '안 해', '됐어',
]

_EARLY_REGISTER_PHRASES = [
    '바로 등록해줘', '등록해줘', '작업으로 만들어줘', '작업 등록', '바로 해줘',
]

_DISCOVERY_SYSTEM = """\
당신은 팀장(잡스)입니다. 사용자와 자연스럽게 대화하며 작업 요구사항을 파악합니다.

규칙:
- 한 번에 질문 하나만. 짧고 자연스럽게.
- 이미 파악한 내용은 다시 묻지 마세요.
- 작업 목적, 활용 방향, 중점 사항을 파악하세요.
- 충분히 파악됐다면 자연스럽게 대화를 마무리하는 방향으로 유도하세요.
- 2-4문장, 한국어, 팀장답게 친근하고 전문적으로.
"""


# ── 상태 ────────────────────────────────────────────────────────────────────────

@dataclass
class DiscoveryState:
    turns: list[dict[str, str]] = field(default_factory=list)  # {'role': 'user'|'assistant', 'text': str}
    attachments_text: str = ''
    user_input_original: str = ''
    proposed_confirm: bool = False
    proposed_spec_id: str = ''


# ── 공개 API ────────────────────────────────────────────────────────────────────

def should_enter_discovery(user_input: str, attachments_text: str) -> bool:
    """Discovery 모드 진입 여부 결정."""
    if any(kw in user_input for kw in _DISCOVERY_KEYWORDS):
        return True
    if attachments_text.strip():
        return True
    # 요청이 짧고 구체적 목표가 불분명할 때 (30자 이하 단독 요청)
    if len(user_input.strip()) < 30:
        return True
    return False


async def start_discovery(
    office: 'Office',
    user_input: str,
    attachments_text: str,
) -> DiscoveryState:
    """Discovery 대화를 시작하고 팀장 첫 응답을 emit한다.

    spec_id 결정 없이 대화부터 시작한다.
    """
    state = DiscoveryState(
        attachments_text=attachments_text,
        user_input_original=user_input,
    )
    state.turns.append({'role': 'user', 'text': user_input})

    reply = await _generate_chat(state)
    state.turns.append({'role': 'assistant', 'text': reply})
    await office._emit('teamlead', reply, 'response')
    return state


async def continue_discovery(
    office: 'Office',
    state: DiscoveryState,
    user_input: str,
) -> DiscoveryState | None:
    """Discovery 대화를 이어간다.

    Returns:
        DiscoveryState — 계속 대화 중
        None — 등록 완료 또는 취소
    """
    state.turns.append({'role': 'user', 'text': user_input})

    # 취소
    if any(p in user_input for p in _CANCEL_PHRASES):
        await office._emit('teamlead', '알겠습니다. 나중에 필요하면 말씀해 주세요.', 'response')
        return None

    # 즉시 등록 요청 (대화 없이 바로 등록)
    if any(p in user_input for p in _EARLY_REGISTER_PHRASES):
        await _finalize_and_register(office, state)
        return None

    # 제안 후 확인 응답
    if state.proposed_confirm and any(p in user_input for p in _CONFIRM_PHRASES):
        await _finalize_and_register(office, state)
        return None

    # 제안 시점 판단
    user_turns = [t for t in state.turns if t['role'] == 'user']
    if len(user_turns) >= 2 and not state.proposed_confirm:
        if await _should_propose(state):
            reply = await _build_proposal(state)
            state.turns.append({'role': 'assistant', 'text': reply})
            state.proposed_confirm = True
            await office._emit('teamlead', reply, 'response')
            return state

    # 자연스럽게 대화 이어가기
    reply = await _generate_chat(state)
    state.turns.append({'role': 'assistant', 'text': reply})
    await office._emit('teamlead', reply, 'response')
    return state


# ── 내부 함수 ───────────────────────────────────────────────────────────────────

def _attach_section(attachments_text: str, limit: int = 800) -> str:
    """첨부파일 프롬프트 섹션 생성."""
    if not attachments_text.strip():
        return ''
    return f'\n\n[첨부 파일 내용]\n{attachments_text[:limit]}'


async def _generate_chat(state: DiscoveryState) -> str:
    """팀장 페르소나로 자연스러운 대화 응답을 생성한다."""
    from runners.gemini_runner import run_gemini
    from runners.claude_runner import run_claude_isolated
    import os

    convo = '\n'.join(
        f'{"사용자" if t["role"] == "user" else "팀장"}: {t["text"][:300]}'
        for t in state.turns[-8:]
    )
    attach_note = _attach_section(state.attachments_text)
    prompt = f'[대화]\n{convo}{attach_note}'

    try:
        if os.environ.get('GOOGLE_API_KEY'):
            return await run_gemini(prompt, system=_DISCOVERY_SYSTEM, timeout=15.0)
    except Exception:
        pass

    try:
        return await run_claude_isolated(
            f'{_DISCOVERY_SYSTEM}\n\n{prompt}',
            model='claude-haiku-4-5-20251001',
            timeout=20.0,
            max_turns=1,
        )
    except Exception:
        logger.debug('_generate_chat 실패', exc_info=True)
        return '조금 더 알려주시겠어요?'


async def _should_propose(state: DiscoveryState) -> bool:
    """수집된 정보가 작업 등록 제안에 충분한지 판단한다."""
    from runners.claude_runner import run_claude_isolated

    user_texts = ' '.join(t['text'] for t in state.turns if t['role'] == 'user')
    prompt = (
        f'아래 사용자 발언에서 구체적인 작업 목적/방향이 충분히 드러났는지 판단하세요.\n\n'
        f'[사용자 발언]\n{user_texts[:600]}\n\n'
        f'작업으로 등록할 만큼 충분하면 "YES", 아직 막연하면 "NO" 한 단어만 출력하세요.'
    )
    try:
        resp = await run_claude_isolated(
            prompt, model='claude-haiku-4-5-20251001', timeout=12.0, max_turns=1,
        )
        return resp.strip().upper().startswith('Y')
    except Exception:
        return True


async def _build_proposal(state: DiscoveryState) -> str:
    """등록 제안 메시지를 생성한다."""
    from runners.claude_runner import run_claude_isolated

    convo = '\n'.join(
        f'{"사용자" if t["role"] == "user" else "팀장"}: {t["text"][:200]}'
        for t in state.turns
    )
    attach_note = _attach_section(state.attachments_text, limit=400)
    prompt = (
        f'아래 대화를 보고, 작업 등록 제안 메시지를 작성하세요.\n\n'
        f'[대화]\n{convo}{attach_note}\n\n'
        f'형식:\n'
        f'1. 핵심 내용을 1-2문장으로 요약\n'
        f'2. "이 내용으로 작업을 등록할까요?" 라고 자연스럽게 제안\n'
        f'- 한국어, 팀장답게, 3-4문장 이내'
    )
    try:
        return await run_claude_isolated(
            prompt, model='claude-haiku-4-5-20251001', timeout=15.0, max_turns=1,
        )
    except Exception:
        return '지금까지 이야기한 내용으로 작업을 등록할까요?'


async def _compress_to_job_input(state: DiscoveryState, spec_id: str) -> dict[str, Any]:
    """대화 전체에서 Job 입력 필드를 추출한다."""
    from runners.claude_runner import run_claude_isolated
    from jobs.registry import get as get_spec

    spec = get_spec(spec_id)
    if not spec or not spec.input_fields:
        return {}

    convo = '\n'.join(
        f'{"사용자" if t["role"] == "user" else "팀장"}: {t["text"][:200]}'
        for t in state.turns
    )
    attach_note = _attach_section(state.attachments_text, limit=1200)
    fields_list = ', '.join(spec.input_fields)

    prompt = (
        f'아래 대화에서 Job 입력 필드 값을 추출하세요.\n\n'
        f'[필드 목록] {fields_list}\n'
        f'[대화]\n{convo}{attach_note}\n\n'
        f'규칙: 대화에 명시된 값만 추출. 추론 금지. 없는 필드는 빈 문자열("").\n'
        f'JSON만 출력: {{"필드명":"값"}}'
    )
    try:
        resp = await run_claude_isolated(
            prompt, model='claude-haiku-4-5-20251001', timeout=20.0, max_turns=1,
        )
        m = re.search(r'\{[\s\S]*\}', resp)
        if m:
            return json.loads(m.group())
    except Exception:
        logger.debug('_compress_to_job_input 실패', exc_info=True)
    return {}


async def _finalize_and_register(office: 'Office', state: DiscoveryState) -> None:
    """대화 내용을 분석해 Job을 등록한다.

    1. 전체 대화에서 spec_id + 필드 추출
    2. 누락 필수 필드가 있으면 _pending_job 방식으로 추가 질문
    3. 등록
    """
    from orchestration.intent import map_to_job_spec

    # 대화 전체 텍스트를 하나로 합쳐 spec 매핑
    all_user_text = ' '.join(t['text'] for t in state.turns if t['role'] == 'user')
    full_context = '\n'.join(
        f'{"사용자" if t["role"] == "user" else "팀장"}: {t["text"][:150]}'
        for t in state.turns
    )

    await office._emit('teamlead', '잠시만요, 내용을 정리하고 있어요.', 'response')

    spec_id, job_input, conf = await map_to_job_spec(all_user_text, full_context)
    if not spec_id or conf < 0.5:
        spec_id = 'research'
        job_input = {'topic': all_user_text[:500]}

    # 대화에서 추가 필드 추출 후 병합
    extra = await _compress_to_job_input(state, spec_id)
    for k, v in extra.items():
        if v and str(v).strip() and not job_input.get(k, '').strip():
            job_input[k] = v

    state.proposed_spec_id = spec_id
    await office._handle_job(
        spec_id, job_input, state.user_input_original,
        attachments_text=state.attachments_text,
    )
