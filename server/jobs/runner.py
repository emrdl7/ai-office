"""Job 파이프라인 실행기 — Step을 순서대로 실행하고 Gate에서 대기한다."""
from __future__ import annotations

import asyncio
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


async def submit(
    spec: JobSpec,
    input_data: dict[str, Any],
    title: str = '',
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
    task = asyncio.create_task(_execute(job, spec))
    _running[job_id] = task
    task.add_done_callback(lambda _: _running.pop(job_id, None))
    return job


async def resolve_gate(job_id: str, gate_id: str, decision: str, feedback: str = '') -> bool:
    """Human Gate 결정을 DB에 저장하고, 대기 중인 Job을 깨운다."""
    decide_gate(job_id, gate_id, decision, feedback)
    # 실행 중인 태스크가 있으면 바로 event로 깨울 수 있지만,
    # 여기서는 polling 기반으로 단순하게 처리 (runner가 1초마다 체크)
    return True


# ── 내부 실행 로직 ────────────────────────────────────────────────────────────

async def _execute(job: JobRun, spec: JobSpec) -> None:
    """Job의 모든 Step을 순서대로 실행한다."""
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

    now = datetime.now(timezone.utc).isoformat()
    update_job(job.id, status='running', started_at=now)
    await emit(f'🚀 Job 시작: {job.title}', 'job_started')

    # Gate 맵 (after_step → GateSpec)
    gate_map = {g.after_step: g for g in spec.gates}

    # 각 Step에서 생성한 결과를 다음 Step 프롬프트에 주입
    context: dict[str, str] = {}

    # 입력 데이터를 context에 주입
    context.update({k: str(v) for k, v in job.input.items()})

    try:
        for step in spec.steps:
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

            # 결과를 context에 저장 (다음 step 프롬프트에 {key} 형태로 주입)
            if step.output_key:
                context[step.output_key] = step_run.output

            # artifact 저장
            artifacts = json_loads(get_job(job.id) or {}, 'artifacts')
            artifacts[step.output_key or step.id] = step_run.output
            update_job(job.id, artifacts=artifacts)

            await emit(f'✅ Step 완료: {step.id}', 'job_step_done',
                       {'step_id': step.id, 'output_len': len(step_run.output)})

            # Gate 체크
            gate = gate_map.get(step.id)
            if gate:
                gate_run = GateRun(job_id=job.id, gate_id=gate.id, status='pending')
                open_gate(gate_run)
                update_job(job.id, status='waiting_gate')
                await emit(
                    f'🔔 Gate 대기: {gate.prompt}',
                    'job_gate_opened',
                    {'gate_id': gate.id, 'prompt': gate.prompt},
                )

                # Gate 결정 대기 (최대 auto_advance_after 초, 없으면 무제한)
                max_wait = gate.auto_advance_after or 86400 * 7  # 7일
                waited = 0
                while waited < max_wait:
                    await asyncio.sleep(3)
                    waited += 3
                    row = get_gate(job.id, gate.id)
                    if not row:
                        continue
                    decision = row.get('decision', '')
                    if decision == 'approved':
                        # 피드백 있으면 context에 주입
                        if row.get('feedback'):
                            context[f'{gate.id}_feedback'] = row['feedback']
                        update_job(job.id, status='running')
                        await emit(f'✅ Gate 승인: {gate.id}', 'job_gate_approved')
                        break
                    elif decision == 'rejected':
                        update_job(job.id, status='cancelled',
                                   finished_at=datetime.now(timezone.utc).isoformat())
                        await emit(f'🚫 Job 취소: Gate {gate.id} 거절', 'job_cancelled')
                        return
                    elif decision == 'revised':
                        # 수정 요청: 피드백을 context에 넣고 마지막 Step 재실행
                        fb = row.get('feedback', '')
                        context[f'{gate.id}_feedback'] = fb
                        context['revision_request'] = fb
                        # gate를 다시 pending으로 초기화하고 step 재실행
                        decide_gate(job.id, gate.id, '', '')
                        from db.job_store import _conn as _jconn
                        c = _jconn()
                        c.execute(
                            "UPDATE job_gates SET status='pending', decision='' WHERE job_id=? AND gate_id=?",
                            (job.id, gate.id),
                        )
                        c.commit(); c.close()
                        update_job(job.id, status='running')
                        await emit(f'🔄 수정 재실행: {step.id}', 'job_step_revised')
                        step_run = await _run_step(job.id, step, context)
                        upsert_step(step_run)
                        if step.output_key:
                            context[step.output_key] = step_run.output
                        artifacts[step.output_key or step.id] = step_run.output
                        update_job(job.id, artifacts=artifacts)
                        # 다시 gate 오픈
                        gate_run2 = GateRun(job_id=job.id, gate_id=gate.id, status='pending')
                        open_gate(gate_run2)
                        update_job(job.id, status='waiting_gate')
                        await emit(f'🔔 Gate 재대기: {gate.prompt}', 'job_gate_opened',
                                   {'gate_id': gate.id, 'prompt': gate.prompt})
                else:
                    # 타임아웃 — auto_advance
                    if gate.auto_advance_after:
                        decide_gate(job.id, gate.id, 'approved', 'auto-advance(timeout)')
                        update_job(job.id, status='running')
                        await emit(f'⏩ Gate 자동 승인: {gate.id}', 'job_gate_approved')
                    else:
                        update_job(job.id, status='failed', error='Gate 대기 시간 초과')
                        return

        # 모든 Step 완료
        update_job(job.id, status='done',
                   finished_at=datetime.now(timezone.utc).isoformat(),
                   current_step='')
        await emit(f'🎉 Job 완료: {job.title}', 'job_done')

    except asyncio.CancelledError:
        update_job(job.id, status='failed', error='취소됨')
        raise
    except Exception as e:
        logger.exception('Job 실행 오류: %s', job.id)
        update_job(job.id, status='failed', error=str(e)[:500],
                   finished_at=datetime.now(timezone.utc).isoformat())
        await emit(f'❌ Job 오류: {e!s:.200}', 'job_failed')


async def _run_step(job_id: str, step: StepSpec, context: dict[str, str]) -> StepRun:
    """단일 Step 실행 — 프롬프트를 채우고 model_router로 호출한다."""
    from datetime import datetime, timezone
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
        # 프롬프트 템플릿에 context 주입
        prompt = _fill(step.prompt_template, context)

        # Tool 결과를 프롬프트에 선처리
        if step.tools:
            tool_results = await _run_tools(step.tools, context)
            if tool_results:
                prompt = prompt + '\n\n[수집된 참고 자료]\n' + tool_results

        text, model_used = await model_router.run(
            tier=step.tier,
            prompt=prompt,
            agent_id=f'{step.agent}:{step.id}',
            timeout=180.0,
        )

        step_run.status = 'done'
        step_run.output = text
        step_run.model_used = model_used
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
    result = template
    for k, v in context.items():
        result = result.replace('{' + k + '}', str(v))
    # 채워지지 않은 플레이스홀더는 빈 문자열로
    import re
    result = re.sub(r'\{[a-z_]+\}', '', result)
    return result.strip()


def json_loads(job_dict: dict, key: str) -> dict:
    import json
    val = job_dict.get(key, {})
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return val if isinstance(val, dict) else {}
