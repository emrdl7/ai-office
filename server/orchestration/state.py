from __future__ import annotations

from enum import Enum


class OfficeState(str, Enum):
  '''사무실 상태'''
  IDLE = 'idle'
  TEAMLEAD_THINKING = 'teamlead_thinking'
  MEETING = 'meeting'
  WORKING = 'working'
  QA_REVIEW = 'qa_review'
  TEAMLEAD_REVIEW = 'teamlead_review'
  REVISION = 'revision'
  COMPLETED = 'completed'
  ESCALATED = 'escalated'
