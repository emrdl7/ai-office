// Job 상세 뷰 — 스텝 타임라인 + Gate 컨트롤 + 아티팩트
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Job } from '../types'
import { MatIcon } from './icons'

async function fetchJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`)
  if (!res.ok) throw new Error('Job 로드 실패')
  return res.json()
}

const STATUS_LABEL: Record<string, { text: string; cls: string; icon: string }> = {
  queued: { text: '대기', cls: 'bg-gray-500/20 text-gray-400', icon: 'schedule' },
  running: { text: '실행 중', cls: 'bg-blue-500/20 text-blue-400', icon: 'play_circle' },
  waiting_gate: { text: 'Gate 대기', cls: 'bg-yellow-500/20 text-yellow-500', icon: 'pending' },
  done: { text: '완료', cls: 'bg-green-500/20 text-green-500', icon: 'check_circle' },
  failed: { text: '실패', cls: 'bg-red-500/20 text-red-500', icon: 'error' },
  cancelled: { text: '취소됨', cls: 'bg-gray-500/20 text-gray-500', icon: 'cancel' },
}

const STEP_STATUS_ICON: Record<string, { icon: string; cls: string }> = {
  queued: { icon: 'radio_button_unchecked', cls: 'text-gray-400' },
  running: { icon: 'pending', cls: 'text-blue-400 animate-pulse' },
  done: { icon: 'check_circle', cls: 'text-green-500' },
  failed: { icon: 'cancel', cls: 'text-red-500' },
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

function ArtifactPanel({ artifact }: { artifact: string }) {
  const [expanded, setExpanded] = useState(false)
  const preview = artifact.slice(0, 300)
  const needsExpand = artifact.length > 300

  return (
    <div className="mt-2 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
      {expanded ? artifact : preview}
      {needsExpand && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="block mt-1 text-blue-500 hover:underline cursor-pointer"
        >
          {expanded ? '접기' : `... 더 보기 (${artifact.length}자)`}
        </button>
      )}
    </div>
  )
}

function GateControl({ job, gate }: { job: Job; gate: NonNullable<Job['gates']>[number] }) {
  const qc = useQueryClient()
  const [feedback, setFeedback] = useState('')
  const [showFeedback, setShowFeedback] = useState(false)

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
      setShowFeedback(false)
    },
  })

  if (gate.status !== 'pending') return null

  return (
    <div className="mt-3 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-xl border border-yellow-200 dark:border-yellow-700/40">
      <div className="flex items-start gap-2 mb-2">
        <MatIcon name="pending" className="text-yellow-500 text-[18px] mt-0.5" />
        <div className="flex-1">
          <p className="text-xs font-semibold text-yellow-700 dark:text-yellow-400">Gate 승인 필요</p>
          <p className="text-xs text-yellow-600 dark:text-yellow-500 mt-0.5">{gate.prompt}</p>
        </div>
      </div>

      {showFeedback && (
        <textarea
          rows={3}
          value={feedback}
          onChange={e => setFeedback(e.target.value)}
          placeholder="피드백 내용 입력 (수정 요청 또는 거절 이유)"
          className="w-full mt-2 px-3 py-2 text-xs rounded-lg border border-yellow-200 dark:border-yellow-700
            bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none
            focus:outline-none focus:ring-2 focus:ring-yellow-500/50"
        />
      )}

      <div className="flex gap-2 mt-2">
        <button
          onClick={() => decide.mutate('approved')}
          disabled={decide.isPending}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-white bg-green-600 hover:bg-green-700
            rounded-lg transition-colors cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="check" className="text-[14px] mr-1" />
          승인
        </button>
        <button
          onClick={() => { setShowFeedback(true); if (feedback) decide.mutate('revised') }}
          disabled={decide.isPending}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-yellow-700 dark:text-yellow-400
            bg-yellow-100 dark:bg-yellow-900/30 hover:bg-yellow-200 dark:hover:bg-yellow-900/50
            rounded-lg transition-colors cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="edit" className="text-[14px] mr-1" />
          {showFeedback && feedback ? '수정 요청' : '피드백'}
        </button>
        <button
          onClick={() => decide.mutate('rejected')}
          disabled={decide.isPending}
          className="px-3 py-1.5 text-xs font-medium text-red-600 dark:text-red-400
            bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30
            rounded-lg transition-colors cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="close" className="text-[14px]" />
        </button>
      </div>
      {decide.isError && (
        <p className="text-xs text-red-500 mt-1">
          {decide.error instanceof Error ? decide.error.message : '오류'}
        </p>
      )}
    </div>
  )
}

export function JobDetailView({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [showArtifacts, setShowArtifacts] = useState(false)

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
          </div>
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => setShowArtifacts(!showArtifacts)}
            className={`p-1.5 rounded-lg text-sm transition-colors cursor-pointer
              ${showArtifacts ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'}`}
            title="아티팩트 보기"
          >
            <MatIcon name="description" className="text-[18px]" />
          </button>
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
            <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
              실행 단계
            </h3>
            <div className="space-y-2">
              {job.steps?.map((step, idx) => {
                const s = STEP_STATUS_ICON[step.status] ?? STEP_STATUS_ICON.queued
                const isActive = job.current_step === step.step_id && step.status === 'running'
                return (
                  <div key={step.step_id}
                    className={`flex gap-3 p-3 rounded-xl transition-colors
                      ${isActive ? 'bg-blue-50 dark:bg-blue-900/20' : 'bg-gray-50 dark:bg-gray-800/50'}`}>
                    {/* 연결선 */}
                    <div className="flex flex-col items-center">
                      <MatIcon name={s.icon} className={`text-[20px] ${s.cls}`} />
                      {idx < (job.steps?.length ?? 0) - 1 && (
                        <div className="w-px flex-1 mt-1 bg-gray-200 dark:bg-gray-700 min-h-[8px]" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium text-gray-900 dark:text-gray-100">
                          {step.step_id}
                        </span>
                        {step.started_at && (
                          <span className="text-[10px] text-gray-400 shrink-0">
                            {elapsed(step.started_at, step.finished_at || undefined)}
                          </span>
                        )}
                      </div>
                      {step.status === 'failed' && step.error && (
                        <p className="text-[11px] text-red-500 mt-1">{step.error}</p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Gates 목록 */}
          {job.gates && job.gates.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                검토 게이트
              </h3>
              <div className="space-y-2">
                {job.gates.map(gate => {
                  if (gate.status === 'pending') return <GateControl key={gate.gate_id} job={job} gate={gate} />
                  const gIcon = gate.status === 'approved' ? 'check_circle'
                    : gate.status === 'rejected' ? 'cancel'
                    : gate.status === 'not_reached' ? 'radio_button_unchecked'
                    : 'pending'
                  const gCls = gate.status === 'approved' ? 'text-green-500'
                    : gate.status === 'rejected' ? 'text-red-500'
                    : 'text-gray-400'
                  return (
                    <div key={gate.gate_id}
                      className="flex items-start gap-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-xl">
                      <MatIcon name={gIcon} className={`text-[18px] mt-0.5 ${gCls}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-gray-700 dark:text-gray-300">{gate.gate_id}</p>
                        <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">{gate.prompt}</p>
                        {gate.feedback && (
                          <p className="text-[11px] text-blue-500 mt-1 italic">"{gate.feedback}"</p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 아티팩트 */}
          {showArtifacts && job.artifacts && Object.keys(job.artifacts).length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                산출물
              </h3>
              <div className="space-y-3">
                {Object.entries(job.artifacts).map(([key, value]) => (
                  <div key={key}>
                    <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">{key}</p>
                    <ArtifactPanel artifact={value} />
                  </div>
                ))}
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
              <p className="text-xs text-red-500">{job.error}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
