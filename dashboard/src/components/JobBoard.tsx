// Job Board — Job 목록 + 상세 뷰
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Job } from '../types'
import { MatIcon } from './icons'
import { JobDetailView } from './JobDetailView'
import { NewJobDialog } from './NewJobDialog'

const DELETABLE_STATUSES = new Set(['done', 'cancelled', 'failed'])

async function fetchJobs(): Promise<Job[]> {
  const res = await fetch('/api/jobs?limit=100')
  if (!res.ok) throw new Error('Job 목록 로드 실패')
  return res.json()
}

const STATUS_TABS = [
  { key: 'all', label: '전체' },
  { key: 'running', label: '실행 중' },
  { key: 'waiting_gate', label: 'Gate 대기' },
  { key: 'done', label: '완료' },
  { key: 'failed', label: '실패' },
] as const

const STATUS_STYLE: Record<string, { dot: string; badge: string; label: string }> = {
  queued:       { dot: 'bg-gray-400', badge: 'bg-gray-500/20 text-gray-400', label: '대기' },
  running:      { dot: 'bg-blue-400 animate-pulse', badge: 'bg-blue-500/20 text-blue-400', label: '실행 중' },
  waiting_gate: { dot: 'bg-yellow-400 animate-pulse', badge: 'bg-yellow-500/20 text-yellow-500', label: 'Gate 대기' },
  done:         { dot: 'bg-green-500', badge: 'bg-green-500/20 text-green-500', label: '완료' },
  failed:       { dot: 'bg-red-500', badge: 'bg-red-500/20 text-red-500', label: '실패' },
  cancelled:    { dot: 'bg-gray-500', badge: 'bg-gray-500/20 text-gray-500', label: '취소됨' },
}

const SPEC_ICONS: Record<string, string> = {
  research: 'search',
  planning: 'account_tree',
  design_direction: 'palette',
  review: 'rate_review',
  publishing: 'code',
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
  const hasPendingGate = job.status === 'waiting_gate'
  const canDelete = DELETABLE_STATUSES.has(job.status)

  return (
    <div
      className={`relative group w-full text-left px-3 py-3 rounded-xl transition-all
        ${isSelected
          ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800'
          : 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-blue-300 dark:hover:border-blue-700'
        }`}
    >
      <button onClick={onClick} className="w-full text-left cursor-pointer">
        <div className="flex items-start gap-2.5">
          {/* 아이콘 */}
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5
            ${isSelected ? 'bg-blue-500 text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'}`}>
            <MatIcon name={SPEC_ICONS[job.spec_id] || 'work'} className="text-[16px]" />
          </div>

          <div className="flex-1 min-w-0 pr-6">
            <div className="flex items-start justify-between gap-1">
              <p className={`text-sm font-medium leading-snug truncate
                ${isSelected ? 'text-blue-600 dark:text-blue-400' : 'text-gray-900 dark:text-gray-100'}`}>
                {job.title}
              </p>
              {hasPendingGate && (
                <MatIcon name="notification_important" className="text-[14px] text-yellow-500 shrink-0 mt-0.5" />
              )}
            </div>

            <div className="flex items-center gap-2 mt-1">
              <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${s.badge}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                {s.label}
              </span>
              <span className="text-[10px] text-gray-400 truncate">{job.spec_id}</span>
            </div>

            <div className="flex items-center justify-between mt-1">
              {job.current_step && (job.status === 'running' || job.status === 'waiting_gate') ? (
                <p className="text-[11px] text-gray-500 dark:text-gray-400 truncate">{job.current_step}</p>
              ) : (
                <span />
              )}
              <p className="text-[10px] text-gray-400 shrink-0">{timeAgo(job.created_at)}</p>
            </div>
          </div>
        </div>
      </button>

      {/* 삭제 버튼 — hover 시 표시, done/cancelled/failed만 */}
      {canDelete && (
        <button
          onClick={onDelete}
          title="삭제"
          className="absolute top-2 right-2 p-1 rounded-lg opacity-0 group-hover:opacity-100
            text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20
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

export function JobBoard() {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<string>('all')
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [showNewJob, setShowNewJob] = useState(false)
  const [newJobValues, setNewJobValues] = useState<NewJobValues | null>(null)

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
    <div className="flex-1 flex min-h-0 bg-gray-50 dark:bg-gray-950">
      {/* 좌측: Job 목록 */}
      <div className={`flex flex-col border-r border-gray-200 dark:border-gray-800
        bg-white dark:bg-gray-950
        ${selectedJobId ? 'hidden md:flex md:w-80 lg:w-96' : 'flex w-full md:w-80 lg:w-96'}`}>

        {/* 헤더 */}
        <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Job Board</h2>
            <button
              onClick={() => setShowNewJob(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white
                bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors cursor-pointer"
            >
              <MatIcon name="add" className="text-[14px]" />
              새 Job
            </button>
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
        <div className="flex-1 flex flex-col min-h-0">
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
    </div>
  )
}
