"""Haiku 기반 Step 동적 설정기 — persona/skills/tools를 실행 시점에 자동 선택한다."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DATA = Path(__file__).parent.parent.parent / 'data'
_PERSONAS_DIR = _DATA / 'personas'
_SKILLS_DIR = _DATA / 'skills'

# 툴 목록은 tool_registry에서 가져오므로 캐시만 보관
_persona_catalog: list[dict] | None = None
_skill_catalog: list[dict] | None = None


def invalidate_catalog_cache() -> None:
    """persona/skill 파일 변경 후 캐시를 초기화한다."""
    global _persona_catalog, _skill_catalog
    _persona_catalog = None
    _skill_catalog = None


def _load_persona_catalog() -> list[dict]:
    global _persona_catalog
    if _persona_catalog is not None:
        return _persona_catalog
    items = []
    for p in sorted(_PERSONAS_DIR.glob('*.yaml')):
        try:
            d = yaml.safe_load(p.read_text('utf-8'))
            items.append({
                'id': p.stem,
                'name': d.get('display_name', p.stem),
                'description': d.get('description', ''),
                'category': d.get('category', ''),
            })
        except Exception:
            pass
    _persona_catalog = items
    return items


def _load_skill_catalog() -> list[dict]:
    global _skill_catalog
    if _skill_catalog is not None:
        return _skill_catalog
    items = []
    for s in sorted(_SKILLS_DIR.glob('*.yaml')):
        try:
            d = yaml.safe_load(s.read_text('utf-8'))
            items.append({
                'id': s.stem,
                'name': d.get('display_name', s.stem),
                'description': d.get('description', ''),
                'category': d.get('category', ''),
            })
        except Exception:
            pass
    _skill_catalog = items
    return items


def _load_tool_catalog() -> list[dict]:
    try:
        from jobs.tool_registry import list_tools
        tools = list_tools()
        return [{'id': t['id'], 'name': t['name'], 'description': t.get('description', '')}
                for t in tools]
    except Exception:
        return []


def _build_selection_prompt(step, context: dict[str, str]) -> str:
    personas = _load_persona_catalog()
    skills = _load_skill_catalog()
    tools = _load_tool_catalog()

    # context에서 유용한 힌트 추출 (과도한 토큰 방지)
    ctx_hints = {k: v[:200] for k, v in context.items()
                 if not k.startswith('_') and v and len(k) < 40}

    persona_list = '\n'.join(
        f'- {p["id"]}: {p["name"]} — {p["description"][:80]}' for p in personas
    )
    skill_list = '\n'.join(
        f'- {s["id"]}: {s["name"]} — {s["description"][:80]}' for s in skills
    )
    tool_list = '\n'.join(
        f'- {t["id"]}: {t["name"]} — {t["description"][:80]}' for t in tools
    )

    # 힌트 정보 (spec에서 이미 지정된 것)
    hints = {}
    if step.persona:
        hints['persona_hint'] = step.persona
    if step.skills:
        hints['skills_hint'] = step.skills
    if step.tools:
        hints['tools_hint'] = step.tools

    hint_block = ''
    if hints:
        hint_block = f'\n[힌트 — spec에 미리 지정된 값, 적절하면 그대로 사용]\n{json.dumps(hints, ensure_ascii=False)}\n'
    if context.get('output_format'):
        hint_block += f'\n[출력 형식 요청] {context["output_format"]} → deliver 스텝이면 반드시 이 형식에 맞는 툴 선택:\n  pdf → pdf_generate | docx → docx_generate | pptx → pptx_generate | notion → notion_write | slack → slack_post | drive → google_drive_upload\n'

    return f"""당신은 AI 에이전트 오케스트레이터입니다.
아래 Step의 목적에 가장 적합한 페르소나 1개, 스킬 1-3개, 툴 0-3개를 선택하세요.

[Step 정보]
id: {step.id}
agent: {step.agent}
tier: {step.tier}
prompt 요약: {step.prompt_template[:300]}
{hint_block}
[Job 컨텍스트]
{json.dumps(ctx_hints, ensure_ascii=False, indent=2)[:500]}

[선택 가능한 페르소나]
{persona_list}

[선택 가능한 스킬]
{skill_list}

[선택 가능한 툴]
{tool_list}

선택 기준:
- 페르소나: step의 주 역할(작성/검토/연구/설계/개발/QA)과 도메인에 맞는 1개
- 스킬: prompt에서 요구하는 사고방식과 출력 형식에 필요한 것만
- 툴: prompt에서 실제로 호출할 가능성이 높은 것만 (없어도 됨)
- 힌트가 있고 적절하면 그대로 사용

다음 JSON만 출력하세요 (설명 없이):
{{"persona": "persona_id", "skills": ["skill_id1"], "tools": ["tool_id1"]}}"""


async def configure_step(step, context: dict[str, str]):
    """step의 persona/skills/tools가 비어있으면 Haiku로 자동 선택해 step을 갱신한다.

    spec에 모두 지정돼 있으면 Haiku 호출을 건너뛴다 (비용 0).
    """
    # persona와 skills 모두 spec에 지정돼 있으면 Haiku 호출 불필요
    if step.persona and step.skills:
        return step

    # Haiku 호출
    try:
        from runners import model_router
        prompt = _build_selection_prompt(step, context)
        raw, _ = await model_router.run(
            tier='nano',
            prompt=prompt,
            system='JSON만 출력하세요. 절대 설명을 추가하지 마세요.',
            agent_id=f'step_configurator:{step.id}',
            timeout=30.0,
        )
        # JSON 추출
        raw = raw.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        config = json.loads(raw.strip())
    except Exception as e:
        logger.warning('[step_configurator] Haiku 선택 실패(%s) — spec 값 유지: %s', step.id, e)
        return step

    # spec 힌트 우선: 이미 지정된 필드는 덮어쓰지 않음
    import dataclasses
    updates = {}
    if not step.persona and config.get('persona'):
        updates['persona'] = config['persona']
    if not step.skills and config.get('skills'):
        updates['skills'] = config['skills']
    if not step.tools and config.get('tools'):
        updates['tools'] = config['tools']

    if updates:
        step = dataclasses.replace(step, **updates)
        logger.debug('[step_configurator] %s → %s', step.id, updates)

    return step


async def suggest_alternative_tools(
    step,
    failed_tools: list[str],
    reason: str = '',
) -> list[str]:
    """실패한 툴을 대체할 툴 목록을 Haiku에게 요청한다.

    반환값이 비면 재시도 스킵. spec 고정 툴은 유지하지 않음 — step.tools 자체를 교체한다.
    """
    if not failed_tools:
        return []
    try:
        from runners import model_router
    except Exception:
        return []

    tools = _load_tool_catalog()
    tool_list = '\n'.join(
        f'- {t["id"]}: {t["name"]} — {t["description"][:80]}' for t in tools
    )

    prompt = (
        f'아래 Step에서 툴 {failed_tools} 이 실패했습니다.\n'
        f'실패 사유: {reason[:200] or "(미상)"}\n\n'
        f'[Step 목적]\n{step.prompt_template[:300]}\n\n'
        f'[선택 가능한 툴]\n{tool_list}\n\n'
        f'실패한 툴을 대체해 동일한 목적을 달성할 수 있는 툴 0-3개를 선택하세요.\n'
        f'대체 가능한 게 없으면 빈 배열을 반환하세요.\n'
        f'JSON만 출력: {{"tools":["tool_id1"]}}'
    )

    try:
        raw, _ = await model_router.run(
            tier='nano', prompt=prompt,
            system='JSON만 출력하세요. 절대 설명을 추가하지 마세요.',
            agent_id=f'step_retry:{step.id}', timeout=20.0,
        )
        raw = raw.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        config = json.loads(raw.strip())
    except Exception as e:
        logger.debug('[step_retry] 대체 툴 선택 실패(%s): %s', step.id, e)
        return []

    alts = config.get('tools') or []
    # 실패한 툴은 제외
    alts = [t for t in alts if t not in failed_tools]
    return alts[:3]
