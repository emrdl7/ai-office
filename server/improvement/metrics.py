# 성과 수집기 — 프로젝트 실행 메트릭을 수집하고 저장한다
from __future__ import annotations
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class PhaseMetrics:
  '''단계별 성과 메트릭.'''
  phase_name: str
  agent_name: str
  started_at: str       # ISO timestamp
  finished_at: str
  duration_seconds: float
  qa_passed: bool
  revision_count: int
  group: str = ''


@dataclass
class ProjectMetrics:
  '''프로젝트 전체 성과 메트릭.'''
  task_id: str
  project_type: str     # 'website', 'document', 'analysis', 'code'
  instruction: str
  started_at: str
  finished_at: str
  total_duration: float
  phases: list[PhaseMetrics] = field(default_factory=list)
  final_review_passed: bool = True
  final_review_rounds: int = 0


METRICS_DIR = Path(__file__).parent.parent / 'data' / 'metrics'
METRICS_DB = Path(__file__).parent.parent / 'data' / 'metrics.db'


def _ensure_db(db_path: Path | None = None) -> sqlite3.Connection:
  '''SQLite 집계 테이블을 생성/연결한다.'''
  path = db_path or METRICS_DB
  path.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(str(path))
  conn.row_factory = sqlite3.Row
  conn.execute('''
    CREATE TABLE IF NOT EXISTS project_metrics (
      task_id TEXT PRIMARY KEY,
      project_type TEXT NOT NULL,
      instruction TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT NOT NULL,
      total_duration REAL NOT NULL,
      phase_count INTEGER NOT NULL,
      final_review_passed INTEGER NOT NULL,
      final_review_rounds INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    )
  ''')
  conn.execute('''
    CREATE TABLE IF NOT EXISTS phase_metrics (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL,
      phase_name TEXT NOT NULL,
      agent_name TEXT NOT NULL,
      started_at TEXT,
      finished_at TEXT,
      duration_seconds REAL NOT NULL DEFAULT 0,
      qa_passed INTEGER NOT NULL DEFAULT 1,
      revision_count INTEGER NOT NULL DEFAULT 0,
      phase_group TEXT NOT NULL DEFAULT '',
      FOREIGN KEY (task_id) REFERENCES project_metrics(task_id)
    )
  ''')
  conn.commit()
  return conn


class MetricsCollector:
  '''프로젝트 성과 메트릭을 수집하고 저장한다.'''

  def __init__(self, metrics_dir: str | Path | None = None, db_path: str | Path | None = None):
    self._metrics_dir = Path(metrics_dir) if metrics_dir else METRICS_DIR
    self._metrics_dir.mkdir(parents=True, exist_ok=True)
    self._db_path = Path(db_path) if db_path else METRICS_DB

  def save(self, metrics: ProjectMetrics) -> None:
    '''프로젝트 메트릭을 JSON 파일 + SQLite에 저장한다.'''
    # JSON 파일 저장
    json_path = self._metrics_dir / f'{metrics.task_id}.json'
    data = asdict(metrics)
    tmp = json_path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
      json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp, json_path)

    # SQLite 집계 저장
    conn = _ensure_db(self._db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
      '''INSERT OR REPLACE INTO project_metrics
         (task_id, project_type, instruction, started_at, finished_at,
          total_duration, phase_count, final_review_passed, final_review_rounds, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
      (metrics.task_id, metrics.project_type, metrics.instruction[:500],
       metrics.started_at, metrics.finished_at, metrics.total_duration,
       len(metrics.phases), int(metrics.final_review_passed),
       metrics.final_review_rounds, now),
    )
    for pm in metrics.phases:
      conn.execute(
        '''INSERT INTO phase_metrics
           (task_id, phase_name, agent_name, started_at, finished_at,
            duration_seconds, qa_passed, revision_count, phase_group)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (metrics.task_id, pm.phase_name, pm.agent_name, pm.started_at,
         pm.finished_at, pm.duration_seconds, int(pm.qa_passed),
         pm.revision_count, pm.group),
      )
    conn.commit()
    conn.close()

  def load(self, task_id: str) -> ProjectMetrics | None:
    '''특정 프로젝트의 메트릭을 로드한다.'''
    json_path = self._metrics_dir / f'{task_id}.json'
    if not json_path.exists():
      return None
    with open(json_path, encoding='utf-8') as f:
      data = json.load(f)
    phases = [PhaseMetrics(**p) for p in data.pop('phases', [])]
    return ProjectMetrics(**data, phases=phases)

  def load_all(self) -> list[ProjectMetrics]:
    '''전체 프로젝트 메트릭을 로드한다 (최신순).'''
    results = []
    for json_path in sorted(self._metrics_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
      try:
        with open(json_path, encoding='utf-8') as f:
          data = json.load(f)
        phases = [PhaseMetrics(**p) for p in data.pop('phases', [])]
        results.append(ProjectMetrics(**data, phases=phases))
      except Exception:
        logger.debug("메트릭 JSON 파싱 실패: %s", json_path, exc_info=True)
        continue
    return results

  def total_projects(self) -> int:
    '''저장된 프로젝트 수를 반환한다.'''
    return len(list(self._metrics_dir.glob('*.json')))

  def agent_stats(self, agent_name: str) -> dict[str, Any]:
    '''에이전트별 통계를 반환한다.'''
    conn = _ensure_db(self._db_path)
    rows = conn.execute(
      'SELECT * FROM phase_metrics WHERE agent_name = ?', (agent_name,)
    ).fetchall()
    conn.close()

    if not rows:
      return {'agent': agent_name, 'total_phases': 0}

    total = len(rows)
    passed = sum(1 for r in rows if r['qa_passed'])
    total_revisions = sum(r['revision_count'] for r in rows)
    avg_duration = sum(r['duration_seconds'] for r in rows) / total

    return {
      'agent': agent_name,
      'total_phases': total,
      'qa_pass_rate': passed / total if total else 0,
      'avg_revisions': total_revisions / total if total else 0,
      'avg_duration_seconds': avg_duration,
    }

  def project_type_stats(self) -> dict[str, dict]:
    '''프로젝트 유형별 통계를 반환한다.'''
    conn = _ensure_db(self._db_path)
    rows = conn.execute('SELECT * FROM project_metrics').fetchall()
    conn.close()

    stats: dict[str, dict] = {}
    for row in rows:
      ptype = row['project_type']
      if ptype not in stats:
        stats[ptype] = {'count': 0, 'total_duration': 0, 'passed': 0}
      stats[ptype]['count'] += 1
      stats[ptype]['total_duration'] += row['total_duration']
      stats[ptype]['passed'] += row['final_review_passed']

    for ptype, s in stats.items():
      s['avg_duration'] = s['total_duration'] / s['count'] if s['count'] else 0
      s['pass_rate'] = s['passed'] / s['count'] if s['count'] else 0

    return stats
