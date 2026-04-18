"""Job 스텝 system prompt 3-레이어 합성기."""
from __future__ import annotations
from pathlib import Path
import yaml

_DATA = Path(__file__).parent.parent.parent / 'data'
PERSONAS_DIR = _DATA / 'personas'
SKILLS_DIR   = _DATA / 'skills'


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
        sections.append('\n'.join(block))
    return '\n\n'.join(sections)


def compose_system_prompt(step) -> str:
    """페르소나 + 스킬 + 기존 system_prompt 합성."""
    parts = []
    persona_block = load_persona(step.persona)
    if persona_block:
        parts.append(persona_block)
    skills_block = load_skills(step.skills)
    if skills_block:
        parts.append(skills_block)
    if step.tools:
        parts.append('## 이 스텝에서 사용 가능한 툴\n' + ', '.join(step.tools))
    # 기존 YAML system_prompt는 하위호환으로 마지막에 append
    if getattr(step, 'system_prompt', ''):
        parts.append(step.system_prompt)
    return '\n\n'.join(p for p in parts if p)
