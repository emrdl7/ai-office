# 패턴 분석기 — 누적 성과 데이터에서 개선 포인트를 자동 도출한다
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from improvement.metrics import MetricsCollector, ProjectMetrics, PhaseMetrics


@dataclass
class AgentProfile:
  '''에이전트별 강점/약점 프로파일.'''
  agent_name: str
  total_phases: int = 0
  qa_pass_rate: float = 0.0
  avg_revisions: float = 0.0
  avg_duration: float = 0.0
  top_failure_groups: list[str] = field(default_factory=list)  # 자주 실패하는 그룹
  strengths: list[str] = field(default_factory=list)
  weaknesses: list[str] = field(default_factory=list)


@dataclass
class Bottleneck:
  '''워크플로우 병목 정보.'''
  phase_name: str
  agent_name: str
  avg_duration: float
  overall_avg: float
  ratio: float  # avg_duration / overall_avg
  revision_rate: float


@dataclass
class RecurringPattern:
  '''반복 실패 패턴.'''
  agent_name: str
  group: str
  failure_count: int
  description: str


@dataclass
class ImprovementReport:
  '''자가개선 보고서.'''
  total_projects: int = 0
  agent_profiles: list[AgentProfile] = field(default_factory=list)
  bottlenecks: list[Bottleneck] = field(default_factory=list)
  recurring_failures: list[RecurringPattern] = field(default_factory=list)

  @property
  def has_prompt_improvements(self) -> bool:
    return len(self.recurring_failures) > 0

  @property
  def has_qa_improvements(self) -> bool:
    return any(p.qa_pass_rate < 0.7 for p in self.agent_profiles if p.total_phases >= 3)

  @property
  def has_workflow_improvements(self) -> bool:
    return len(self.bottlenecks) > 0


class PatternAnalyzer:
  '''누적 성과 데이터에서 개선 포인트를 자동 도출한다.'''

  def __init__(self, metrics: MetricsCollector):
    self._metrics = metrics

  def analyze(self) -> ImprovementReport:
    '''전체 성과 데이터를 분석하여 개선 보고서를 생성한다.'''
    projects = self._metrics.load_all()
    if not projects:
      return ImprovementReport()

    report = ImprovementReport(total_projects=len(projects))

    # 에이전트별 프로파일
    agent_names = set()
    for p in projects:
      for phase in p.phases:
        agent_names.add(phase.agent_name)

    for agent_name in sorted(agent_names):
      report.agent_profiles.append(self.agent_profile(agent_name, projects))

    # 워크플로우 병목
    report.bottlenecks = self.workflow_bottlenecks(projects)

    # 반복 실패 패턴
    report.recurring_failures = self.recurring_failures(projects)

    return report

  def agent_profile(self, agent_name: str, projects: list[ProjectMetrics] | None = None) -> AgentProfile:
    '''에이전트별 강점/약점 프로파일.'''
    if projects is None:
      projects = self._metrics.load_all()

    phases: list[PhaseMetrics] = []
    for p in projects:
      for phase in p.phases:
        if phase.agent_name == agent_name:
          phases.append(phase)

    if not phases:
      return AgentProfile(agent_name=agent_name)

    total = len(phases)
    passed = sum(1 for p in phases if p.qa_passed)
    total_revisions = sum(p.revision_count for p in phases)
    durations = [p.duration_seconds for p in phases if p.duration_seconds > 0]
    avg_dur = sum(durations) / len(durations) if durations else 0

    # 실패 그룹 분석
    failure_groups = Counter(
      p.group for p in phases if not p.qa_passed and p.group
    )
    top_failures = [g for g, _ in failure_groups.most_common(3)]

    # 강점/약점 도출
    profile = AgentProfile(
      agent_name=agent_name,
      total_phases=total,
      qa_pass_rate=passed / total,
      avg_revisions=total_revisions / total,
      avg_duration=avg_dur,
      top_failure_groups=top_failures,
    )

    if profile.qa_pass_rate >= 0.8:
      profile.strengths.append('높은 QA 합격률')
    if profile.avg_revisions <= 0.3:
      profile.strengths.append('보완 요청 적음')
    if profile.qa_pass_rate < 0.6:
      profile.weaknesses.append('QA 합격률 낮음')
    if profile.avg_revisions > 1.0:
      profile.weaknesses.append('보완 반복 잦음')

    return profile

  def workflow_bottlenecks(self, projects: list[ProjectMetrics] | None = None) -> list[Bottleneck]:
    '''워크플로우 병목 식별 — 평균 대비 2배 이상 소요되는 단계.'''
    if projects is None:
      projects = self._metrics.load_all()

    # 단계별 소요시간 집계
    phase_durations: dict[str, list[float]] = {}
    phase_agents: dict[str, str] = {}
    phase_revisions: dict[str, list[int]] = {}

    for p in projects:
      for phase in p.phases:
        if phase.duration_seconds <= 0:
          continue
        phase_durations.setdefault(phase.phase_name, []).append(phase.duration_seconds)
        phase_agents[phase.phase_name] = phase.agent_name
        phase_revisions.setdefault(phase.phase_name, []).append(phase.revision_count)

    if not phase_durations:
      return []

    # 전체 평균 소요시간
    all_durations = [d for dlist in phase_durations.values() for d in dlist]
    overall_avg = sum(all_durations) / len(all_durations) if all_durations else 1

    bottlenecks = []
    for phase_name, durations in phase_durations.items():
      avg = sum(durations) / len(durations)
      ratio = avg / overall_avg if overall_avg else 0
      revisions = phase_revisions.get(phase_name, [])
      rev_rate = sum(1 for r in revisions if r > 0) / len(revisions) if revisions else 0

      if ratio >= 2.0 or rev_rate >= 0.5:
        bottlenecks.append(Bottleneck(
          phase_name=phase_name,
          agent_name=phase_agents.get(phase_name, ''),
          avg_duration=avg,
          overall_avg=overall_avg,
          ratio=ratio,
          revision_rate=rev_rate,
        ))

    return sorted(bottlenecks, key=lambda b: b.ratio, reverse=True)

  def recurring_failures(self, projects: list[ProjectMetrics] | None = None) -> list[RecurringPattern]:
    '''반복 실패 패턴 탐지 — 3회 이상 동일 에이전트+그룹에서 불합격.'''
    if projects is None:
      projects = self._metrics.load_all()

    # (agent, group) 별 실패 횟수
    failure_counts: Counter = Counter()
    for p in projects:
      for phase in p.phases:
        if not phase.qa_passed:
          key = (phase.agent_name, phase.group or phase.phase_name)
          failure_counts[key] += 1

    patterns = []
    for (agent, group), count in failure_counts.most_common():
      if count >= 3:
        patterns.append(RecurringPattern(
          agent_name=agent,
          group=group,
          failure_count=count,
          description=f'{agent}가 {group} 단계에서 {count}회 불합격',
        ))

    return patterns
