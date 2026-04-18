"""Job 파이프라인 실행기 — Step을 순서대로 실행하고 Gate에서 대기한다."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
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
    depends_on_job_ids: list[str] | None = None,
) -> JobRun:
    """Job을 DB에 등록하고 백그라운드 실행 태스크를 시작한다.

    Args:
        depends_on_job_ids: 완료를 기다려야 하는 선행 Job ID 목록 (DAG, 2-1)
    """
    job_id = uuid.uuid4().hex[:12]
    job = JobRun(
        id=job_id,
        spec_id=spec.id,
        title=title or await _generate_title(spec, input_data, job_id),
        status='queued',
        input=input_data,
    )
    create_job(job)
    task = asyncio.create_task(_execute(
        job, spec,
        attachments_text=attachments_text,
        depends_on_job_ids=depends_on_job_ids or [],
    ))
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
    depends_on_job_ids: list[str] | None = None,
) -> None:
    """Job의 모든 Step을 순서대로 실행한다.

    Args:
        resume_context: 재시작 복구 시 이전 context (없으면 입력 데이터로 초기화)
        resume_steps_done: 재시작 복구 시 이미 완료된 step 집합
        depends_on_job_ids: 완료를 기다려야 하는 선행 Job ID 목록 (DAG, 2-1)
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

    # DAG 의존 Job 완료 대기 (2-1)
    if depends_on_job_ids:
        update_job(job.id, status='queued')
        await emit(f'⏳ 선행 Job 완료 대기: {depends_on_job_ids}', 'job_dag_waiting')
        max_dag_wait = 7200.0
        dag_waited = 0.0
        while dag_waited < max_dag_wait:
            all_done = True
            attachments_parts: list[str] = []
            for dep_id in depends_on_job_ids:
                dep = get_job(dep_id)
                if not dep:
                    continue
                if dep['status'] not in ('done',):
                    all_done = False
                    break
                # 완료된 선행 Job 산출물을 attachments에 추가
                arts = dep.get('artifacts') or {}
                for k, v in arts.items():
                    if v:
                        attachments_parts.append(f'[선행 Job {dep_id} — {k}]\n{str(v)[:1000]}')
            if all_done:
                if attachments_parts and not attachments_text:
                    attachments_text = '\n\n'.join(attachments_parts)[:3000]
                break
            await asyncio.sleep(5.0)
            dag_waited += 5.0

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

    # Haiku 잡 플래너: 실행할 스텝 목록·순서 결정 (신규 잡만)
    if not is_resume:
        try:
            from jobs.job_planner import plan_job
            planned_ids = await plan_job(spec, job.input)
            step_map = {s.id: s for s in spec.steps}
            planned_steps = [step_map[sid] for sid in planned_ids if sid in step_map]
            update_job(job.id, planned_steps=planned_ids)
            await emit(
                f'📋 실행 계획: {", ".join(planned_ids)}',
                'job_planned',
                {'planned_steps': planned_ids},
            )
        except Exception as _pe:
            logger.warning('[job_planner] 플래너 실패, 전체 스텝 실행: %s', _pe)
            planned_steps = spec.steps
    else:
        planned_steps = spec.steps

    try:
        for step in planned_steps:
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

            # Haiku 동적 설정: persona/skills/tools 자동 선택 (spec 힌트 우선)
            from jobs.step_configurator import configure_step
            step = await configure_step(step, context)

            await emit(f'▶ Step: {step.id}', 'job_step_started',
                       {'step_id': step.id, 'tier': step.tier,
                        'persona': step.persona, 'skills': step.skills})

            step_run = await _run_step(job.id, step, context)
            # Haiku가 결정한 persona/skills/tools를 step_run에 기록
            step_run.persona = step.persona
            step_run.skills = step.skills
            step_run.tools = step.tools
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
            job_row = get_job(job.id) or {}
            artifacts = json_loads(job_row, 'artifacts')
            artifact_kinds = json_loads(job_row, 'artifact_kinds')
            output_key = step.output_key or step.id
            artifacts[output_key] = step_run.output

            # artifact_kinds 결정 — output_format 명시 시 우선 적용
            requested_fmt = str(job.input.get('output_format', '')).lower().strip()
            if requested_fmt in ('html',) and output_key in ('report', 'brief', 'plan', 'insights', 'analysis'):
                artifact_kinds[output_key] = 'html'
            else:
                artifact_kinds[output_key] = _resolve_artifact_kind(output_key)

            # palette_svg 후처리 훅: JSON → SVG 자동 생성
            if step.output_key == 'palette_svg':
                artifacts = _postprocess_palette_svg(
                    step_run.output, artifacts, job.id
                )

            # html_validation 후처리 훅: preview_html에서 HTML 추출 → axe 검증
            if step.output_key == 'html_validation':
                artifacts, context = await _postprocess_html_validation(
                    artifacts, context, job.id, emit
                )

            # screenshots 후처리 훅: preview_html에서 HTML 추출 → 3-viewport 스크린샷
            if step.output_key == 'screenshots':
                artifacts, context = await _postprocess_screenshots(
                    artifacts, context, job.id, emit
                )

            # bundle_files 후처리 훅: JSON → ZIP 생성
            if step.output_key == 'bundle_files':
                zip_path = _postprocess_bundle_zip(step_run.output, job.id)
                if zip_path:
                    artifacts['bundle_zip'] = zip_path
                    artifact_kinds['bundle_zip'] = 'zip'

            # visual_mockup 후처리 훅: stitch html_path → html artifact 저장
            if step.output_key == 'visual_mockup':
                artifacts, context = _postprocess_visual_mockup(
                    step_run.output, artifacts, context, artifact_kinds, job.id
                )

            update_job(job.id, artifacts=artifacts, artifact_kinds=artifact_kinds)

            # 품질 메트릭 훅: report/summary/brief output_key이면 측정
            if output_key in ('report', 'summary', 'brief') and step_run.output:
                try:
                    from improvement.metrics import measure_artifact_quality, save_artifact_quality
                    aq = measure_artifact_quality(job.id, output_key, step_run.output)
                    save_artifact_quality(aq)
                    logger.debug('[quality] %s/%s → overall=%.1f', job.id, output_key, aq.overall)
                except Exception as _qe:
                    logger.warning('[quality] 측정 실패: %s', _qe)

            await emit(f'✅ Step 완료: {step.id}', 'job_step_done',
                       {'step_id': step.id, 'output_len': len(step_run.output)})

            # Gate 체크
            if gate:
                # auto_approve_if 조건 평가 (P1)
                if gate.auto_approve_if and _eval_gate_condition(gate.auto_approve_if, context):
                    gate_run = GateRun(job_id=job.id, gate_id=gate.id, status='approved')
                    open_gate(gate_run)
                    decide_gate(job.id, gate.id, 'approved', f'auto-approve: {gate.auto_approve_if}')
                    await emit(f'⚡ Gate 자동 승인 (조건 충족): {gate.id}', 'job_gate_approved')
                    continue

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

        # 교차 리뷰 훅 — done 전환 후 비동기 수행 (Job 성공에 영향 없음)
        try:
            final_job_row = get_job(job.id) or {}
            final_artifacts = json_loads(final_job_row, 'artifacts')
            final_artifact_kinds = json_loads(final_job_row, 'artifact_kinds')

            from jobs.cross_review import cross_review_job, format_cross_review_markdown
            review = await cross_review_job(job, final_artifacts)
            if review:
                md = format_cross_review_markdown(review)
                final_artifacts['cross_review'] = md
                final_artifact_kinds['cross_review'] = 'markdown'
                update_job(job.id, artifacts=final_artifacts, artifact_kinds=final_artifact_kinds)
                await emit(
                    f'교차 리뷰 완료 (reviewer={review["reviewer"]}, score={review["score"]})',
                    'job_cross_review_done',
                    {'reviewer': review['reviewer'], 'score': review['score']},
                )
        except Exception as _cr_err:
            logger.warning('[cross_review] 훅 오류 (무시): %s', _cr_err)

    except asyncio.CancelledError:
        # 모든 스텝이 이미 완료된 경우 (gate 대기 중 취소) → done 처리
        try:
            from db.job_store import get_steps as _check_steps
            done_ids = {s['step_id'] for s in _check_steps(job.id) if s['status'] == 'done'}
            if all(s.id in done_ids for s in spec.steps):
                total_cost = sum(s.get('cost_usd', 0.0) for s in _check_steps(job.id))
                update_job(job.id, status='done',
                           finished_at=datetime.now(timezone.utc).isoformat(),
                           current_step='', total_cost_usd=round(total_cost, 6))
            else:
                update_job(job.id, status='failed', error='취소됨')
        except Exception:
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

            # step 재실행 — revision_prompt가 있으면 부분 수정 프롬프트 사용 (2-3)
            step_run = await _run_step(job_id, step, context, is_revision=True)
            step_run.revised = prev_revised + 1
            step_run.revision_feedback = fb
            upsert_step(step_run)
            if step.output_key:
                context[step.output_key] = step_run.output

            rev_job_row = get_job(job_id) or {}
            artifacts = json_loads(rev_job_row, 'artifacts')
            artifact_kinds = json_loads(rev_job_row, 'artifact_kinds')
            rev_output_key = step.output_key or step.id
            artifacts[rev_output_key] = step_run.output
            artifact_kinds[rev_output_key] = _resolve_artifact_kind(rev_output_key)
            update_job(job_id, artifacts=artifacts, artifact_kinds=artifact_kinds)

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


async def _run_step(
    job_id: str, step: StepSpec, context: dict[str, str], is_revision: bool = False
) -> StepRun:
    """단일 Step 실행 — 프롬프트를 채우고 model_router로 호출한다.

    Args:
        is_revision: True이면 revision_prompt_template 우선 사용 (2-3)
    """
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
        # inputs 필드로 선택적 컨텍스트 주입 (P1)
        effective_context = context
        if step.inputs:
            effective_context = {k: v for k, v in context.items()
                                 if k in step.inputs or k.startswith('_')}

        # 수정 재실행: revision_prompt_template이 있으면 사용 (2-3)
        if is_revision and step.revision_prompt_template:
            prompt = _fill(step.revision_prompt_template, effective_context)
        else:
            prompt = _fill(step.prompt_template, effective_context)

        if step.tools:
            tool_results = await _run_tools(step.tools, effective_context)
            if tool_results:
                prompt = prompt + '\n\n[수집된 참고 자료]\n' + tool_results

        attachments = context.get('_attachments', '')
        if attachments:
            prompt = prompt + '\n\n[사용자 첨부 참조 자료 — 작업 시 반드시 반영]\n' + attachments

        # output_format 지시 주입 — html 요청 시 리포트 스텝에 HTML 마크업 생성 지시
        requested_fmt = str(context.get('output_format', '')).lower().strip()
        if requested_fmt == 'html' and step.output_key in ('report', 'brief', 'plan', 'insights', 'analysis'):
            prompt = prompt + (
                '\n\n[출력 형식]\n'
                '결과물을 완전한 HTML 문서로 작성하세요. '
                '<!DOCTYPE html>부터 시작하는 self-contained HTML이어야 합니다. '
                '스타일은 인라인 또는 <style> 태그로 포함하세요.'
            )

        # 페르소나 + 스킬 + 기존 system_prompt 3-레이어 합성
        from jobs.prompt_composer import compose_system_prompt
        system = compose_system_prompt(step) or step.system_prompt

        text, model_used = await model_router.run(
            tier=step.tier,
            prompt=prompt,
            system=system,
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


async def _postprocess_html_validation(
    artifacts: dict,
    context: dict[str, str],
    job_id: str,
    emit: Any,
) -> tuple[dict, dict[str, str]]:
    """html_validation step 완료 후 실제 axe-core 검증을 수행하는 후처리 훅."""
    import re as _re

    html_raw = artifacts.get('preview_html') or context.get('preview_html') or ''

    m = _re.search(r'```html\s*([\s\S]+?)```', html_raw, _re.IGNORECASE)
    html = m.group(1).strip() if m else html_raw.strip()

    if not html:
        logger.warning('[html_validation] preview_html 없음 — 후처리 건너뜀')
        return artifacts, context

    try:
        from harness.html_tools import validate_html
        await emit('HTML 검증 중 (axe-core)...', 'job_event')
        result = await validate_html(html)
    except Exception as e:
        logger.warning('[html_validation] validate_html 실패: %s', e)
        result = {'structure': None, 'a11y': None, 'score': 0, 'error': str(e)}

    lines: list[str] = ['## HTML 검증 결과']
    score = result.get('score', 0)
    error = result.get('error')
    if error:
        lines.append(f'\n> 검증 오류: {error}')

    structure = result.get('structure') or {}
    if structure:
        lines.append('\n### 기본 구조')
        checks = [
            ('DOCTYPE 선언', structure.get('has_doctype')),
            ('lang 속성', structure.get('has_lang')),
            ('viewport meta', structure.get('has_viewport')),
            ('title 태그', structure.get('has_title')),
            ('h1 태그', structure.get('has_h1')),
        ]
        for label, ok in checks:
            icon = '[OK]' if ok else '[X]'
            lines.append(f'- {icon} {label}')
        empty_alt = structure.get('empty_alt_count', 0)
        if empty_alt:
            lines.append(f'- [!] 빈 alt 이미지: {empty_alt}개')

    a11y = result.get('a11y') or {}
    if a11y:
        lines.append('\n### 접근성 (axe-core)')
        lines.append(f'- 위반 항목: {a11y.get("violation_count", 0)}개')
        lines.append(f'- 통과 항목: {a11y.get("passes", 0)}개')
        violations = a11y.get('violations') or []
        if violations:
            lines.append('\n#### 위반 목록')
            for v in violations:
                impact = v.get('impact', '')
                vid = v.get('id', '')
                desc = v.get('description', '')
                count = v.get('count', 0)
                lines.append(f'- **{vid}** ({impact}) — {desc} [{count}개 노드]')

    lines.append(f'\n**종합 점수: {score} / 100**')
    report = '\n'.join(lines)
    artifacts['html_validation'] = report
    context['html_validation'] = report
    await emit(f'HTML 검증 완료 (점수: {score}/100)', 'job_event')
    return artifacts, context


async def _postprocess_screenshots(
    artifacts: dict,
    context: dict[str, str],
    job_id: str,
    emit: Any,
) -> tuple[dict, dict[str, str]]:
    """screenshots step 완료 후 실제 3-viewport 스크린샷을 촬영하는 후처리 훅."""
    import re as _re
    import os as _os
    import tempfile as _tempfile

    html_raw = artifacts.get('preview_html') or context.get('preview_html') or ''

    m = _re.search(r'```html\s*([\s\S]+?)```', html_raw, _re.IGNORECASE)
    html = m.group(1).strip() if m else html_raw.strip()

    if not html:
        logger.warning('[screenshots] preview_html 없음 — 후처리 건너뜀')
        return artifacts, context

    output_dir = _os.path.join(_tempfile.gettempdir(), 'ai_office_screenshots', job_id)

    try:
        from harness.html_tools import screenshot_html
        await emit('스크린샷 촬영 중 (3 viewports)...', 'job_event')
        result = await screenshot_html(html, output_dir, job_id)
    except Exception as e:
        logger.warning('[screenshots] screenshot_html 실패: %s', e)
        result = {'screenshots': None, 'error': str(e)}

    lines: list[str] = ['## 스크린샷']
    error = result.get('error')
    if error:
        lines.append(f'\n> 스크린샷 오류: {error}')
    shots = result.get('screenshots') or {}
    for vp in ('mobile', 'tablet', 'desktop'):
        path_val = shots.get(vp, '')
        if path_val:
            lines.append(f'- **{vp}**: `{path_val}`')

    report = '\n'.join(lines)
    artifacts['screenshots'] = report
    context['screenshots'] = report
    if shots:
        await emit(f'스크린샷 촬영 완료 ({len(shots)}개)', 'job_event')
    return artifacts, context


def _postprocess_palette_svg(
    raw_output: str,
    artifacts: dict,
    job_id: str,
) -> dict:
    """palette_svg step 완료 후 SVG를 자동 생성하는 후처리 훅.

    1. LLM 출력(JSON)을 파싱
    2. color_utils.generate_palette_svg() 호출
    3. artifacts['palette_svg']에 SVG 덮어씀
    4. WCAG 경고가 있으면 artifacts['palette_wcag_warnings']에 저장
    """
    import json as _json
    try:
        from harness.color_utils import (
            extract_hex_colors,
            generate_palette_svg,
            collect_wcag_warnings,
        )
    except ImportError:
        logger.warning('[palette_svg] harness.color_utils import 실패, 후처리 건너뜀')
        return artifacts

    # JSON 파싱 (마크다운 코드 블록 감싸진 경우 처리)
    text = raw_output.strip()
    # ```json ... ``` 또는 ``` ... ``` 제거
    import re as _re
    text = _re.sub(r'^```[a-z]*\n?', '', text, flags=_re.MULTILINE)
    text = _re.sub(r'```$', '', text, flags=_re.MULTILINE)
    text = text.strip()

    try:
        data = _json.loads(text)
    except Exception:
        # JSON 파싱 실패 시 텍스트에서 HEX 직접 추출
        logger.warning('[palette_svg] JSON 파싱 실패, HEX 직접 추출로 대체')
        colors = extract_hex_colors(raw_output)
        title = '색상 팔레트'
        data = {}
    else:
        title = data.get('title', '색상 팔레트')
        color_entries = data.get('colors', [])
        if isinstance(color_entries, list):
            colors = [
                entry.get('hex', '') if isinstance(entry, dict) else str(entry)
                for entry in color_entries
            ]
            colors = [c for c in colors if c]
        else:
            colors = extract_hex_colors(raw_output)

    if not colors:
        logger.warning('[palette_svg] 색상 추출 결과 없음, 후처리 건너뜀')
        return artifacts

    try:
        svg = generate_palette_svg(colors, title=title)
        artifacts['palette_svg'] = svg

        warnings = collect_wcag_warnings(colors)
        if warnings:
            artifacts['palette_wcag_warnings'] = warnings
            logger.info('[palette_svg] WCAG 경고 %d건: %s', len(warnings), warnings)
        else:
            artifacts.pop('palette_wcag_warnings', None)

        logger.info('[palette_svg] SVG 생성 완료 (색상 %d개, %d bytes)',
                    len(colors), len(svg))
    except Exception as e:
        logger.error('[palette_svg] SVG 생성 실패: %s', e)

    return artifacts


def _postprocess_visual_mockup(
    step_output: str,
    artifacts: dict,
    context: dict[str, str],
    artifact_kinds: dict,
    job_id: str,
) -> tuple[dict, dict[str, str]]:
    """visual_mockup step 완료 후 stitch html_path를 읽어 artifact로 저장하는 후처리 훅.

    step_output(LLM 응답)에서 stitch_generate 결과의 html_path를 찾아:
    - artifact_kinds['visual_mockup'] = 'html'
    - artifacts['visual_mockup_preview'] = HTML 파일 내용
    """
    import re as _re

    # stitch_generate 도구 결과에서 html_path 추출
    # 형식: "HTML 시안: /path/to/file.html"
    html_path = ''
    m = _re.search(r'HTML 시안:\s*(\S+\.html)', step_output)
    if m:
        html_path = m.group(1).strip()

    if not html_path:
        logger.debug('[visual_mockup] html_path 없음 — visual_mockup_preview 건너뜀')
        return artifacts, context

    artifact_kinds['visual_mockup'] = 'html'

    try:
        from pathlib import Path as _Path
        html_content = _Path(html_path).read_text(encoding='utf-8')
        artifacts['visual_mockup_preview'] = html_content
        context['visual_mockup_preview'] = html_content[:3000]
        logger.info('[visual_mockup] HTML 저장 완료: %s (%d bytes)', html_path, len(html_content))
    except Exception as e:
        logger.warning('[visual_mockup] HTML 읽기 실패: %s — %s', html_path, e)
        artifacts['visual_mockup_preview'] = f'[HTML 읽기 실패: {e}]'

    return artifacts, context


def _resolve_artifact_kind(output_key: str) -> str:
    """output_key로 artifact kind를 결정한다."""
    if output_key == 'palette_svg':
        return 'svg'
    if output_key in ('preview_html', 'visual_mockup'):
        return 'html'
    if 'diagram' in output_key:
        return 'mermaid'
    if output_key == 'bundle_zip':
        return 'zip'
    if output_key == 'screenshots':
        return 'image'
    return 'markdown'


def _postprocess_bundle_zip(raw_output: str, job_id: str) -> str | None:
    """bundle_files step 완료 후 ZIP 파일을 생성하는 후처리 훅.

    1. LLM 출력(JSON)에서 files 배열 추출
    2. workspace/{job_id}/bundle/ 디렉토리 생성 후 각 파일 쓰기
    3. ZIP으로 묶기 → workspace/{job_id}/bundle.zip
    4. zip 파일 경로 반환 (실패 시 None)
    """
    # workspace 경로 설정
    workspace = Path(__file__).parent.parent / 'workspace' / job_id
    bundle_dir = workspace / 'bundle'

    # JSON 파싱 (마크다운 코드 블록 처리)
    text = raw_output.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        # 첫/마지막 ``` 제거
        inner = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
        text = inner.strip()

    try:
        data = json.loads(text)
    except Exception:
        # JSON 블록 추출 시도
        import re
        m = re.search(r'\{[\s\S]*\}', text)
        if not m:
            logger.error('[bundle_zip] JSON 파싱 실패: %s…', text[:200])
            return None
        try:
            data = json.loads(m.group())
        except Exception as e:
            logger.error('[bundle_zip] JSON 파싱 실패: %s', e)
            return None

    files = data.get('files', [])
    if not files:
        logger.warning('[bundle_zip] files 배열이 비어 있음')
        return None

    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # 각 파일 쓰기
        for f in files:
            fname = f.get('name', '')
            content = f.get('content', '')
            if not fname:
                continue
            # 보안: 경로 이탈 방지
            fpath = (bundle_dir / fname).resolve()
            if not str(fpath).startswith(str(bundle_dir.resolve())):
                logger.warning('[bundle_zip] 경로 이탈 시도 차단: %s', fname)
                continue
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding='utf-8')

        # ZIP 생성
        zip_path = workspace / 'bundle.zip'
        with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                fname = f.get('name', '')
                if not fname:
                    continue
                fpath = bundle_dir / fname
                if fpath.exists():
                    arcname = f'{data.get("package_name", "bundle")}/{fname}'
                    zf.write(str(fpath), arcname)

        logger.info('[bundle_zip] ZIP 생성 완료: %s (%d개 파일)', zip_path, len(files))
        return str(zip_path)

    except Exception as e:
        logger.error('[bundle_zip] ZIP 생성 실패: %s', e)
        return None


def _fill(template: str, context: dict[str, str]) -> str:
    """템플릿의 {key}를 context 값으로 치환한다.

    값이 비어있는 키는 치환 후 해당 줄 전체(레이블 포함)를 제거해
    모델이 빈 항목을 보고 혼동하거나 없는 내용을 지어내는 것을 방지한다.
    """
    import re
    result = template
    for k, v in context.items():
        result = result.replace('{' + k + '}', str(v))
    # 미치환 placeholder 제거
    result = re.sub(r'\{[a-z_]+\}', '', result)
    # 빈 값으로 치환된 줄 제거: "레이블: " 또는 "레이블:" 뒤에 아무것도 없는 줄
    result = re.sub(r'^[^\n]*:\s*$', '', result, flags=re.MULTILINE)
    # 연속 빈 줄 정리
    result = re.sub(r'\n{3,}', '\n\n', result)
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


def _eval_gate_condition(condition: str, context: dict[str, str]) -> bool:
    """auto_approve_if 조건식을 평가한다.

    지원 형식:
    - "{key} contains {text}" — context[key]에 text 포함 여부
    - "{key} equals {text}"   — context[key] == text
    - "{key} not_empty"       — context[key]가 비어있지 않음
    """
    try:
        cond = condition.strip()
        if ' contains ' in cond:
            key, _, text = cond.partition(' contains ')
            return text.strip().lower() in (context.get(key.strip()) or '').lower()
        elif ' equals ' in cond:
            key, _, text = cond.partition(' equals ')
            return (context.get(key.strip()) or '').strip() == text.strip()
        elif cond.endswith(' not_empty'):
            key = cond[: -len(' not_empty')].strip()
            return bool(context.get(key))
    except Exception as e:
        logger.warning('[gate_condition] 평가 실패: %s — %s', condition, e)
    return False


async def _generate_title(spec, input_data: dict[str, Any], job_id: str) -> str:
    """Haiku로 잡 타이틀을 자동 생성한다. 실패 시 기본값 반환."""
    # 입력값에서 의미있는 내용 추출
    values = [str(v)[:200] for v in input_data.values() if v and str(v).strip()]
    if not values:
        return f'{spec.title} #{job_id[:6]}'

    hint = ' | '.join(values[:3])
    try:
        from runners import model_router
        raw, _ = await model_router.run(
            tier='nano',
            prompt=(
                f'다음 잡 요청에 어울리는 짧은 제목을 한국어로 지어주세요.\n'
                f'잡 종류: {spec.title}\n'
                f'입력 내용: {hint}\n\n'
                f'조건:\n'
                f'- 20자 이내\n'
                f'- 핵심 주제만 담을 것\n'
                f'- 제목만 출력 (설명, 따옴표 금지)'
            ),
            system='제목만 출력하세요.',
            agent_id=f'title_gen:{spec.id}',
            timeout=10.0,
        )
        title = raw.strip().strip('"').strip("'")[:40]
        return title if title else f'{spec.title} #{job_id[:6]}'
    except Exception:
        return f'{spec.title} #{job_id[:6]}'
