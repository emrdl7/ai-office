"""Job intent 핸들러 — Office.receive()에서 분리한 JOB 처리 로직.

Office가 커지면서 JOB 관련 코드가 섞였습니다 (4-1).
이 모듈로 분리해 의존성을 명확히 합니다:
  office.py → job_handler.dispatch() → jobs.runner.submit()
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from orchestration.office import Office

from orchestration.intent import IntentResult, IntentType

logger = logging.getLogger(__name__)


async def dispatch(
    office: 'Office',
    intent_result: IntentResult,
    user_input: str,
) -> dict[str, Any]:
    """JOB intent를 처리한다.

    confidence 확인 → spec 조회 → _handle_job() 호출 또는 clarification.
    """
    from orchestration.state import OfficeState

    # 신뢰도 낮음 → spec 목록 제시하며 확인 (2-4)
    if intent_result.confidence < 0.6 or not intent_result.job_spec_id:
        try:
            from jobs.registry import all_specs as _all_specs
            spec_list = '\n'.join(
                f'- **{s.id}**: {s.title} — {s.description}' for s in _all_specs()
            )
        except Exception:
            spec_list = ''
        clarify_msg = (
            '어떤 Job 파이프라인을 실행할까요?\n\n'
            f'{spec_list}\n\n'
            'Job Board에서 직접 선택하거나, 구체적인 Job 이름을 알려주세요.'
        )
        await office._emit('teamlead', clarify_msg, 'response')
        office._state = OfficeState.COMPLETED
        office._active_agent = ''
        return {'state': office._state.value, 'response': '', 'artifacts': []}

    return await office._handle_job(
        intent_result.job_spec_id,
        intent_result.job_input,
        user_input,
    )
