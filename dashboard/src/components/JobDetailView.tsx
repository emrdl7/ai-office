// Job 상세 뷰 — 스텝 타임라인 + 출력물 뷰어 + Gate 컨트롤 + 아티팩트
import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import type { Job, JobStep } from '../types'
import { MatIcon } from './icons'

async function fetchJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`)
  if (!res.ok) throw new Error('Job 로드 실패')
  return res.json()
}

const STATUS_LABEL: Record<string, { text: string; cls: string; icon: string }> = {
  queued:       { text: '대기',      cls: 'bg-gray-500/20 text-gray-400',   icon: 'schedule' },
  running:      { text: '실행 중',   cls: 'bg-blue-500/20 text-blue-400',   icon: 'play_circle' },
  waiting_gate: { text: 'Gate 대기', cls: 'bg-yellow-500/20 text-yellow-500', icon: 'pending' },
  done:         { text: '완료',      cls: 'bg-green-500/20 text-green-500', icon: 'check_circle' },
  failed:       { text: '실패',      cls: 'bg-red-500/20 text-red-500',     icon: 'error' },
  cancelled:    { text: '취소됨',    cls: 'bg-gray-500/20 text-gray-500',   icon: 'cancel' },
}

const STEP_STATUS_ICON: Record<string, { icon: string; cls: string }> = {
  queued:  { icon: 'radio_button_unchecked', cls: 'text-gray-400' },
  running: { icon: 'pending',                cls: 'text-blue-400 animate-pulse' },
  done:    { icon: 'check_circle',           cls: 'text-green-500' },
  failed:  { icon: 'cancel',                 cls: 'text-red-500' },
}

function elapsed(start: string, end?: string): string {
  if (!start) return ''
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const sec = Math.round((e - s) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}

// 마크다운 출력 패널 — prose 스타일
function MarkdownViewer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none
      prose-headings:font-semibold prose-headings:text-gray-900 dark:prose-headings:text-gray-100
      prose-p:text-gray-700 dark:prose-p:text-gray-300
      prose-code:text-pink-600 dark:prose-code:text-pink-400
      prose-pre:bg-gray-100 dark:prose-pre:bg-gray-800
      prose-table:text-xs prose-th:bg-gray-100 dark:prose-th:bg-gray-800
      prose-a:text-blue-500">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}

// 스텝 카드 — 클릭하면 출력 내용 열림
function StepCard({
  step,
  isActive,
  isLast,
}: {
  step: JobStep
  isActive: boolean
  isLast: boolean
}) {
  const isRevised = (step.revised ?? 0) > 0
  // 수정된 step은 기본 펼침
  const [open, setOpen] = useState(isRevised)
  const s = STEP_STATUS_ICON[step.status] ?? STEP_STATUS_ICON.queued
  const hasOutput = step.status === 'done' && step.output
  const isCode = step.output?.includes('```html') || step.output?.includes('```css')

  // 다운로드 — step 출력물을 .md 파일로
  const download = useCallback(() => {
    const blob = new Blob([step.output], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${step.step_id}.md`
    a.click()
    URL.revokeObjectURL(url)
  }, [step])

  return (
    <div className={`rounded-xl border transition-all
      ${isRevised
        ? 'border-orange-300 dark:border-orange-700/60 bg-orange-50/30 dark:bg-orange-900/10'
        : isActive
          ? 'border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-900/10'
          : 'border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900'
      }`}>

      {/* 수정 이력 배너 */}
      {isRevised && (
        <div className="flex items-start gap-2 px-3 pt-2.5 pb-0">
          <MatIcon name="history" className="text-[13px] text-orange-500 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <span className="text-[10px] font-semibold text-orange-600 dark:text-orange-400">
              수정 {step.revised}회 — 아래가 최신 결과물입니다
            </span>
            {step.revision_feedback && (
              <p className="text-[10px] text-orange-500 dark:text-orange-500 mt-0.5 italic truncate">
                "{step.revision_feedback}"
              </p>
            )}
          </div>
        </div>
      )}

      {/* 헤더 행 */}
      <button
        onClick={() => hasOutput && setOpen(!open)}
        className={`w-full flex items-center gap-3 px-3 py-2.5
          ${hasOutput ? 'cursor-pointer' : 'cursor-default'}`}
      >
        <div className="flex flex-col items-center self-stretch">
          <MatIcon name={s.icon} className={`text-[20px] ${s.cls} shrink-0`} />
          {!isLast && <div className="w-px flex-1 mt-1 bg-gray-200 dark:bg-gray-700 min-h-[12px]" />}
        </div>

        <div className="flex-1 min-w-0 text-left">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-900 dark:text-gray-100 truncate">
              {step.step_id}
            </span>
            {isRevised && (
              <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full shrink-0
                bg-orange-100 dark:bg-orange-900/40 text-orange-600 dark:text-orange-400">
                수정됨 ×{step.revised}
              </span>
            )}
            {step.model_used && (
              <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full shrink-0
                ${step.model_used.includes('gemini') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                  : step.model_used.includes('opus') ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                  : step.model_used.includes('sonnet') ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                }`}>
                {step.model_used.replace('claude-', '').replace('-4-5-20251001', '').replace('-4-6', '')}
              </span>
            )}
            {step.started_at && (
              <span className="text-[10px] text-gray-400 shrink-0">
                {elapsed(step.started_at, step.finished_at || undefined)}
              </span>
            )}
            {hasOutput && (
              <span className="text-[9px] text-gray-400 shrink-0">
                {(step.output.length / 1000).toFixed(1)}k자
              </span>
            )}
          </div>
          {step.status === 'failed' && step.error && (
            <p className="text-[11px] text-red-500 mt-0.5">{step.error}</p>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {hasOutput && (
            <span
              onClick={e => { e.stopPropagation(); download() }}
              className="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer"
              title="다운로드"
            >
              <MatIcon name="download" className="text-[14px]" />
            </span>
          )}
          {hasOutput && (
            <MatIcon
              name={open ? 'expand_less' : 'expand_more'}
              className="text-[18px] text-gray-400"
            />
          )}
        </div>
      </button>

      {/* 출력 내용 */}
      {open && hasOutput && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-3 pb-3 pt-2 overflow-x-auto">
          {isCode ? (
            <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words overflow-auto max-h-[60vh]">
              {step.output}
            </pre>
          ) : (
            <div className="max-h-[60vh] overflow-y-auto">
              <MarkdownViewer content={step.output} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function GateControl({ job, gate }: { job: Job; gate: NonNullable<Job['gates']>[number] }) {
  const qc = useQueryClient()
  const [feedback, setFeedback] = useState('')

  const decide = useMutation({
    mutationFn: async (decision: 'approved' | 'rejected' | 'revised') => {
      const res = await fetch(`/api/jobs/${job.id}/gates/${gate.gate_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, feedback }),
      })
      if (!res.ok) throw new Error('결정 실패')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job', job.id] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['pending-gates'] })
      setFeedback('')
    },
  })

  // 수정 재실행 중
  if (gate.status === 'revising') {
    return (
      <div className="mt-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-200 dark:border-blue-700/40">
        <div className="flex items-center gap-2">
          <MatIcon name="autorenew" className="text-blue-500 text-[18px] animate-spin" />
          <div>
            <p className="text-xs font-semibold text-blue-700 dark:text-blue-400">피드백 반영 중 — Step 재실행</p>
            {gate.feedback && (
              <p className="text-[11px] text-blue-500 dark:text-blue-500 mt-0.5 italic">"{gate.feedback}"</p>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (gate.status !== 'pending') return null

  return (
    <div className="mt-3 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-xl border border-yellow-200 dark:border-yellow-700/40 space-y-2.5">
      {/* 헤더 */}
      <div className="flex items-start gap-2">
        <MatIcon name="pending" className="text-yellow-500 text-[18px] mt-0.5 shrink-0" />
        <div className="flex-1">
          <p className="text-xs font-semibold text-yellow-700 dark:text-yellow-400">Gate — 검토 필요</p>
          <p className="text-xs text-yellow-600 dark:text-yellow-500 mt-0.5">{gate.prompt}</p>
        </div>
      </div>

      {/* 피드백 입력 — 항상 표시 */}
      <textarea
        rows={2}
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        placeholder="수정 요청 시 피드백을 입력하세요 (예: 경쟁사 분석 섹션을 더 구체적으로)"
        className="w-full px-3 py-2 text-xs rounded-lg border border-yellow-200 dark:border-yellow-700
          bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none
          focus:outline-none focus:ring-2 focus:ring-yellow-400/50"
      />

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <button
          onClick={() => decide.mutate('approved')}
          disabled={decide.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white
            bg-green-600 hover:bg-green-700 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="check" className="text-[14px]" />
          승인
        </button>
        <button
          onClick={() => decide.mutate('revised')}
          disabled={decide.isPending || !feedback.trim()}
          title={!feedback.trim() ? '피드백을 먼저 입력하세요' : ''}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
            text-blue-700 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30
            hover:bg-blue-200 dark:hover:bg-blue-900/50 rounded-lg transition-colors
            cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <MatIcon name="refresh" className="text-[14px]" />
          수정 후 재검토
        </button>
        <button
          onClick={() => decide.mutate('rejected')}
          disabled={decide.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
            text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20
            hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors
            cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="cancel" className="text-[14px]" />
          거절
        </button>
      </div>
      {decide.isError && (
        <p className="text-xs text-red-500">
          {decide.error instanceof Error ? decide.error.message : '오류'}
        </p>
      )}
    </div>
  )
}

// 최종 리포트 전체 뷰 (모달)
function ReportModal({ title, content, onClose }: { title: string; content: string; onClose: () => void }) {
  const download = () => {
    const blob = new Blob([content], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-800">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate">{title}</h3>
          <div className="flex gap-2 shrink-0">
            <button onClick={download}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white
                bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700
                rounded-lg transition-colors cursor-pointer">
              <MatIcon name="download" className="text-[14px]" />
              다운로드
            </button>
            <button onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white
                hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
              <MatIcon name="close" className="text-[18px]" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <MarkdownViewer content={content} />
        </div>
      </div>
    </div>
  )
}

export function JobDetailView({
  jobId,
  onClose,
  onDuplicate,
  onChain,
}: {
  jobId: string
  onClose: () => void
  onDuplicate?: (job: Job) => void
  onChain?: (job: Job) => void    // 산출물 기반 다음 Job 시작
}) {
  const qc = useQueryClient()
  const [reportKey, setReportKey] = useState<string | null>(null)

  const { data: job, isLoading } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'running' || status === 'waiting_gate' || status === 'queued') return 2000
      return false
    },
  })

  const cancel = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('취소 실패')
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['job', jobId] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        <MatIcon name="hourglass_empty" className="text-[32px] animate-spin" />
      </div>
    )
  }

  if (!job) return null

  const status = STATUS_LABEL[job.status] ?? STATUS_LABEL.queued
  const pendingGate = job.gates?.find(g => g.status === 'pending')
  // 최종 리포트 키 찾기 (output_key='report'인 스텝)
  const reportKeys = ['report', 'brief', 'final_markup', 'insights']
  const finalKey = reportKeys.find(k => job.artifacts?.[k])

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-gray-950">
      {/* 헤더 */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-800">
        <button onClick={onClose}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white
            hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
          <MatIcon name="arrow_back" className="text-[18px]" />
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white truncate">{job.title}</h2>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${status.cls}`}>
              <MatIcon name={status.icon} className="text-[11px]" />
              {status.text}
            </span>
            <span className="text-[10px] text-gray-400">{job.spec_id}</span>
            {job.created_at && (
              <span className="text-[10px] text-gray-400">
                {new Date(job.created_at).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
            {job.status === 'done' && (job.total_cost_usd ?? 0) > 0 && (
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-mono">
                ${job.total_cost_usd.toFixed(4)}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          {finalKey && job.status === 'done' && (
            <button
              onClick={() => setReportKey(finalKey)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-white
                bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors cursor-pointer"
              title="최종 산출물 보기"
            >
              <MatIcon name="article" className="text-[14px]" />
              리포트
            </button>
          )}
          {onChain && job.status === 'done' && (
            <button
              onClick={() => onChain(job)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium
                text-purple-700 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/30
                hover:bg-purple-200 dark:hover:bg-purple-900/50 rounded-lg transition-colors cursor-pointer"
              title="이 Job의 산출물을 바탕으로 다음 Job 시작"
            >
              <MatIcon name="arrow_forward" className="text-[14px]" />
              다음 단계
            </button>
          )}
          {onDuplicate && (
            <button
              onClick={() => onDuplicate(job)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200
                hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer"
              title="입력값 복제로 새 Job 시작"
            >
              <MatIcon name="content_copy" className="text-[17px]" />
            </button>
          )}
          {(job.status === 'running' || job.status === 'queued' || job.status === 'waiting_gate') && (
            <button
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
              className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20
                transition-colors cursor-pointer disabled:opacity-50"
              title="취소"
            >
              <MatIcon name="stop_circle" className="text-[18px]" />
            </button>
          )}
        </div>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-y-auto">
        {/* Gate 알림 (최상단) */}
        {pendingGate && (
          <div className="m-4">
            <GateControl job={job} gate={pendingGate} />
          </div>
        )}

        <div className="p-4 space-y-5">
          {/* Steps 타임라인 */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                실행 단계
              </h3>
              <span className="text-[10px] text-gray-400">
                클릭하면 출력 내용 확인
              </span>
            </div>
            <div className="space-y-1.5">
              {job.steps?.map((step, idx) => (
                <StepCard
                  key={step.step_id}
                  step={step}
                  isActive={job.current_step === step.step_id && step.status === 'running'}
                  isLast={idx === (job.steps?.length ?? 0) - 1}
                />
              ))}
            </div>
          </div>

          {/* Gate 상태 목록 (pending 제외 — 위에서 처리) */}
          {job.gates && job.gates.some(g => g.status !== 'pending') && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                게이트 이력
              </h3>
              <div className="space-y-1.5">
                {job.gates.filter(g => g.status !== 'pending').map(gate => {
                  const gIcon = gate.status === 'approved' ? 'check_circle'
                    : gate.status === 'rejected' ? 'cancel'
                    : gate.status === 'not_reached' ? 'radio_button_unchecked'
                    : 'pending'
                  const gCls = gate.status === 'approved' ? 'text-green-500'
                    : gate.status === 'rejected' ? 'text-red-500'
                    : 'text-gray-400'
                  return (
                    <div key={gate.gate_id}
                      className="flex items-start gap-2 p-2.5 bg-gray-50 dark:bg-gray-800/50 rounded-xl">
                      <MatIcon name={gIcon} className={`text-[17px] mt-0.5 ${gCls}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-gray-700 dark:text-gray-300">{gate.gate_id}</p>
                        {gate.feedback && (
                          <p className="text-[11px] text-blue-500 mt-0.5 italic">"{gate.feedback}"</p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 입력값 */}
          {job.input && Object.keys(job.input).length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                입력값
              </h3>
              <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-3 space-y-2">
                {Object.entries(job.input).map(([k, v]) => (
                  <div key={k}>
                    <span className="text-[10px] font-semibold text-gray-400 uppercase">{k}</span>
                    <p className="text-xs text-gray-700 dark:text-gray-300 mt-0.5 whitespace-pre-wrap">{v}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 오류 */}
          {job.status === 'failed' && job.error && (
            <div className="bg-red-50 dark:bg-red-900/20 rounded-xl p-3">
              <p className="text-xs font-semibold text-red-600 dark:text-red-400 mb-1">오류</p>
              <p className="text-xs text-red-500 font-mono">{job.error}</p>
            </div>
          )}
        </div>
      </div>

      {/* 리포트 모달 */}
      {reportKey && job.artifacts?.[reportKey] && (
        <ReportModal
          title={`${job.title} — ${reportKey}`}
          content={job.artifacts[reportKey]}
          onClose={() => setReportKey(null)}
        />
      )}
    </div>
  )
}
