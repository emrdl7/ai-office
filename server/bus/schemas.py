# 에이전트 간 메시지 스키마 (D-02: 풍부한 필드, D-03: 3가지 타입 + 확장 가능)
from pydantic import BaseModel, Field
from typing import Literal, Optional, Any
from datetime import datetime
import uuid

MessageType = Literal['task_request', 'task_result', 'status_update']
AgentId = Literal['claude', 'planner', 'developer', 'designer', 'qa', 'orchestrator']
Priority = Literal['normal', 'high', 'urgent']
Status = Literal['pending', 'processing', 'done', 'failed']

class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    from_agent: AgentId = Field(alias='from')
    to_agent: AgentId | Literal['broadcast'] = Field(alias='to')
    payload: Any
    reply_to: Optional[str] = None
    priority: Priority = 'normal'
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    ack_at: Optional[datetime] = None
    status: Status = 'pending'

    model_config = {'populate_by_name': True}
