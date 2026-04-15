# 팀 공유 메모리 — 에이전트 간 공유 기억, 교훈, 프로젝트 히스토리
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class SharedLesson:
    '''팀 전체가 공유하는 교훈/학습 레코드'''
    id: str
    project_title: str
    agent_name: str       # 교훈을 발견한 에이전트
    lesson: str           # 교훈 내용
    category: str         # 'success_pattern' | 'failure_pattern' | 'process_improvement' | 'collaboration'
    timestamp: str


DYNAMIC_TYPES = (
    # 피어 리뷰 (agent_interactions._peer_review)
    'peer_concern',          # 리뷰어가 우려 표명 ([CONCERN])
    'peer_approved',         # 리뷰어가 무난/긍정 평가
    # 자문 (agent_interactions._consult_peers)
    'consulted',             # A가 B에게 자문 요청 → B 응답
    # 다짐/약속 (suggestion_filer._file_commitment_suggestion)
    'committed_to_request',  # A가 B의 요청에 "~하겠습니다" 응답
    # 멘션 라우팅 (agent_interactions._route_agent_mentions)
    'needs_clarification',   # A가 작업 중 B에게 @멘션으로 질문
    # 미사용 예약 — 향후 분류용
    'prefers_detail', 'works_well', 'complements',
)


@dataclass
class TeamDynamic:
    '''에이전트 간 협업 관계 기록.

    dynamic_type은 위 DYNAMIC_TYPES 어휘를 사용한다 (자유 문자열 허용하지만
    가능하면 표준 어휘로 통일 — 통계 집계 일관성 확보).
    '''
    from_agent: str
    to_agent: str
    dynamic_type: str
    description: str
    timestamp: str


@dataclass
class ProjectSummary:
    '''과거 프로젝트 요약'''
    project_id: str
    title: str
    project_type: str
    outcome: str          # 'success' | 'partial' | 'failed'
    key_decisions: list[str]
    duration_seconds: float
    timestamp: str


class TeamMemory:
    '''팀 전체 공유 메모리 — 프로젝트를 넘어 축적되는 팀 경험.

    저장 위치: data/memory/team_shared.json
    '''

    MAX_LESSONS = 30
    MAX_DYNAMICS = 200  # 동일 (from,to,type) 누적 허용 → 임계치 기반 집계/경고 가능
    MAX_PROJECTS = 15

    def __init__(self, memory_root: str | Path | None = None):
        if memory_root is None:
            from core import paths
            memory_root = paths.MEMORY_ROOT
        self._file = Path(memory_root) / 'team_shared.json'
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def add_lesson(self, lesson: SharedLesson) -> None:
        '''교훈을 팀 메모리에 추가한다.'''
        data = self._load()
        lessons = data.setdefault('lessons', [])
        lessons.append(asdict(lesson))
        # 오래된 교훈 제거
        if len(lessons) > self.MAX_LESSONS:
            data['lessons'] = lessons[-self.MAX_LESSONS:]
        self._save(data)

    def add_dynamic(self, dynamic: TeamDynamic) -> None:
        '''에이전트 간 협업 관계를 기록한다.

        동일 (from, to, type) 튜플도 append — 반복 카운트로 임계치 기반 경고에 사용.
        MAX_DYNAMICS 초과 시 오래된 기록부터 drop.
        '''
        data = self._load()
        dynamics = data.setdefault('dynamics', [])
        dynamics.append(asdict(dynamic))
        if len(dynamics) > self.MAX_DYNAMICS:
            dynamics = dynamics[-self.MAX_DYNAMICS:]
        data['dynamics'] = dynamics
        self._save(data)

    def add_project_summary(self, summary: ProjectSummary) -> None:
        '''프로젝트 요약을 저장한다.'''
        data = self._load()
        projects = data.setdefault('projects', [])
        projects.append(asdict(summary))
        if len(projects) > self.MAX_PROJECTS:
            data['projects'] = projects[-self.MAX_PROJECTS:]
        self._save(data)

    def get_lessons_for_agent(self, agent_name: str, limit: int = 5) -> list[SharedLesson]:
        '''특정 에이전트에게 관련된 교훈을 반환한다.'''
        data = self._load()
        lessons = data.get('lessons', [])
        # 해당 에이전트가 발견했거나 전체 공유 교훈
        relevant = [
            l for l in lessons
            if l.get('agent_name') == agent_name or l.get('category') in ('process_improvement', 'collaboration')
        ]
        # 최신순
        relevant.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return [SharedLesson(**l) for l in relevant[:limit]]

    def get_all_lessons(self, limit: int = 10) -> list[SharedLesson]:
        '''전체 교훈을 최신순으로 반환한다.'''
        data = self._load()
        lessons = data.get('lessons', [])
        lessons.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return [SharedLesson(**l) for l in lessons[:limit]]

    def get_dynamics_for(self, agent_name: str) -> list[TeamDynamic]:
        '''특정 에이전트 관련 팀 다이나믹을 반환한다.'''
        data = self._load()
        dynamics = data.get('dynamics', [])
        relevant = [
            d for d in dynamics
            if d.get('from_agent') == agent_name or d.get('to_agent') == agent_name
        ]
        return [TeamDynamic(**d) for d in relevant]

    def get_recent_projects(self, limit: int = 5) -> list[ProjectSummary]:
        '''최근 프로젝트 요약을 반환한다.'''
        data = self._load()
        projects = data.get('projects', [])
        projects.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return [ProjectSummary(**p) for p in projects[:limit]]

    def get_team_context_text(self, agent_name: str) -> str:
        '''에이전트 시스템 프롬프트에 주입할 팀 메모리 텍스트를 생성한다.'''
        parts = []

        # 1. 관련 교훈
        lessons = self.get_lessons_for_agent(agent_name, limit=3)
        if lessons:
            lesson_lines = [f'- [{l.category}] {l.lesson[:100]}' for l in lessons]
            parts.append('## 팀이 배운 교훈\n' + '\n'.join(lesson_lines))

        # 2. 협업 관계 — 최신순 최대 5개, 타입까지 표시
        dynamics = self.get_dynamics_for(agent_name)
        if dynamics:
            dynamics_sorted = sorted(dynamics, key=lambda d: d.timestamp, reverse=True)[:5]
            dyn_lines = [
                f'- [{d.dynamic_type}] {d.from_agent}→{d.to_agent}: {d.description[:80]}'
                for d in dynamics_sorted
            ]
            parts.append('## 팀 협업 패턴\n' + '\n'.join(dyn_lines))

        # 3. 최근 프로젝트
        projects = self.get_recent_projects(limit=2)
        if projects:
            proj_lines = [f'- {p.title} ({p.outcome}): {", ".join(p.key_decisions[:2])}' for p in projects]
            parts.append('## 최근 프로젝트 경험\n' + '\n'.join(proj_lines))

        return '\n\n'.join(parts) if parts else ''

    def _load(self) -> dict[str, Any]:
        if not self._file.exists():
            return {}
        try:
            with open(self._file, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self._file.with_suffix('.json.tmp')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.rename(tmp, self._file)
        except Exception:
            logger.warning("팀 메모리 저장 실패", exc_info=True)
            tmp.unlink(missing_ok=True)
