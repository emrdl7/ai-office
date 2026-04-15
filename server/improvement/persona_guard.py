# 누적 규칙 ↔ 페르소나 충돌 감사 — P5-2
#
# 실행 주기: teamlead batch review 끝에 1회 (주 1회 수준).
# 각 agent별로:
#   1. PromptEvolver 활성 규칙 + agents/{name}.md 성격/판단력/대화 스타일 로드
#   2. Claude Haiku 1회 — 충돌 쌍을 JSON으로 출력
#   3. 충돌 규칙 active=False 비활성화 + evidence에 사유 기록
#   4. teamlead에게 system_notice
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'
# 페르소나 감사 대상 에이전트 (teamlead 제외 — 팀장은 역할 특성상 규칙이 적음)
GUARD_AGENTS = ['designer', 'developer', 'planner', 'qa']
# 감사할 페르소나 섹션
PERSONA_SECTIONS = ['성격', '판단력', '대화 스타일']


def _load_persona_text(agent_name: str) -> str:
    '''agents/{name}.md에서 성격/판단력/대화 스타일 섹션만 추출.'''
    path = AGENTS_DIR / f'{agent_name}.md'
    if not path.exists():
        return ''
    text = path.read_text(encoding='utf-8')
    out: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
        elif current in PERSONA_SECTIONS:
            out.append(line)
    return '\n'.join(out).strip()


async def run_persona_guard(office: Any | None = None) -> dict[str, list[dict]]:
    '''모든 GUARD_AGENTS의 누적 규칙과 페르소나 충돌을 감사한다.

    반환: {agent_name: [{rule_id, persona_clause, reason}, ...]}
    '''
    from improvement.prompt_evolver import PromptEvolver
    from runners.claude_runner import run_claude_isolated

    evolver = PromptEvolver()
    summary: dict[str, list[dict]] = {}

    for agent_name in GUARD_AGENTS:
        rules = evolver.load_rules(agent_name)
        active = [r for r in rules if r.active]
        if not active:
            logger.debug('persona_guard skip %s: 활성 규칙 없음', agent_name)
            continue

        persona_text = _load_persona_text(agent_name)
        if not persona_text:
            logger.debug('persona_guard skip %s: 페르소나 텍스트 없음', agent_name)
            continue

        rules_text = '\n'.join(
            f'[{r.id}] {r.rule} (근거: {r.evidence[:80]})' for r in active
        )

        prompt = (
            f'다음은 AI 에이전트 "{agent_name}"의 페르소나 선언입니다:\n\n'
            f'{persona_text}\n\n'
            f'다음은 이 에이전트에 누적된 학습 규칙 {len(active)}개입니다:\n\n'
            f'{rules_text}\n\n'
            f'페르소나 선언과 모순되는 규칙 쌍을 찾아 JSON으로 출력하세요.\n'
            f'모순이 없으면 conflicts를 빈 배열로 출력하세요.\n\n'
            f'JSON만 출력:\n'
            f'{{"conflicts":[{{"rule_id":"...","persona_clause":"...","reason":"1문장"}}]}}'
        )

        try:
            raw = await run_claude_isolated(prompt, model='claude-haiku-4-5-20251001', timeout=30.0)
            m = re.search(r'\{[\s\S]*\}', raw)
            if not m:
                logger.warning('persona_guard LLM 파싱 실패: %s', agent_name)
                continue
            result = json.loads(m.group())
            conflicts: list[dict] = result.get('conflicts') or []
        except Exception as e:
            logger.warning('persona_guard LLM 실패: %s | %s', agent_name, e)
            continue

        if not conflicts:
            logger.info('persona_guard %s: 충돌 없음', agent_name)
            summary[agent_name] = []
            continue

        # 충돌 규칙 비활성화
        deactivated: list[str] = []
        for conflict in conflicts:
            rule_id = (conflict.get('rule_id') or '').strip()
            reason = (conflict.get('reason') or '').strip()
            for rule in active:
                if rule.id == rule_id:
                    rule.active = False
                    rule.evidence += f' | persona_guard deactivated: {reason}'
                    deactivated.append(rule_id)
                    break

        if deactivated:
            evolver.save_rules(agent_name, rules)
            logger.info('persona_guard %s: %d개 규칙 비활성화 — %s',
                       agent_name, len(deactivated), deactivated)

        summary[agent_name] = conflicts

        # teamlead에게 감사 로그 공개
        if office is not None:
            from log_bus.event_bus import LogEvent
            from config.team import display_name
            deact_txt = f'{len(deactivated)}건 비활성화' if deactivated else '자동 조치 없음'
            await office.event_bus.publish(LogEvent(
                agent_id='system',
                event_type='system_notice',
                message=(
                    f'🔍 페르소나 감사 — {display_name(agent_name)}: '
                    f'충돌 {len(conflicts)}건 발견, {deact_txt}.\n'
                    + '\n'.join(
                        f'  ✗ [{c.get("rule_id","")}] {c.get("reason","")}' for c in conflicts[:3]
                    )
                ),
            ))

    return summary


async def maybe_run_persona_guard(office: Any) -> None:
    '''teamlead batch review 끝에 호출. 실패해도 배치가 중단되지 않음.'''
    try:
        summary = await run_persona_guard(office)
        total_conflicts = sum(len(v) for v in summary.values())
        if total_conflicts == 0:
            logger.info('persona_guard 완료: 모든 에이전트 충돌 없음')
    except Exception:
        logger.warning('persona_guard 실행 실패', exc_info=True)
