# 자가개선 프레임워크 단위 테스트
import asyncio
import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from improvement.metrics import MetricsCollector, ProjectMetrics, PhaseMetrics
from improvement.analyzer import PatternAnalyzer, ImprovementReport
from improvement.prompt_evolver import PromptEvolver, PromptRule
from improvement.qa_adapter import QAAdapter
from improvement.workflow_optimizer import WorkflowOptimizer


# --- Fixtures ---

@pytest.fixture
def tmp_dir(tmp_path):
  return tmp_path


@pytest.fixture
def metrics_collector(tmp_dir):
  return MetricsCollector(
    metrics_dir=tmp_dir / 'metrics',
    db_path=tmp_dir / 'metrics.db',
  )


@pytest.fixture
def sample_project() -> ProjectMetrics:
  return ProjectMetrics(
    task_id='test-001',
    project_type='website',
    instruction='테스트 프로젝트',
    started_at='2026-04-01T10:00:00+00:00',
    finished_at='2026-04-01T10:30:00+00:00',
    total_duration=1800.0,
    phases=[
      PhaseMetrics(
        phase_name='기획-IA설계',
        agent_name='planner',
        started_at='2026-04-01T10:00:00+00:00',
        finished_at='2026-04-01T10:05:00+00:00',
        duration_seconds=300.0,
        qa_passed=True,
        revision_count=0,
        group='기획',
      ),
      PhaseMetrics(
        phase_name='디자인-시스템',
        agent_name='designer',
        started_at='2026-04-01T10:05:00+00:00',
        finished_at='2026-04-01T10:15:00+00:00',
        duration_seconds=600.0,
        qa_passed=False,
        revision_count=1,
        group='디자인',
      ),
      PhaseMetrics(
        phase_name='퍼블리싱',
        agent_name='developer',
        started_at='2026-04-01T10:15:00+00:00',
        finished_at='2026-04-01T10:30:00+00:00',
        duration_seconds=900.0,
        qa_passed=True,
        revision_count=0,
        group='퍼블리싱',
      ),
    ],
    final_review_passed=True,
    final_review_rounds=0,
  )


def _make_project(task_id: str, phases: list[PhaseMetrics] | None = None) -> ProjectMetrics:
  '''테스트용 프로젝트 메트릭을 생성한다.'''
  return ProjectMetrics(
    task_id=task_id,
    project_type='website',
    instruction=f'프로젝트 {task_id}',
    started_at='2026-04-01T10:00:00+00:00',
    finished_at='2026-04-01T10:30:00+00:00',
    total_duration=1800.0,
    phases=phases or [],
  )


# --- MetricsCollector 테스트 ---

class TestMetricsCollector:

  def test_save_and_load(self, metrics_collector, sample_project):
    metrics_collector.save(sample_project)
    loaded = metrics_collector.load(sample_project.task_id)

    assert loaded is not None
    assert loaded.task_id == 'test-001'
    assert loaded.project_type == 'website'
    assert len(loaded.phases) == 3
    assert loaded.phases[0].phase_name == '기획-IA설계'

  def test_total_projects(self, metrics_collector, sample_project):
    assert metrics_collector.total_projects() == 0
    metrics_collector.save(sample_project)
    assert metrics_collector.total_projects() == 1

  def test_load_all(self, metrics_collector, sample_project):
    metrics_collector.save(sample_project)

    p2 = ProjectMetrics(
      task_id='test-002', project_type='document',
      instruction='문서 작업', started_at='2026-04-01T11:00:00+00:00',
      finished_at='2026-04-01T11:30:00+00:00', total_duration=1800.0,
    )
    metrics_collector.save(p2)

    all_projects = metrics_collector.load_all()
    assert len(all_projects) == 2

  def test_agent_stats(self, metrics_collector, sample_project):
    metrics_collector.save(sample_project)
    stats = metrics_collector.agent_stats('designer')

    assert stats['agent'] == 'designer'
    assert stats['total_phases'] == 1
    assert stats['qa_pass_rate'] == 0.0  # 1건 불합격
    assert stats['avg_revisions'] == 1.0

  def test_project_type_stats(self, metrics_collector, sample_project):
    metrics_collector.save(sample_project)
    stats = metrics_collector.project_type_stats()

    assert 'website' in stats
    assert stats['website']['count'] == 1
    assert stats['website']['pass_rate'] == 1.0

  def test_load_nonexistent(self, metrics_collector):
    assert metrics_collector.load('nonexistent') is None


# --- PatternAnalyzer 테스트 ---

class TestPatternAnalyzer:

  def test_empty_analysis(self, metrics_collector):
    analyzer = PatternAnalyzer(metrics_collector)
    report = analyzer.analyze()
    assert report.total_projects == 0
    assert report.agent_profiles == []

  def test_agent_profile(self, metrics_collector, sample_project):
    metrics_collector.save(sample_project)
    analyzer = PatternAnalyzer(metrics_collector)

    profile = analyzer.agent_profile('planner')
    assert profile.agent_name == 'planner'
    assert profile.total_phases == 1
    assert profile.qa_pass_rate == 1.0

  def test_recurring_failures(self, metrics_collector):
    '''3회 이상 동일 패턴 실패 → RecurringPattern 생성 확인.'''
    analyzer = PatternAnalyzer(metrics_collector)

    for i in range(4):
      p = _make_project(f'fail-{i}', [
        PhaseMetrics(
          phase_name='디자인-시스템', agent_name='designer',
          started_at='2026-04-01T10:00:00+00:00',
          finished_at='2026-04-01T10:10:00+00:00',
          duration_seconds=600.0, qa_passed=False,
          revision_count=1, group='디자인',
        ),
      ])
      metrics_collector.save(p)

    patterns = analyzer.recurring_failures()
    assert len(patterns) >= 1
    assert patterns[0].agent_name == 'designer'
    assert patterns[0].failure_count == 4

  def test_workflow_bottlenecks(self, metrics_collector):
    '''특정 단계가 평균 대비 2배 이상 소요 → Bottleneck 식별.'''
    analyzer = PatternAnalyzer(metrics_collector)

    phases = [
      PhaseMetrics('기획-IA설계', 'planner', '', '', 100.0, True, 0, '기획'),
      PhaseMetrics('기획-와이어프레임', 'planner', '', '', 100.0, True, 0, '기획'),
      PhaseMetrics('디자인-시스템', 'designer', '', '', 500.0, False, 2, '디자인'),  # 병목
    ]
    metrics_collector.save(_make_project('bottleneck-1', phases))
    metrics_collector.save(_make_project('bottleneck-2', phases))

    bottlenecks = analyzer.workflow_bottlenecks()
    # 디자인-시스템이 평균(233.3) 대비 2배 이상
    assert len(bottlenecks) >= 1
    assert bottlenecks[0].phase_name == '디자인-시스템'

  def test_full_analysis(self, metrics_collector, sample_project):
    metrics_collector.save(sample_project)
    analyzer = PatternAnalyzer(metrics_collector)
    report = analyzer.analyze()

    assert report.total_projects == 1
    assert len(report.agent_profiles) >= 1


# --- PromptEvolver 테스트 ---

class TestPromptEvolver:

  def test_load_empty(self, tmp_dir):
    evolver = PromptEvolver(patches_dir=tmp_dir / 'patches')
    rules = evolver.load_rules('designer')
    assert rules == []

  def test_save_and_load_rules(self, tmp_dir):
    evolver = PromptEvolver(patches_dir=tmp_dir / 'patches')
    rules = [
      PromptRule(
        id='rule-001', created_at='2026-04-01T10:00:00+00:00',
        source='pattern_analysis', category='quality',
        rule='hex 코드를 반드시 명시할 것', evidence='3회 불합격',
        priority='high',
      ),
    ]
    evolver.save_rules('designer', rules)
    loaded = evolver.load_rules('designer')

    assert len(loaded) == 1
    assert loaded[0].rule == 'hex 코드를 반드시 명시할 것'
    assert loaded[0].priority == 'high'

  def test_get_active_rules_text(self, tmp_dir):
    evolver = PromptEvolver(patches_dir=tmp_dir / 'patches')
    rules = [
      PromptRule(id='rule-001', created_at='', source='', category='',
                 rule='규칙 1', evidence='', priority='high'),
      PromptRule(id='rule-002', created_at='', source='', category='',
                 rule='규칙 2', evidence='', priority='medium', active=False),
    ]
    evolver.save_rules('designer', rules)
    text = evolver.get_active_rules_text('designer')

    assert '규칙 1' in text
    assert '규칙 2' not in text
    assert '학습된 품질 규칙' in text

  def test_toggle_rule(self, tmp_dir):
    evolver = PromptEvolver(patches_dir=tmp_dir / 'patches')
    rules = [
      PromptRule(id='rule-001', created_at='', source='', category='',
                 rule='규칙 1', evidence=''),
    ]
    evolver.save_rules('designer', rules)

    assert evolver.toggle_rule('designer', 'rule-001', False)
    loaded = evolver.load_rules('designer')
    assert loaded[0].active is False

  def test_evolve(self, tmp_dir):
    evolver = PromptEvolver(patches_dir=tmp_dir / 'patches')

    from improvement.analyzer import RecurringPattern
    report = ImprovementReport(
      total_projects=5,
      recurring_failures=[
        RecurringPattern(
          agent_name='designer', group='디자인',
          failure_count=4, description='디자이너가 디자인 단계에서 4회 불합격',
        ),
      ],
    )

    new_rules = asyncio.run(evolver.evolve(report))
    assert 'designer' in new_rules
    assert len(new_rules['designer']) == 1

    loaded = evolver.load_rules('designer')
    assert len(loaded) == 1


# --- QAAdapter 테스트 ---

class TestQAAdapter:

  def test_default_criteria(self, tmp_dir):
    adapter = QAAdapter(criteria_path=tmp_dir / 'qa.json')
    criteria = adapter.get_criteria('website')

    assert '반응형 레이아웃' in criteria['focus']

  def test_classify_project_type(self, tmp_dir):
    adapter = QAAdapter(criteria_path=tmp_dir / 'qa.json')

    assert adapter.classify_project_type('회사 홈페이지 만들어주세요') == 'website'
    assert adapter.classify_project_type('분석 보고서 작성') == 'analysis'
    assert adapter.classify_project_type('사업계획서 기획') == 'document'
    assert adapter.classify_project_type('API 서버 개발') == 'code'

  def test_build_qa_prompt_supplement(self, tmp_dir):
    adapter = QAAdapter(criteria_path=tmp_dir / 'qa.json')
    text = adapter.build_qa_prompt_supplement('website', ['접근성 누락'])

    assert 'website' in text
    assert '접근성 누락' in text

  def test_update(self, tmp_dir):
    adapter = QAAdapter(criteria_path=tmp_dir / 'qa.json')

    from improvement.analyzer import RecurringPattern
    report = ImprovementReport(
      recurring_failures=[
        RecurringPattern('designer', '디자인', 3, '설명'),
      ],
    )
    adapter.update(report)

    criteria = adapter.get_criteria('website')
    assert any('품질 강화' in f for f in criteria.get('focus', []))


# --- WorkflowOptimizer 테스트 ---

class TestWorkflowOptimizer:

  def test_get_phases_website(self, tmp_dir):
    optimizer = WorkflowOptimizer(data_path=tmp_dir / 'wf.json')
    phases = optimizer.get_phases('website')

    assert len(phases) == 7
    assert phases[0].name == '기획-IA설계'
    assert phases[-1].name == '퍼블리싱'

  def test_get_phases_document(self, tmp_dir):
    optimizer = WorkflowOptimizer(data_path=tmp_dir / 'wf.json')
    phases = optimizer.get_phases('document')

    assert len(phases) == 3
    assert all(p.assigned_to == 'planner' for p in phases)

  def test_skip_design_phase(self, tmp_dir):
    optimizer = WorkflowOptimizer(data_path=tmp_dir / 'wf.json')
    phases = optimizer.get_phases('website', '디자인 없이 바로 코드만 만들어주세요')

    # 디자인 그룹이 스킵됨
    assert not any(p.group == '디자인' for p in phases)

  def test_get_phase_dicts(self, tmp_dir):
    optimizer = WorkflowOptimizer(data_path=tmp_dir / 'wf.json')
    dicts = optimizer.get_phase_dicts('website')

    assert isinstance(dicts, list)
    assert all(isinstance(d, dict) for d in dicts)
    assert dicts[0]['name'] == '기획-IA설계'
    assert 'group' in dicts[0]

  def test_update(self, tmp_dir):
    optimizer = WorkflowOptimizer(data_path=tmp_dir / 'wf.json')

    from improvement.analyzer import Bottleneck
    report = ImprovementReport(
      bottlenecks=[
        Bottleneck('디자인-시스템', 'designer', 600.0, 200.0, 3.0, 0.6),
      ],
    )
    optimizer.update(report)

    phases = optimizer.get_phases('website')
    design_sys = next(p for p in phases if p.name == '디자인-시스템')
    assert '보완 비율' in design_sys.description


# --- ImprovementEngine 통합 테스트 ---

class TestImprovementEngine:

  def test_on_project_complete_insufficient_data(self, tmp_dir):
    from log_bus.event_bus import EventBus
    from improvement.engine import ImprovementEngine

    event_bus = EventBus()
    engine = ImprovementEngine(
      event_bus=event_bus,
      metrics=MetricsCollector(tmp_dir / 'metrics', tmp_dir / 'metrics.db'),
      prompt_evolver=PromptEvolver(tmp_dir / 'patches'),
      qa_adapter=QAAdapter(tmp_dir / 'qa.json'),
      workflow_optimizer=WorkflowOptimizer(data_path=tmp_dir / 'wf.json'),
    )

    async def _run():
      p = _make_project('eng-1')
      return await engine.on_project_complete(p)

    result = asyncio.run(_run())
    assert result is None  # 데이터 부족

  def test_on_project_complete_with_analysis(self, tmp_dir):
    from log_bus.event_bus import EventBus
    from improvement.engine import ImprovementEngine

    event_bus = EventBus()
    engine = ImprovementEngine(
      event_bus=event_bus,
      metrics=MetricsCollector(tmp_dir / 'metrics', tmp_dir / 'metrics.db'),
      prompt_evolver=PromptEvolver(tmp_dir / 'patches'),
      qa_adapter=QAAdapter(tmp_dir / 'qa.json'),
      workflow_optimizer=WorkflowOptimizer(data_path=tmp_dir / 'wf.json'),
    )

    async def _run():
      for i in range(3):
        p = _make_project(f'eng-{i}', [
          PhaseMetrics('디자인-시스템', 'designer', '', '', 300.0, False, 1, '디자인'),
        ])
        await engine.on_project_complete(p)

    asyncio.run(_run())
    assert engine.metrics.total_projects() == 3

  def test_get_report(self, tmp_dir):
    from log_bus.event_bus import EventBus
    from improvement.engine import ImprovementEngine

    event_bus = EventBus()
    engine = ImprovementEngine(
      event_bus=event_bus,
      metrics=MetricsCollector(tmp_dir / 'metrics', tmp_dir / 'metrics.db'),
    )

    report = engine.get_report()
    assert report['total_projects'] == 0

  def test_get_metrics_summary(self, tmp_dir):
    from log_bus.event_bus import EventBus
    from improvement.engine import ImprovementEngine

    event_bus = EventBus()
    metrics = MetricsCollector(tmp_dir / 'metrics', tmp_dir / 'metrics.db')
    engine = ImprovementEngine(event_bus=event_bus, metrics=metrics)

    metrics.save(_make_project('summary-1'))
    summary = engine.get_metrics_summary()
    assert len(summary) == 1
    assert summary[0]['task_id'] == 'summary-1'
