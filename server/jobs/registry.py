"""JobSpec YAML 로더 — server/jobs/specs/*.yaml 에서 Job 타입을 로드한다."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jobs.models import JobSpec, StepSpec, GateSpec

logger = logging.getLogger(__name__)

_SPECS_DIR = Path(__file__).parent / 'specs'
_registry: dict[str, JobSpec] = {}


def load_all() -> dict[str, JobSpec]:
    """specs/ 디렉토리의 모든 YAML을 로드해 레지스트리를 채운다."""
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        logger.error('PyYAML이 없습니다. pip install pyyaml')
        return {}

    _registry.clear()
    for path in sorted(_SPECS_DIR.glob('*.yaml')):
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            spec = _parse(data)
            _registry[spec.id] = spec
            logger.info('Job spec 로드: %s (%d steps)', spec.id, len(spec.steps))
        except Exception:
            logger.exception('Job spec 로드 실패: %s', path)
    return _registry


def get(spec_id: str) -> JobSpec | None:
    if not _registry:
        load_all()
    return _registry.get(spec_id)


def all_specs() -> list[JobSpec]:
    if not _registry:
        load_all()
    return list(_registry.values())


def _parse(data: dict[str, Any]) -> JobSpec:
    steps = [
        StepSpec(
            id=s['id'],
            agent=s.get('agent', ''),
            tier=s['tier'],
            prompt_template=s.get('prompt', ''),
            tools=s.get('tools', []),
            parallel=s.get('parallel', False),
            output_key=s.get('output_key', s['id']),
            revision_prompt_template=s.get('revision_prompt', ''),
        )
        for s in data.get('steps', [])
    ]
    gates = [
        GateSpec(
            id=g['id'],
            after_step=g['after_step'],
            prompt=g.get('prompt', ''),
            auto_advance_after=g.get('auto_advance_after'),
        )
        for g in data.get('gates', [])
    ]
    input_fields = data.get('input_fields', [])
    # required_fields 미지정 시 input_fields 전체를 필수로 (하위 호환)
    required_fields = data.get('required_fields', input_fields)
    return JobSpec(
        id=data['id'],
        title=data['title'],
        description=data.get('description', ''),
        version=data.get('version', 1),
        steps=steps,
        gates=gates,
        input_fields=input_fields,
        required_fields=required_fields,
        depends_on=data.get('depends_on', []),
    )
