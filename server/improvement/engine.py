# 자가개선 엔진 — 모든 개선 모듈을 통합하는 파이프라인
from __future__ import annotations
from dataclasses import asdict
from typing import Any

from log_bus.event_bus import EventBus, LogEvent
from improvement.metrics import MetricsCollector, ProjectMetrics
from improvement.analyzer import PatternAnalyzer, ImprovementReport
from improvement.prompt_evolver import PromptEvolver
from improvement.qa_adapter import QAAdapter
from improvement.workflow_optimizer import WorkflowOptimizer


# 분석을 시작하기 위한 최소 프로젝트 수
MIN_PROJECTS_FOR_ANALYSIS = 3


class ImprovementEngine:
  '''자가개선 엔진 — 프로젝트 완료 시 자동으로 성과를 분석하고 시스템을 개선한다.'''

  def __init__(
    self,
    event_bus: EventBus,
    metrics: MetricsCollector | None = None,
    prompt_evolver: PromptEvolver | None = None,
    qa_adapter: QAAdapter | None = None,
    workflow_optimizer: WorkflowOptimizer | None = None,
  ):
    self.event_bus = event_bus
    self.metrics = metrics or MetricsCollector()
    self.analyzer = PatternAnalyzer(self.metrics)
    self.prompt_evolver = prompt_evolver or PromptEvolver()
    self.qa_adapter = qa_adapter or QAAdapter(metrics=self.metrics)
    self.workflow_optimizer = workflow_optimizer or WorkflowOptimizer(metrics=self.metrics)

  async def on_project_complete(self, project_metrics: ProjectMetrics) -> ImprovementReport | None:
    '''프로젝트 완료 시 호출 — 자가개선 파이프라인을 실행한다.

    Returns:
      개선 보고서 (충분한 데이터가 없으면 None)
    '''
    # 1. 메트릭 저장
    self.metrics.save(project_metrics)

    # 2. 충분한 데이터가 모이면 분석 실행
    if self.metrics.total_projects() < MIN_PROJECTS_FOR_ANALYSIS:
      return None

    report = self.analyzer.analyze()

    # 3. 개선 적용
    new_rules: dict[str, list[str]] = {}
    if report.has_prompt_improvements:
      new_rules = await self.prompt_evolver.evolve(report)
    if report.has_qa_improvements:
      self.qa_adapter.update(report)
    if report.has_workflow_improvements:
      self.workflow_optimizer.update(report)

    # 4. 개선 내역을 채팅에 보고
    await self._report_improvements(report, new_rules)

    return report

  async def _report_improvements(self, report: ImprovementReport, new_rules: dict[str, list[str]]) -> None:
    '''팀장이 자가개선 내역을 사용자에게 보고한다.'''
    lines = [f'📊 **자가개선 분석 완료** (최근 {report.total_projects}개 프로젝트 기준)\n']

    # 에이전트 프로파일 요약
    for profile in report.agent_profiles:
      if profile.total_phases == 0:
        continue
      emoji = '✅' if profile.qa_pass_rate >= 0.8 else '⚠️' if profile.qa_pass_rate >= 0.6 else '❌'
      lines.append(f'{emoji} **{profile.agent_name}**: QA 합격률 {profile.qa_pass_rate*100:.0f}%, 평균 보완 {profile.avg_revisions:.1f}회')

    # 병목 보고
    if report.bottlenecks:
      lines.append('\n**🔍 병목 단계:**')
      for b in report.bottlenecks[:3]:
        lines.append(f'- {b.phase_name} ({b.agent_name}): 평균 대비 {b.ratio:.1f}배 소요, 보완율 {b.revision_rate*100:.0f}%')

    # 새 규칙 보고
    if new_rules:
      lines.append('\n**📝 새로 추가된 품질 규칙:**')
      for agent, rules in new_rules.items():
        for rule in rules:
          lines.append(f'- [{agent}] {rule}')

    # 반복 실패 패턴
    if report.recurring_failures:
      lines.append('\n**⚠️ 반복 실패 패턴:**')
      for p in report.recurring_failures[:3]:
        lines.append(f'- {p.description}')

    await self.event_bus.publish(LogEvent(
      agent_id='teamlead',
      event_type='response',
      message='\n'.join(lines),
      data={'type': 'improvement_report'},
    ))

  def get_report(self) -> dict[str, Any]:
    '''최신 개선 보고서를 dict로 반환한다 (API용).'''
    if self.metrics.total_projects() < 1:
      return {'total_projects': 0, 'message': '아직 분석할 데이터가 없습니다.'}

    report = self.analyzer.analyze()
    return {
      'total_projects': report.total_projects,
      'agent_profiles': [asdict(p) for p in report.agent_profiles],
      'bottlenecks': [asdict(b) for b in report.bottlenecks],
      'recurring_failures': [asdict(f) for f in report.recurring_failures],
      'has_prompt_improvements': report.has_prompt_improvements,
      'has_qa_improvements': report.has_qa_improvements,
      'has_workflow_improvements': report.has_workflow_improvements,
    }

  def get_metrics_summary(self) -> list[dict]:
    '''프로젝트별 성과 메트릭 요약을 반환한다 (API용).'''
    projects = self.metrics.load_all()
    return [
      {
        'task_id': p.task_id,
        'project_type': p.project_type,
        'instruction': p.instruction[:100],
        'total_duration': p.total_duration,
        'phase_count': len(p.phases),
        'final_review_passed': p.final_review_passed,
        'final_review_rounds': p.final_review_rounds,
        'started_at': p.started_at,
        'finished_at': p.finished_at,
      }
      for p in projects
    ]
