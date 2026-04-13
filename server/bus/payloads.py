# 에이전트 간 payload 스키마 (ORCH-03)
from pydantic import BaseModel, Field
from typing import Literal, Optional
import uuid


class TaskRequestPayload(BaseModel):
  '''태스크 요청 payload — 기획자가 각 에이전트에게 작업을 지시할 때 사용'''
  task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # UUID 자동 생성
  description: str  # 수행할 작업 설명
  requirements: str  # 원본 요구사항 — QA 독립 참조용 (D-08)
  acceptance_criteria: list[str] = []  # 완료 기준 목록 — 각 항목은 검증 가능한 조건
  depends_on: list[str] = []  # DAG 의존 task_id 목록
  assigned_to: str  # 실행 에이전트 id


class TaskResultPayload(BaseModel):
  '''태스크 결과 payload — 에이전트가 작업 완료 후 결과를 반환할 때 사용'''
  task_id: str  # 원본 요청 task_id
  status: Literal['success', 'fail']  # 작업 성공 여부
  artifact_paths: list[str] = []  # workspace 내 생성된 파일의 상대 경로 목록
  summary: str  # 작업 요약 (기획자 추적용 — WKFL-04)
  failure_reason: Optional[str] = None  # QA 반려 시 구체적 이유 (D-09)


class StatusUpdatePayload(BaseModel):
  '''상태 업데이트 payload — 에이전트가 작업 진행 상황을 브로드캐스트할 때 사용'''
  task_id: str  # 대상 task_id
  state: str  # WorkflowState 열거값 (loop.py에서 정의 예정)
  agent_id: str  # 상태를 보고하는 에이전트 id
  note: str = ''  # 추가 메모 (선택적)
