"""Job 스텝 system prompt 3-레이어 합성기."""
from __future__ import annotations
from pathlib import Path
import yaml

_DATA = Path(__file__).parent.parent.parent / 'data'
PERSONAS_DIR = _DATA / 'personas'
SKILLS_DIR   = _DATA / 'skills'


def _list_section(title: str, values: list[str] | None) -> str:
    if not values:
        return ''
    return title + '\n' + '\n'.join(f'- {v}' for v in values)


def load_persona(persona_id: str) -> str:
    if not persona_id:
        return ''
    p = PERSONAS_DIR / f'{persona_id}.yaml'
    if not p.exists():
        return ''
    d = yaml.safe_load(p.read_text('utf-8'))
    parts = [f"# 페르소나: {d.get('display_name', persona_id)}"]
    if d.get('identity'):
        parts.append(d['identity'].strip())
    if d.get('traits'):
        parts.append('## 성향\n' + '\n'.join(f'- {t}' for t in d['traits']))
    for title, key in (
        ('## 선택 기준', 'selection_criteria'),
        ('## 피해야 할 경우', 'avoid_when'),
        ('## 기본 산출물 계약', 'output_contract'),
        ('## 품질 기준', 'quality_rubric'),
    ):
        section = _list_section(title, d.get(key))
        if section:
            parts.append(section)
    if d.get('voice'):
        parts.append(f'어조: {d["voice"]}')
    return '\n'.join(parts)


def load_skills(skill_ids: list[str]) -> str:
    if not skill_ids:
        return ''
    sections = []
    for sid in skill_ids:
        s = SKILLS_DIR / f'{sid}.yaml'
        if not s.exists():
            continue
        d = yaml.safe_load(s.read_text('utf-8'))
        block = [f"## 스킬: {d.get('display_name', sid)}"]
        if d.get('thinking_frame'):
            block.append(d['thinking_frame'].strip())
        if d.get('output_checklist'):
            block.append('### 출력 체크리스트\n' + '\n'.join(f'- {c}' for c in d['output_checklist']))
        for title, key in (
            ('### 입력 조건', 'input_conditions'),
            ('### 출력 템플릿', 'output_template'),
            ('### 품질 기준', 'quality_rubric'),
        ):
            section = _list_section(title, d.get(key))
            if section:
                block.append(section)
        sections.append('\n'.join(block))
    return '\n\n'.join(sections)


def load_tool_contracts(tool_ids: list[str]) -> str:
    if not tool_ids:
        return ''
    from jobs.tool_registry import list_tools

    by_id = {tool['id']: tool for tool in list_tools()}
    sections = []
    for tool_id in tool_ids:
        tool = by_id.get(tool_id)
        if not tool:
            sections.append(
                f'### {tool_id}\n'
                '- 상태: 등록되지 않은 도구\n'
                '- 실패 정책: 이 도구를 사용할 수 있다고 가정하지 말고 대체 경로를 제시하세요.'
            )
            continue
        inputs = ', '.join(tool.get('input_contract') or []) or '필수 입력 없음'
        sections.append(
            f'### {tool["name"]} ({tool_id})\n'
            f'- maturity: {tool.get("maturity", "optional")}\n'
            f'- 필수 입력: {inputs}\n'
            f'- 산출: {tool.get("output_contract", "")}\n'
            f'- 실패 정책: {tool.get("failure_policy", "")}\n'
            f'- 복구 힌트: {tool.get("recovery_hint", "")}'
        )
    return '## 툴 사용 계약\n' + '\n'.join(sections)


def compose_system_prompt(step) -> str:
    """페르소나 + 스킬 + 기존 system_prompt 합성."""
    parts = []
    persona_block = load_persona(step.persona)
    if persona_block:
        parts.append(persona_block)
    skills_block = load_skills(step.skills)
    if skills_block:
        parts.append(skills_block)
    tool_contracts = load_tool_contracts(step.tools)
    if tool_contracts:
        parts.append(tool_contracts)
    # 기존 YAML system_prompt는 하위호환으로 마지막에 append
    if getattr(step, 'system_prompt', ''):
        parts.append(step.system_prompt)
    return '\n\n'.join(p for p in parts if p)
