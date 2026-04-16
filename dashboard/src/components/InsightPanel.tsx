// 인사이트 패널 — Job 파이프라인 통계
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { MatIcon } from './icons'

// ─── 타입 ──────────────────────────────────────────────────────────────────

interface JobInsights {
  total: number
  by_status: Record<string, number>
  completion_rate: number
  avg_duration_sec: number
  by_spec: Record<string, Record<string, number>>
  model_usage: { model: string; count: number }[]
  total_revised: number
  total_steps_done: number
  revision_rate: number
  daily_done: { day: string; count: number }[]
}

// ─── 유틸 ──────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  done: '완료', running: '실행중', queued: '대기', failed: '실패',
  cancelled: '취소', waiting_gate: 'Gate 대기',
}
const STATUS_COLOR: Record<string, string> = {
  done: 'bg-green-500', running: 'bg-blue-500', queued: 'bg-gray-400',
  failed: 'bg-red-500', cancelled: 'bg-gray-500', waiting_gate: 'bg-yellow-500',
}

function fmtSec(sec: number): string {
  if (!sec) return '—'
  if (sec < 60) return `${sec}초`
  if (sec < 3600) return `${Math.floor(sec / 60)}분 ${sec % 60}초`
  return `${Math.floor(sec / 3600)}시간 ${Math.floor((sec % 3600) / 60)}분`
}

// ─── 메인 패널 ──────────────────────────────────────────────────────────────

export function InsightPanel({ onClose }: { onClose: () => void }) {
  const { data, isLoading } = useQuery<JobInsights>({
    queryKey: ['job-insights'],
    queryFn: async () => (await fetch('/api/jobs/insights')).json(),
    refetchInterval: 15_000,
  })

  const maxDaily = Math.max(...(data?.daily_done ?? []).map((d) => d.count), 1)

  const panel = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-md
        border border-gray-200 dark:border-gray-700 flex flex-col max-h-[85vh]">

        {/* 헤더 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center gap-1.5">
            <MatIcon name="insights" className="text-[18px] text-blue-400" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">인사이트</h2>
          </div>
          <button onClick={onClose}
            className="p-1 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200
              hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors"
            aria-label="닫기">
            <MatIcon name="close" className="text-[18px]" />
          </button>
        </div>

        {/* 콘텐츠 */}
        <div className="overflow-y-auto p-4">
          {isLoading && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-10">로딩 중...</p>
          )}
          {!isLoading && (!data || data.total === 0) && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-10">Job 실행 기록이 없습니다</p>
          )}
          {!isLoading && data && data.total > 0 && (
            <div className="space-y-4">
              {/* 상태 분포 */}
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">
                  상태 분포 (총 {data.total}건)
                </p>
                <div className="space-y-1">
                  {Object.entries(data.by_status)
                    .sort((a, b) => b[1] - a[1])
                    .map(([status, cnt]) => (
                      <div key={status} className="flex items-center gap-2">
                        <span className="w-16 text-[10px] text-gray-500 text-right shrink-0">
                          {STATUS_LABEL[status] ?? status}
                        </span>
                        <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${STATUS_COLOR[status] ?? 'bg-gray-400'}`}
                            style={{ width: `${Math.round((cnt / data.total) * 100)}%` }}
                          />
                        </div>
                        <span className="w-6 text-[10px] text-gray-500 shrink-0 text-right">{cnt}</span>
                      </div>
                    ))}
                </div>
              </div>

              {/* 핵심 지표 */}
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: '완료율', value: `${data.completion_rate}%`, color: data.completion_rate >= 70 ? 'text-green-500' : 'text-yellow-500' },
                  { label: '평균 소요', value: fmtSec(data.avg_duration_sec), color: 'text-blue-500' },
                  { label: '수정률', value: `${data.revision_rate}%`, color: data.revision_rate > 20 ? 'text-orange-500' : 'text-gray-700 dark:text-gray-300' },
                  { label: '총 Step', value: `${data.total_steps_done}건`, color: 'text-purple-500' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-gray-50 dark:bg-gray-800/60 rounded-xl px-3 py-2.5">
                    <p className="text-[10px] text-gray-400 mb-0.5">{label}</p>
                    <p className={`text-lg font-bold ${color}`}>{value}</p>
                  </div>
                ))}
              </div>

              {/* 모델 사용 */}
              {data.model_usage.length > 0 && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">모델 사용</p>
                  <div className="space-y-1">
                    {data.model_usage.map(({ model, count }) => {
                      const total = data.model_usage.reduce((s, m) => s + m.count, 0)
                      const short = model.replace('claude-', '').replace('-4-5-20251001', '').replace('-4-6', '').replace('gemini-', 'gemini-')
                      const isGemini = model.includes('gemini')
                      return (
                        <div key={model} className="flex items-center gap-2">
                          <span className={`w-20 text-[10px] text-right shrink-0 truncate
                            ${isGemini ? 'text-blue-500' : 'text-purple-500'}`}>
                            {short}
                          </span>
                          <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${isGemini ? 'bg-blue-400' : 'bg-purple-400'}`}
                              style={{ width: `${Math.round((count / total) * 100)}%` }}
                            />
                          </div>
                          <span className="w-6 text-[10px] text-gray-500 shrink-0 text-right">{count}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 일별 완료 차트 (7일) */}
              {data.daily_done.length > 0 && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">최근 7일 완료</p>
                  <div className="flex items-end gap-1 h-16">
                    {data.daily_done.map(({ day, count }) => (
                      <div key={day} className="flex-1 flex flex-col items-center gap-0.5">
                        <div
                          className="w-full bg-blue-400 rounded-t-sm"
                          style={{ height: `${Math.round((count / maxDaily) * 48)}px`, minHeight: count > 0 ? '4px' : '0' }}
                          title={`${day}: ${count}건`}
                        />
                        <span className="text-[8px] text-gray-400">{day.slice(5)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 스펙별 통계 */}
              {Object.keys(data.by_spec).length > 0 && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">스펙별</p>
                  <div className="space-y-1">
                    {Object.entries(data.by_spec).map(([spec, counts]) => {
                      const done = counts['done'] ?? 0
                      const failed = counts['failed'] ?? 0
                      const total = Object.values(counts).reduce((s, n) => s + n, 0)
                      return (
                        <div key={spec} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-900">
                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300 flex-1 truncate">{spec}</span>
                          <span className="text-[10px] text-green-500">{done}완료</span>
                          {failed > 0 && <span className="text-[10px] text-red-400">{failed}실패</span>}
                          <span className="text-[10px] text-gray-400">{total}건</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )

  return createPortal(panel, document.body)
}
