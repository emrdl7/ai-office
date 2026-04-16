"""Job 파이프라인 실행기 — Step을 순서대로 실행하고 Gate에서 대기한다."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from jobs.models import JobRun, StepRun, GateRun, JobSpec, StepSpec
from db.job_store import (
    create_job, update_job, get_job, upsert_step, open_gate, get_gate, decide_gate,
)

logger = logging.getLogger(__name__)

# 실행 중인 Job 태스크 추적 (job_id → asyncio.Task)
_running: dict[str, asyncio.Task[None]] = {}

# Gate 결정 이벤트 — polling 대신 이벤트로 즉시 깨움 (1-4)
# key: (job_id, gate_id) → asyncio.Event
_gate_events: dict[tuple[str, str], asyncio.Event] = {}


async def submit(
    spec: JobSpec,
    input_data: dict[str, Any],
    title: str = '',
    attachments_text: str = '',
) -> JobRun:
    """Job을 DB에 등록하고 백그라운드 실행 태스크를 시작한다."""
    job_id = uuid.uuid4().hex[:12]
    job = JobRun(
        id=job_id,
        spec_id=spec.id,
        title=title or f'{spec.title} #{job_id[:6]}',
        status='queued',
        input=input_data,
    )
    create_job(job)
    task = asyncio.create_task(_execute(job, spec, attachments_text=attachments_text))
    _running[job_id] = task
    task.add_done_callback(lambda _: _running.pop(job_id, None))
    return job


async def resolve_gate(job_id: str, gate_id: str, decision: str, feedback: str = '') -> bool:
    """Human Gate 결정을 DB에 저장하고, 대기 중인 runner를 즉시 깨운다."""
    decide_gate(job_id, gate_id, decision, feedback)
    # 이벤트로 polling 없이 즉시 깨움 (1-4)
    key = (job_id, gate_id)
    if key in _gate_events:
        _gate_events[key].set()
    return True


async def resume_orphan_jobs() -> None:
    """서버 재시작 후 중단된 Job을 복구한다. (1-1)

    - status='running': 마지막 완료 step 이후부터 재개
    - status='waiting_gate': gate 대기 상태 그대로 재진입
    """
    from db.job_store import list_jobs, get_steps
    from jobs.registry import get as get_spec

    try:
        orphans = list_jobs(status='running') + list_jobs(status='waiting_gate')
    except Exception as e:
        logger.warning('[resume] DB 조회 실패: %s', e)
        return

    if not orphans:
        return

    logger.info('[resume] 고아 Job %d개 발견, 복구 시도', len(orphans))

    for job_dict in orphans:
        job_id = job_dict['id']
        if job_id in _running:
            continue  # 이미 실행 중이면 스킵

        spec = get_spec(job_dict['spec_id'])
        if not spec:
            logger.warning('[resume] 스펙 없음: %s → failed 처리', job_dict['spec_id'])
            update_job(job_id, status='failed', error='재시작 복구 실패: 스펙 없음')
            continue

        # 완료된 step 목록과 artifacts에서 context 복원
        try:
            steps_rows = get_steps(job_id)
        except Exception:
            steps_rows = []

        steps_done = {s['step_id']: s for s in steps_rows if s['status'] == 'done'}

        try:
            input_data = json.loads(job_dict.get('input_json') or '{}')
        except Exception:
            input_data = {}

        try:
            artifacts = json.loads(job_dict.get('artifacts_json') or '{}')
        except Exception:
            artifacts = {}

        # context = 입력 + 이전 step 산출물
        context: dict[str, str] = {k: str(v) for k, v in input_data.items()}
        context.update({k: str(v) for k, v in artifacts.items()})

        job = JobRun(
            id=job_id,
            spec_id=job_dict['spec_id'],
            title=job_dict['title'],
            status=job_dict['status'],
            input=input_data,
            artifacts=artifacts,
        )

        logger.info('[resume] Job 복구 시작: %s (상태: %s, 완료 step: %s)',
                    job_id, job_dict['status'], list(steps_done.keys()))

        task = asyncio.create_task(
            _execute(job, spec, resume_context=context, resume_steps_done=steps_done)
        )
        _running[job_id] = task
        task.add_done_callback(lambda _: _running.pop(job_id, None))


# ── 내부 실행 로직 ────────────────────────────────────────────────────────────

async def _execute(
    job: JobRun,
    spec: JobSpec,
    attachments_text: str = '',
    resume_context: dict[str, str] | None = None,
    resume_steps_done: dict[str, Any] | None = None,
) -> None:
    """Job의 모든 Step을 순서대로 실행한다.

    Args:
        resume_context: 재시작 복구 시 이전 context (없으면 입력 데이터로 초기화)
        resume_steps_done: 재시작 복구 시 이미 완료된 step 집합
    """
    from log_bus.event_bus import event_bus, LogEvent

    async def emit(msg: str, event_type: str = 'job_event', data: dict | None = None) -> None:
        try:
            await event_bus.publish(LogEvent(
                agent_id='system',
                event_type=event_type,
                message=msg,
                data={'job_id': job.id, **(data or {})},
            ))
        except Exception:
            pass

    is_resume = resume_context is not None
    steps_done = resume_steps_done or {}

    now = datetime.now(timezone.utc).isoformat()
    update_job(job.id, status='running', started_at=now if not is_resume else job.id)
    if is_resume:
        await emit(f'♻️ Job 복구 재개: {job.title}', 'job_resumed')
    else:
        await emit(f'🚀 Job 시작: {job.title}', 'job_started')

    # Gate 맵 (after_step → GateSpec)
    gate_map = {g.after_step: g for g in spec.gates}

    # context 초기화 (재시작 복구면 이전 context 사용)
    context: dict[str, str] = resume_context.copy() if is_resume else {}
    if not is_resume:
        context.update({k: str(v) for k, v in job.input.items()})
        if attachments_text:
            context['_attachments'] = attachments_text

    try:
        for step in spec.steps:
            # 재시작 복구: 이미 완료된 step은 건너뜀
            if step.id in steps_done:
                logger.debug('[resume] step 건너뜀 (이미 완료): %s', step.id)
                # Gate가 있었다면, 복구 중에는 해당 gate도 건너뜀
                # (waiting_gate 상태면 마지막 완료 step의 gate에서 재진입)
                continue

            # waiting_gate 복구: 현재 job이 gate 대기 중이었으면 gate 로직으로 진입
            # (step은 이미 완료 → step 재실행 없이 gate 대기만)
            gate = gate_map.get(step.id)
            if is_resume and job.status == 'waiting_gate' and gate:
                # 마지막 완료 step이 이 step이면 gate 대기 재진입
                current_step = job_dict_field(job.id, 'current_step')
                if current_step == step.id or not current_step:
                    # step output은 artifacts에서 복원
                    if step.output_key and step.output_key in context:
                        pass  # context에 이미 있음
                    await emit(f'♻️ Gate 재대기: {gate.id}', 'job_gate_opened',
                               {'gate_id': gate.id, 'prompt': gate.prompt})
                    update_job(job.id, status='waiting_gate')
                    gate_result = await _wait_gate(job.id, gate, step, context, emit)
                    if gate_result == 'cancelled':
                        return
                    elif gate_result == 'failed':
                        update_job(job.id, status='failed', error='Gate 대기 시간 초과')
                        return
                    # 승인 후 다음 step으로
                    continue

            update_job(job.id, current_step=step.id)
            await emit(f'▶ Step: {step.id}', 'job_step_started',
                       {'step_id': step.id, 'tier': step.tier})

            step_run = await _run_step(job.id, step, context)
            upsert_step(step_run)

            if step_run.status == 'failed':
                update_job(job.id, status='failed', error=step_run.error,
                           finished_at=datetime.now(timezone.utc).isoformat())
                await emit(f'❌ Step 실패: {step.id} — {step_run.error[:200]}', 'job_step_failed')
                return

            # 결과를 context에 저장
            if step.output_key:
                context[step.output_key] = step_run.output

            # artifact 저장
            artifacts = json_loads(get_job(job.id) or {}, 'artifacts')
            artifacts[step.output_key or step.id] = step_run.output
            update_job(job.id, artifacts=artifacts)

            await emit(f'✅ Step 완료: {step.id}', 'job_step_done',
                       {'step_id': step.id, 'output_len': len(step_run.output)})

            # Gate 체크
            if gate:
                gate_run = GateRun(job_id=job.id, gate_id=gate.id, status='pending')
                open_gate(gate_run)
                update_job(job.id, status='waiting_gate')
                await emit(
                    f'🔔 Gate 대기: {gate.prompt}',
                    'job_gate_opened',
                    {'gate_id': gate.id, 'prompt': gate.prompt},
                )

                gate_result = await _wait_gate(job.id, gate, step, context, emit)
                if gate_result == 'cancelled':
                    return
                elif gate_result == 'failed':
                    update_job(job.id, status='failed', error='Gate 대기 시간 초과')
                    return

        # 모든 Step 완료 — 비용 합산 (2-5)
        try:
            from db.job_store import get_steps as _get_steps_final
            total_cost = sum(s.get('cost_usd', 0.0) for s in _get_steps_final(job.id))
        except Exception:
            total_cost = 0.0
        update_job(job.id, status='done',
                   finished_at=datetime.now(timezone.utc).isoformat(),
                   current_step='',
                   total_cost_usd=round(total_cost, 6))
        await emit(f'🎉 Job 완료: {job.title}', 'job_done')

    except asyncio.CancelledError:
        update_job(job.id, status='failed', error='취소됨')
        raise
    except Exception as e:
        logger.exception('Job 실행 오류: %s', job.id)
        update_job(job.id, status='failed', error=str(e)[:500],
                   finished_at=datetime.now(timezone.utc).isoformat())
        await emit(f'❌ Job 오류: {e!s:.200}', 'job_failed')


async def _wait_gate(
    job_id: str,
    gate: Any,
    step: StepSpec,
    context: dict[str, str],
    emit: Any,
) -> str:
    """Gate 결정을 이벤트로 대기한다. (1-4: polling → asyncio.Event)

    Returns:
        'approved' | 'cancelled' | 'failed'
    """
    from db.job_store import _conn as _jconn, get_steps as _get_steps

    max_wait = gate.auto_advance_after  # None = 무제한

    while True:
        # 이벤트 등록
        key = (job_id, gate.id)
        event = asyncio.Event()
        _gate_events[key] = event

        try:
            if max_wait is not None:
                try:
                    await asyncio.wait_for(event.wait(), timeout=float(max_wait))
                except asyncio.TimeoutError:
                    _gate_events.pop(key, None)
                    # 타임아웃 → auto_advance
                    if gate.auto_advance_after:
                        decide_gate(job_id, gate.id, 'approved', 'auto-advance(timeout)')
                        update_job(job_id, status='running')
                        await emit(f'⏩ Gate 자동 승인: {gate.id}', 'job_gate_approved')
                        return 'approved'
                    else:
                        return 'failed'
            else:
                await event.wait()
        finally:
            _gate_events.pop(key, None)

        # 결정 읽기
        row = get_gate(job_id, gate.id)
        if not row:
            continue
        decision = row.get('decision', '')

        if decision == 'approved':
            if row.get('feedback'):
                context[f'{gate.id}_feedback'] = row['feedback']
            update_job(job_id, status='running')
            await emit(f'✅ Gate 승인: {gate.id}', 'job_gate_approved')
            return 'approved'

        elif decision == 'rejected':
            update_job(job_id, status='cancelled',
                       finished_at=datetime.now(timezone.utc).isoformat())
            await emit(f'🚫 Job 취소: Gate {gate.id} 거절', 'job_cancelled')
            return 'cancelled'

        elif decision == 'revised':
            fb = row.get('feedback', '')
            context[f'{gate.id}_feedback'] = fb
            context['revision_request'] = fb

            # gate → revising 상태
            _c = _jconn()
            _c.execute(
                "UPDATE job_gates SET status='revising', decision='', feedback=? "
                "WHERE job_id=? AND gate_id=?",
                (fb, job_id, gate.id),
            )
            _c.commit(); _c.close()
            update_job(job_id, status='running')
            await emit(f'🔄 수정 재실행: {step.id} (피드백: {fb[:80]})', 'job_step_revised',
                       {'step_id': step.id, 'feedback': fb})

            # 이전 revised 카운트
            prev_steps = {s['step_id']: s for s in _get_steps(job_id)}
            prev_revised = (prev_steps.get(step.id) or {}).get('revised', 0) or 0

            # step 재실행
            step_run = await _run_step(job_id, step, context)
            step_run.revised = prev_revised + 1
            step_run.revision_feedback = fb
            upsert_step(step_run)
            if step.output_key:
                context[step.output_key] = step_run.output

            artifacts = json_loads(get_job(job_id) or {}, 'artifacts')
            artifacts[step.output_key or step.id] = step_run.output
            update_job(job_id, artifacts=artifacts)

            # gate → pending 재오픈
            _c2 = _jconn()
            _c2.execute(
                "UPDATE job_gates SET status='pending', decision='', "
                "opened_at=? WHERE job_id=? AND gate_id=?",
                (datetime.now(timezone.utc).isoformat(), job_id, gate.id),
            )
            _c2.commit(); _c2.close()
            update_job(job_id, status='waiting_gate')
            await emit(f'🔔 Gate 재대기: {gate.prompt}', 'job_gate_opened',
                       {'gate_id': gate.id, 'prompt': gate.prompt})
            # 루프 재진입 → 새 Event 등록 후 다시 대기
            continue

        else:
            # 결정 없음 — 이벤트가 조기에 set된 경우, 잠시 후 재확인
            await asyncio.sleep(0.5)
            continue


async def _run_step(job_id: str, step: StepSpec, context: dict[str, str]) -> StepRun:
    """단일 Step 실행 — 프롬프트를 채우고 model_router로 호출한다."""
    from runners import model_router

    started = datetime.now(timezone.utc).isoformat()
    step_run = StepRun(
        job_id=job_id,
        step_id=step.id,
        status='running',
        started_at=started,
    )
    upsert_step(step_run)

    try:
        prompt = _fill(step.prompt_template, context)

        if step.tools:
            tool_results = await _run_tools(step.tools, context)
            if tool_results:
                prompt = prompt + '\n\n[수집된 참고 자료]\n' + tool_results

        attachments = context.get('_attachments', '')
        if attachments:
            prompt = prompt + '\n\n[사용자 첨부 참조 자료 — 작업 시 반드시 반영]\n' + attachments

        text, model_used = await model_router.run(
            tier=step.tier,
            prompt=prompt,
            agent_id=f'{step.agent}:{step.id}',
            timeout=180.0,
        )

        # 비용 추산 (2-5)
        try:
            from runners.cost_tracker import _estimate_tokens, _estimate_cost
            in_toks = _estimate_tokens(prompt)
            out_toks = _estimate_tokens(text)
            cost_usd = _estimate_cost(model_used, in_toks, out_toks)
        except Exception:
            cost_usd = 0.0

        step_run.status = 'done'
        step_run.output = text
        step_run.model_used = model_used
        step_run.cost_usd = cost_usd
        step_run.finished_at = datetime.now(timezone.utc).isoformat()
        return step_run

    except Exception as e:
        step_run.status = 'failed'
        step_run.error = str(e)[:500]
        step_run.finished_at = datetime.now(timezone.utc).isoformat()
        return step_run


async def _run_tools(tool_ids: list[str], context: dict[str, str]) -> str:
    """도구 목록을 실행하고 결과를 합친다."""
    from jobs.tool_registry import execute_tool

    results: list[str] = []
    for tid in tool_ids:
        try:
            result = await asyncio.to_thread(execute_tool, tid, context)
            if result:
                results.append(f'[{tid}]\n{result}')
        except Exception as e:
            logger.warning('Tool 실행 실패: %s — %s', tid, e)
    return '\n\n'.join(results)


def _fill(template: str, context: dict[str, str]) -> str:
    """템플릿의 {key}를 context 값으로 치환한다."""
    import re
    result = template
    for k, v in context.items():
        result = result.replace('{' + k + '}', str(v))
    result = re.sub(r'\{[a-z_]+\}', '', result)
    return result.strip()


def json_loads(job_dict: dict, key: str) -> dict:
    val = job_dict.get(key, {})
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return val if isinstance(val, dict) else {}


def job_dict_field(job_id: str, field: str) -> str:
    """DB에서 Job의 단일 필드를 읽는다."""
    row = get_job(job_id)
    if not row:
        return ''
    return row.get(field, '') or ''
