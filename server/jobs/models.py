"""Job 파이프라인 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GateSpec:
    id: str
    after_step: str
    prompt: str
    auto_advance_after: int | None = None  # 초 단위, None = 수동 필수


@dataclass
class StepSpec:
    id: str
    agent: str
    tier: str                              # nano/fast/standard/deep/research
    prompt_template: str                   # 프롬프트 텍스트 (j2 아닌 일반 문자열)
    tools: list[str] = field(default_factory=list)
    parallel: bool = False
    output_key: str = ''                   # 결과를 저장할 artifact 키


@dataclass
class JobSpec:
    id: str
    title: str
    description: str
    version: int
    steps: list[StepSpec]
    gates: list[GateSpec] = field(default_factory=list)
    input_fields: list[str] = field(default_factory=list)   # 전체 입력 필드 (UI 표시용)
    required_fields: list[str] = field(default_factory=list) # 필수 입력 필드 (검증용)


@dataclass
class StepRun:
    job_id: str
    step_id: str
    status: str                            # pending/running/done/failed/blocked
    started_at: str = ''
    finished_at: str = ''
    output: str = ''
    error: str = ''
    model_used: str = ''
    cost_usd: float = 0.0
    revised: int = 0                       # 수정 재실행 횟수
    revision_feedback: str = ''            # 마지막 수정 요청 피드백


@dataclass
class GateRun:
    job_id: str
    gate_id: str
    status: str                            # pending/approved/rejected/revised
    opened_at: str = field(default_factory=_now)
    decided_at: str = ''
    decision: str = ''
    feedback: str = ''


@dataclass
class JobRun:
    id: str
    spec_id: str
    title: str
    status: str                            # queued/running/waiting_gate/done/failed/cancelled
    input: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)  # key → file path or text
    created_at: str = field(default_factory=_now)
    started_at: str = ''
    finished_at: str = ''
    error: str = ''
    current_step: str = ''
