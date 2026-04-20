// Job Board — Job 목록 + 상세 뷰
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Job } from '../types'
import { MatIcon } from './icons'
import { JobDetailView } from './JobDetailView'
import { NewJobDialog } from './NewJobDialog'
import { PlaybookDialog } from './PlaybookDialog'

const DELETABLE_STATUSES = new Set(['done', 'cancelled', 'failed'])

async function fetchJobs(): Promise<Job[]> {
  const res = await fetch('/api/jobs?limit=100')
  if (!res.ok) throw new Error('Job 목록 로드 실패')
  return res.json()
}

const STATUS_TABS = [
  { key: 'all', label: '전체' },
  { key: 'running', label: '실행 중' },
  { key: 'waiting_gate', label: '게이트 대기' },
  { key: 'done', label: '완료' },
  { key: 'failed', label: '실패' },
] as const

const STATUS_STYLE: Record<string, { dot: string; bar: string; badge: string; label: string }> = {
  queued:       { dot: 'bg-slate-400', bar: 'bg-slate-400', badge: 'bg-slate-500/15 text-slate-500 dark:text-slate-400', label: '대기' },
  running:      { dot: 'bg-sky-500 animate-pulse', bar: 'bg-sky-500', badge: 'bg-sky-500/15 text-sky-700 dark:text-sky-300', label: '실행 중' },
  waiting_gate: { dot: 'bg-amber-500 animate-pulse', bar: 'bg-amber-500', badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300', label: '게이트 대기' },
  done:         { dot: 'bg-emerald-500', bar: 'bg-emerald-500', badge: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300', label: '완료' },
  failed:       { dot: 'bg-rose-500', bar: 'bg-rose-500', badge: 'bg-rose-500/15 text-rose-700 dark:text-rose-300', label: '실패' },
  cancelled:    { dot: 'bg-slate-500', bar: 'bg-slate-500', badge: 'bg-slate-500/15 text-slate-500 dark:text-slate-400', label: '취소됨' },
}

const SPEC_META: Record<string, { icon: string; tone: string }> = {
  research:         { icon: 'search',       tone: 'from-sky-500 to-blue-600' },
  planning:         { icon: 'account_tree', tone: 'from-indigo-500 to-violet-600' },
  design_direction: { icon: 'palette',      tone: 'from-pink-500 to-rose-600' },
  review:           { icon: 'rate_review',  tone: 'from-amber-500 to-orange-600' },
  publishing:       { icon: 'code',         tone: 'from-emerald-500 to-teal-600' },
  coding:           { icon: 'terminal',     tone: 'from-fuchsia-500 to-purple-600' },
}

function timeAgo(ts: string): string {
  if (!ts) return ''
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60) return `${Math.round(diff)}초 전`
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`
  return `${Math.floor(diff / 86400)}일 전`
}

function JobCard({
  job, isSelected, onClick, onDelete,
}: {
  job: Job; isSelected: boolean; onClick: () => void; onDelete: (e: React.MouseEvent) => void
}) {
  const s = STATUS_STYLE[job.status] ?? STATUS_STYLE.queued
  const meta = SPEC_META[job.spec_id] ?? { icon: 'work', tone: 'from-slate-500 to-slate-600' }
  const hasPendingGate = job.status === 'waiting_gate'
  const canDelete = DELETABLE_STATUSES.has(job.status)
  const isLive = job.status === 'running' || job.status === 'waiting_gate' || job.status === 'queued'

  // 완료 step 진행률
  const doneSteps = (job.steps || []).filter(st => st.status === 'done').length
  const totalSteps = (job.planned_steps || []).length || (job.steps || []).length
  const progress = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0

  return (
    <div
      className={`relative group w-full rounded-2xl transition-all duration-200
        ${isSelected
          ? 'bg-gradient-to-br from-indigo-50 to-white dark:from-indigo-950/40 dark:to-slate-900 ring-2 ring-indigo-400 dark:ring-indigo-500/60 shadow-lg shadow-indigo-500/10'
          : 'bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 hover:ring-slate-300 dark:hover:ring-slate-700 hover:-translate-y-0.5 hover:shadow-md'
        }`}
    >
      {/* 좌측 상태 컬러바 */}
      <span className={`absolute left-0 top-4 bottom-4 w-1 rounded-full ${s.bar} ${isLive ? 'animate-pulse' : ''}`} />

      <button onClick={onClick} className="w-full text-left cursor-pointer p-3.5 pl-4">
        <div className="flex items-start gap-3">
          {/* spec 아이콘 — gradient tone */}
          <div className={`relative w-10 h-10 rounded-xl flex items-center justify-center shrink-0
            bg-gradient-to-br ${meta.tone} shadow-md ring-1 ring-black/5`}>
            <MatIcon name={meta.icon} className="text-white text-[18px]" />
            {isLive && totalSteps > 0 && (
              <svg className="absolute -top-1 -right-1 w-5 h-5" viewBox="0 0 20 20">
                <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor"
                        className="text-white/40 dark:text-slate-900/80" strokeWidth="2" />
                <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor"
                        className="text-indigo-500" strokeWidth="2" strokeLinecap="round"
                        strokeDasharray={`${(progress/100) * 50.27} 50.27`}
                        transform="rotate(-90 10 10)" />
              </svg>
            )}
          </div>

          <div className="flex-1 min-w-0 pr-6">
            <div className="flex items-start justify-between gap-1">
              <p className={`text-[13.5px] font-semibold leading-snug line-clamp-2
                ${isSelected ? 'text-indigo-700 dark:text-indigo-300' : 'text-slate-900 dark:text-slate-100'}`}>
                {job.title}
              </p>
              {hasPendingGate && (
                <MatIcon name="pending_actions" className="text-[16px] text-amber-500 shrink-0 mt-0.5 animate-bounce" />
              )}
            </div>

            <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
              <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${s.badge}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                {s.label}
              </span>
              <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">{job.spec_id}</span>
              {totalSteps > 0 && (
                <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">
                  {doneSteps}/{totalSteps}
                </span>
              )}
            </div>

            <div className="flex items-center justify-between mt-2">
              {job.current_step && isLive ? (
                <p className="text-[11px] text-slate-600 dark:text-slate-400 truncate font-medium flex items-center gap-1">
                  <MatIcon name="play_arrow" className="text-[12px] text-indigo-500" />
                  {job.current_step}
                </p>
              ) : (
                <span />
              )}
              <p className="text-[10px] text-slate-400 dark:text-slate-500 shrink-0">{timeAgo(job.created_at)}</p>
            </div>
          </div>
        </div>
      </button>

      {/* 삭제 버튼 — hover 시 표시 */}
      {canDelete && (
        <button
          onClick={onDelete}
          title="삭제"
          className="absolute top-2 right-2 p-1.5 rounded-lg opacity-0 group-hover:opacity-100
            text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20
            transition-all cursor-pointer"
        >
          <MatIcon name="delete_outline" className="text-[15px]" />
        </button>
      )}
    </div>
  )
}

interface NewJobValues {
  specId: string
  title: string
  fields: Record<string, string>
  sourceJob?: { id: string; title: string; specId: string; artifacts: Record<string, string> }
}

export function JobBoard({ onBack }: { onBack?: () => void }) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<string>('all')
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [showNewJob, setShowNewJob] = useState(false)
  const [newJobValues, setNewJobValues] = useState<NewJobValues | null>(null)
  const [showPlaybook, setShowPlaybook] = useState(false)

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
    refetchInterval: 3000,
  })

  const deleteJob = useMutation({
    mutationFn: async (jobId: string) => {
      const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('삭제 실패')
    },
    onSuccess: (_, jobId) => {
      if (selectedJobId === jobId) setSelectedJobId(null)
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const filtered = filter === 'all' ? jobs : jobs.filter(j => j.status === filter)

  const counts: Record<string, number> = {}
  for (const j of jobs) {
    counts[j.status] = (counts[j.status] || 0) + 1
  }
  return (
    <div className="flex-1 flex min-h-0 overflow-x-hidden bg-gray-50 dark:bg-gray-950">
      {/* 좌측: Job 목록 */}
      <div className={`flex flex-col border-r border-gray-200 dark:border-gray-800
        bg-white dark:bg-gray-950
        ${selectedJobId ? 'hidden md:flex md:w-80 lg:w-96' : 'flex w-full md:w-80 lg:w-96'}`}>

        {/* 헤더 */}
        <div className="px-4 md:px-5 py-3 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-1">
              {onBack && (
                <button
                  onClick={onBack}
                  className="md:hidden flex items-center justify-center w-8 h-8 -ml-1 mr-0.5
                    rounded-lg text-gray-500 dark:text-gray-400
                    hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors
                    touch-manipulation cursor-pointer"
                  aria-label="채팅으로 돌아가기"
                >
                  <MatIcon name="arrow_back_ios_new" className="text-[16px]" />
                </button>
              )}
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white">작업 보드</h2>
            </div>
            <div className="flex gap-1.5">
              <button
                onClick={() => setShowPlaybook(true)}
                className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium
                  text-purple-700 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/30
                  hover:bg-purple-200 dark:hover:bg-purple-900/50 rounded-lg transition-colors cursor-pointer"
                title="플레이북 — 여러 작업을 순서대로 자동 실행"
              >
                <MatIcon name="play_circle" className="text-[14px]" />
                플레이북
              </button>
              <button
                onClick={() => setShowNewJob(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white
                  bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors cursor-pointer"
              >
                <MatIcon name="add" className="text-[14px]" />
                새 Job
              </button>
            </div>
          </div>

          {/* 상태 필터 탭 */}
          <div className="flex gap-1 overflow-x-auto no-scrollbar">
            {STATUS_TABS.map(tab => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`shrink-0 px-2.5 py-1 text-[11px] font-medium rounded-lg transition-colors cursor-pointer
                  ${filter === tab.key
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
              >
                {tab.label}
                {tab.key !== 'all' && counts[tab.key] ? (
                  <span className={`ml-1 px-1 py-0.5 rounded-full text-[9px]
                    ${filter === tab.key ? 'bg-white/20' : 'bg-gray-200 dark:bg-gray-700'}`}>
                    {counts[tab.key]}
                  </span>
                ) : null}
                {tab.key === 'all' && jobs.length > 0 && (
                  <span className={`ml-1 px-1 py-0.5 rounded-full text-[9px]
                    ${filter === 'all' ? 'bg-white/20' : 'bg-gray-200 dark:bg-gray-700'}`}>
                    {jobs.length}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Job 목록 */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-gray-400">
              <MatIcon name="hourglass_empty" className="text-[32px]" />
            </div>
          )}

          {!isLoading && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <MatIcon name="work_outline" className="text-[40px] text-gray-300 dark:text-gray-700 mb-3" />
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {filter === 'all' ? '아직 Job이 없습니다' : `${filter} 상태의 Job이 없습니다`}
              </p>
              {filter === 'all' && (
                <button
                  onClick={() => setShowNewJob(true)}
                  className="mt-3 px-4 py-2 text-sm text-blue-600 dark:text-blue-400
                    hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors cursor-pointer"
                >
                  첫 Job 시작하기
                </button>
              )}
            </div>
          )}

          {filtered.map(job => (
            <JobCard
              key={job.id}
              job={job}
              isSelected={selectedJobId === job.id}
              onClick={() => setSelectedJobId(job.id)}
              onDelete={e => {
                e.stopPropagation()
                deleteJob.mutate(job.id)
              }}
            />
          ))}
        </div>
      </div>

      {/* 우측: Job 상세 */}
      {selectedJobId ? (
        <div className="flex-1 flex flex-col min-h-0 min-w-0 overflow-x-hidden">
          <JobDetailView
            jobId={selectedJobId}
            onClose={() => setSelectedJobId(null)}
            onDuplicate={job => {
              setNewJobValues({
                specId: job.spec_id,
                title: `${job.title} (복제)`,
                fields: job.input ?? {},
              })
              setShowNewJob(true)
            }}
            onChain={job => {
              setNewJobValues({
                specId: '',
                title: '',
                fields: {},
                sourceJob: {
                  id: job.id,
                  title: job.title,
                  specId: job.spec_id,
                  artifacts: job.artifacts ?? {},
                },
              })
              setShowNewJob(true)
            }}
          />
        </div>
      ) : (
        <div className="hidden md:flex flex-1 items-center justify-center text-center p-8">
          <div>
            <MatIcon name="work_outline" className="text-[48px] text-gray-300 dark:text-gray-700 mb-3" />
            <p className="text-sm text-gray-500 dark:text-gray-400">Job을 선택하면 상세 내용이 표시됩니다</p>
          </div>
        </div>
      )}

      {/* 새 Job 다이얼로그 */}
      {showNewJob && (
        <NewJobDialog
          onClose={() => { setShowNewJob(false); setNewJobValues(null) }}
          initialValues={newJobValues ?? undefined}
        />
      )}

      {/* Playbook 다이얼로그 */}
      {showPlaybook && (
        <PlaybookDialog onClose={() => setShowPlaybook(false)} />
      )}
    </div>
  )
}
