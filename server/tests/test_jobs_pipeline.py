"""Job 파이프라인 핵심 경로 smoke test (4-6).

검증 대상:
1. intent parser — 정규식 기반 파싱, 다양한 LLM 응답 형식
2. gate event — resolve_gate()가 asyncio.Event를 즉시 set
3. job store WAL — job/step CRUD가 올바르게 동작
4. runner submit — Job이 DB에 등록되고 태스크가 생성됨
"""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 1. Intent Parser ────────────────────────────────────────────────────────

class TestIntentParser:
    """_parse_intent_response — 정규식 기반 파싱."""

    def _parse(self, text: str) -> str:
        """orchestration/intent.py 와 같은 로직을 인라인 재현."""
        m = re.search(
            r'\[(CONVERSATION|QUICK_TASK(?::[a-z]+)?'
            r'|CONTINUE_PROJECT(?::[a-z]+)?'
            r'|PROJECT|JOB(?::[a-z_]+)?)\]',
            text,
        )
        if not m:
            return 'CONVERSATION'
        return m.group(1)

    def test_bare_tag(self):
        assert self._parse('[JOB:research]') == 'JOB:research'

    def test_tag_with_preamble(self):
        text = '물론이죠, 제가 도와드리겠습니다.\n[JOB:planning]\n{"topic": "AI"}'
        assert self._parse(text) == 'JOB:planning'

    def test_conversation_fallback(self):
        assert self._parse('안녕하세요, 반갑습니다!') == 'CONVERSATION'

    def test_project_tag(self):
        assert self._parse('Let me start this. [PROJECT]') == 'PROJECT'

    def test_quick_task(self):
        assert self._parse('[QUICK_TASK:writing]') == 'QUICK_TASK:writing'

    def test_only_first_match_used(self):
        # 두 개 있어도 첫 번째만
        text = '[JOB:research] 그리고 [JOB:planning]'
        assert self._parse(text) == 'JOB:research'

    def test_json_body_extraction(self):
        body = '설명\n{"topic": "AI", "depth": "deep"}\n끝'
        m = re.search(r'\{[\s\S]*\}', body)
        assert m is not None
        data = json.loads(m.group())
        assert data['topic'] == 'AI'


# ─── 2. Gate Event ───────────────────────────────────────────────────────────

class TestGateEvent:
    """resolve_gate()가 asyncio.Event를 즉시 set 하는지 검증."""

    @pytest.mark.asyncio
    async def test_resolve_sets_event(self, tmp_path, monkeypatch):
        # DB를 임시 경로로 격리
        import db.job_store as js
        monkeypatch.setattr(js, '_DB', tmp_path / 'jobs.db')

        # DB 초기화 + 더미 job/gate 삽입
        from jobs.models import JobRun, GateRun
        from datetime import datetime, timezone
        job = JobRun(
            id='testjob001',
            spec_id='research',
            title='test',
            status='waiting_gate',
            input={},
        )
        js.create_job(job)
        gate = GateRun(
            job_id='testjob001',
            gate_id='gate_review',
            status='pending',
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        js.open_gate(gate)

        # runner의 _gate_events에 이벤트 등록
        from jobs import runner as runner_mod
        event = asyncio.Event()
        key = ('testjob001', 'gate_review')
        runner_mod._gate_events[key] = event

        # resolve_gate 호출
        await runner_mod.resolve_gate('testjob001', 'gate_review', 'approved', '')

        assert event.is_set(), 'resolve_gate()가 asyncio.Event를 set해야 함'

        # 정리
        runner_mod._gate_events.pop(key, None)

    @pytest.mark.asyncio
    async def test_resolve_without_event_does_not_raise(self, tmp_path, monkeypatch):
        """이벤트가 없어도 예외 없이 동작해야 함."""
        import db.job_store as js
        monkeypatch.setattr(js, '_DB', tmp_path / 'jobs.db')

        from jobs.models import JobRun, GateRun
        from datetime import datetime, timezone
        job = JobRun(id='testjob002', spec_id='research', title='t', status='running', input={})
        js.create_job(job)
        gate = GateRun(
            job_id='testjob002',
            gate_id='gate_x',
            status='pending',
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        js.open_gate(gate)

        from jobs import runner as runner_mod
        # 이벤트 없음 — 예외 없어야 함
        result = await runner_mod.resolve_gate('testjob002', 'gate_x', 'rejected', '')
        assert result is True


# ─── 3. Job Store WAL ────────────────────────────────────────────────────────

class TestJobStoreCrud:
    """job_store CRUD — WAL 모드 하에서 정확한 읽기/쓰기."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        import db.job_store as js
        monkeypatch.setattr(js, '_DB', tmp_path / 'jobs.db')

    def _make_job(self, jid: str) -> 'JobRun':
        from jobs.models import JobRun
        return JobRun(
            id=jid,
            spec_id='research',
            title=f'Job {jid}',
            status='queued',
            input={'topic': 'AI'},
        )

    def test_create_and_get(self):
        from db.job_store import create_job, get_job
        job = self._make_job('j001')
        create_job(job)
        row = get_job('j001')
        assert row is not None
        assert row['title'] == 'Job j001'
        assert row['input']['topic'] == 'AI'

    def test_update_status(self):
        from db.job_store import create_job, update_job, get_job
        job = self._make_job('j002')
        create_job(job)
        update_job('j002', status='running')
        row = get_job('j002')
        assert row['status'] == 'running'

    def test_update_artifacts(self):
        from db.job_store import create_job, update_job, get_job
        job = self._make_job('j003')
        create_job(job)
        update_job('j003', artifacts={'report': 'AI는 좋다'})
        row = get_job('j003')
        assert row['artifacts']['report'] == 'AI는 좋다'

    def test_list_jobs_filter_status(self):
        from db.job_store import create_job, list_jobs, update_job
        j1 = self._make_job('j010')
        j2 = self._make_job('j011')
        create_job(j1)
        create_job(j2)
        update_job('j010', status='done')
        done = list_jobs(status='done')
        assert any(r['id'] == 'j010' for r in done)
        assert not any(r['id'] == 'j011' for r in done)

    def test_upsert_step(self):
        from db.job_store import create_job, upsert_step, get_steps
        from jobs.models import StepRun
        from datetime import datetime, timezone
        job = self._make_job('j020')
        create_job(job)
        step = StepRun(
            job_id='j020',
            step_id='step_research',
            status='done',
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            output='연구 결과',
        )
        upsert_step(step)
        steps = get_steps('j020')
        assert len(steps) == 1
        assert steps[0]['output'] == '연구 결과'

    def test_upsert_step_idempotent(self):
        """같은 step_id로 두 번 upsert해도 row가 하나여야 함."""
        from db.job_store import create_job, upsert_step, get_steps
        from jobs.models import StepRun
        from datetime import datetime, timezone
        job = self._make_job('j021')
        create_job(job)
        step = StepRun(job_id='j021', step_id='s1', status='running',
                       started_at=datetime.now(timezone.utc).isoformat())
        upsert_step(step)
        step2 = StepRun(job_id='j021', step_id='s1', status='done',
                        started_at=step.started_at,
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        output='최종')
        upsert_step(step2)
        steps = get_steps('j021')
        assert len(steps) == 1
        assert steps[0]['status'] == 'done'
        assert steps[0]['output'] == '최종'


# ─── 4. Runner Submit ────────────────────────────────────────────────────────

class TestRunnerSubmit:
    """submit()이 Job을 DB에 등록하고 asyncio Task를 생성하는지 검증."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        import db.job_store as js
        monkeypatch.setattr(js, '_DB', tmp_path / 'jobs.db')

    def _make_spec(self) -> 'JobSpec':
        from jobs.models import JobSpec, StepSpec
        return JobSpec(
            id='research',
            title='리서치',
            description='...',
            version=1,
            input_fields=['topic'],
            required_fields=['topic'],
            steps=[
                StepSpec(id='s1', agent='researcher', tier='nano',
                         prompt_template='{{topic}} 조사'),
            ],
            gates=[],
        )

    @pytest.mark.asyncio
    async def test_submit_creates_job_in_db(self, tmp_path, monkeypatch):
        import db.job_store as js
        monkeypatch.setattr(js, '_DB', tmp_path / 'jobs.db')

        spec = self._make_spec()

        # _execute가 실제 LLM을 호출하지 않도록 mock
        from jobs import runner as runner_mod
        async def _fake_execute(*args, **kwargs):
            pass
        monkeypatch.setattr(runner_mod, '_execute', _fake_execute)

        job = await runner_mod.submit(spec, {'topic': 'AI'}, title='테스트 Job')

        assert job.id is not None
        row = js.get_job(job.id)
        assert row is not None
        assert row['title'] == '테스트 Job'
        assert row['status'] == 'queued'
        assert row['input']['topic'] == 'AI'

    @pytest.mark.asyncio
    async def test_submit_with_attachments(self, tmp_path, monkeypatch):
        import db.job_store as js
        monkeypatch.setattr(js, '_DB', tmp_path / 'jobs.db')

        spec = self._make_spec()

        captured: dict = {}

        from jobs import runner as runner_mod
        async def _fake_execute(job, spec, attachments_text='', **kw):
            captured['attachments_text'] = attachments_text
        monkeypatch.setattr(runner_mod, '_execute', _fake_execute)

        await runner_mod.submit(spec, {'topic': 'AI'}, attachments_text='이전 산출물')
        # 태스크가 실행될 때까지 잠깐 양보
        await asyncio.sleep(0)

        assert captured.get('attachments_text') == '이전 산출물'
