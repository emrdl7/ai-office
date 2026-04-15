// 자가개선 메트릭 패널 — /api/improvement/metrics 집계 표시
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { MatIcon } from './icons'

interface ProjectMetric {
  task_id: string
  project_type: string
  instruction: string
  total_duration: number
  phase_count: number
  final_review_passed: boolean
  final_review_rounds: number
  started_at: string
  finished_at: string
}

export function formatDuration(sec: number): string {
  if (!sec || sec <= 0) return '-'
  const m = Math.floor(sec / 60)
  if (m < 60) return `${m}분`
  const h = Math.floor(m / 60)
  return `${h}시간 ${m % 60}분`
}

export function MetricsPanel({ onClose }: { onClose: () => void }) {
  const { data, isLoading } = useQuery<ProjectMetric[]>({
    queryKey: ['improvement-metrics'],
    queryFn: async () => (await fetch('/api/improvement/metrics')).json(),
    refetchInterval: 15_000,
  })

  const agg = useMemo(() => {
    const rows = data ?? []
    const n = rows.length
    if (n === 0) return null
    const finished = rows.filter((r) => r.finished_at)
    const passed = rows.filter((r) => r.final_review_passed).length
    const avgRevisions =
      rows.reduce((s, r) => s + (r.final_review_rounds || 0), 0) / n
    const avgPhases =
      rows.reduce((s, r) => s + (r.phase_count || 0), 0) / n
    const avgDuration =
      finished.length > 0
        ? finished.reduce((s, r) => s + (r.total_duration || 0), 0) /
          finished.length
        : 0
    return {
      n,
      passRate: (passed / n) * 100,
      avgRevisions,
      avgPhases,
      avgDuration,
    }
  }, [data])

  const recent = useMemo(
    () =>
      (data ?? [])
        .slice()
        .sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''))
        .slice(0, 8),
    [data],
  )

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-10">
      <div className="absolute inset-0 bg-black/60 dark:bg-black/70" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-white dark:bg-gray-800
        border border-gray-200 dark:border-gray-700
        rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4
          border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            자가개선 분석
          </h2>
          <button onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
              dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="닫기">
            <MatIcon name="close" className="text-[20px]" />
          </button>
        </div>

        <div className="p-5 max-h-[70vh] overflow-y-auto space-y-5">
          {isLoading && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">로딩 중...</p>
          )}

          {!isLoading && !agg && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">
              아직 수집된 프로젝트 메트릭이 없습니다
            </p>
          )}

          {agg && (
            <>
              <div>
                <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  누적 요약 (총 {agg.n}건)
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                    <p className="text-xs text-gray-500 dark:text-gray-400">QA 합격률</p>
                    <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                      {agg.passRate.toFixed(1)}%
                    </p>
                  </div>
                  <div className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                    <p className="text-xs text-gray-500 dark:text-gray-400">평균 revision</p>
                    <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                      {agg.avgRevisions.toFixed(2)}
                    </p>
                  </div>
                  <div className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                    <p className="text-xs text-gray-500 dark:text-gray-400">평균 phase</p>
                    <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                      {agg.avgPhases.toFixed(1)}
                    </p>
                  </div>
                  <div className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                    <p className="text-xs text-gray-500 dark:text-gray-400">평균 소요</p>
                    <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                      {formatDuration(agg.avgDuration)}
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  최근 프로젝트
                </h3>
                <ul className="space-y-1.5">
                  {recent.map((p) => (
                    <li key={p.task_id}
                      className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                      <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                        <span className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700">
                          {p.project_type || 'unknown'}
                        </span>
                        <span>·</span>
                        <span>
                          {p.started_at
                            ? new Date(p.started_at).toLocaleString('ko-KR')
                            : '-'}
                        </span>
                        <span className="ml-auto">
                          <MatIcon name={p.final_review_passed ? 'check_circle' : 'cancel'} className={`text-[13px] ${p.final_review_passed ? 'text-green-500' : 'text-red-500'}`} fill /> · rev {p.final_review_rounds}
                        </span>
                      </div>
                      <p className="text-sm text-gray-800 dark:text-gray-200 mt-0.5 line-clamp-2">
                        {p.instruction || '(지시 없음)'}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        phase {p.phase_count} · {formatDuration(p.total_duration)}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
