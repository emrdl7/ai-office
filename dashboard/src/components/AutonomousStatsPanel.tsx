// 자율 대화 관측 패널 — /api/autonomous/stats 집계 표시 (P3)
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { MatIcon } from './icons'

interface AutonomousStats {
  period_hours: number
  total_count: number
  mode_distribution: Record<string, number>
  pass_drop_count: number
  pass_drop_rate: number
  dedup_skip_count: number
  top_keywords: string[]
  stuck_count: number
}

const MODE_LABEL: Record<string, string> = {
  improvement: '개선 제안',
  joke: '농담',
  reaction: '리액션',
  closing: '마무리',
  trend_research: '트렌드',
  unknown: '기타',
}

const MODE_COLOR: Record<string, string> = {
  improvement: 'bg-blue-500',
  joke: 'bg-yellow-400',
  reaction: 'bg-purple-400',
  closing: 'bg-green-400',
  trend_research: 'bg-cyan-400',
  unknown: 'bg-gray-400',
}

export function AutonomousStatsPanel({ onClose }: { onClose: () => void }) {
  const [hours, setHours] = useState(24)

  const { data, isLoading } = useQuery<AutonomousStats>({
    queryKey: ['autonomous-stats', hours],
    queryFn: async () => (await fetch(`/api/autonomous/stats?hours=${hours}`)).json(),
    refetchInterval: 30_000,
  })

  const total = data?.total_count ?? 0
  const totalAttempts = total + (data?.pass_drop_count ?? 0)
  const modes = Object.entries(data?.mode_distribution ?? {}).sort((a, b) => b[1] - a[1])

  const panel = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-sm
        border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-4 py-3
          border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <span className="text-base">🧠</span>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">자율 대화 관측</h2>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              className="text-xs px-2 py-1 rounded border border-gray-200 dark:border-gray-600
                bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 cursor-pointer"
            >
              <option value={6}>6시간</option>
              <option value={24}>24시간</option>
              <option value={48}>48시간</option>
              <option value={168}>7일</option>
            </select>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 cursor-pointer"
              aria-label="닫기"
            >
              <MatIcon name="close" className="text-[16px]" />
            </button>
          </div>
        </div>

        {/* 본문 */}
        <div className="p-4 space-y-4">
          {isLoading ? (
            <p className="text-center text-sm text-gray-400 py-4">로딩 중...</p>
          ) : !data ? (
            <p className="text-center text-sm text-gray-400 py-4">데이터 없음</p>
          ) : (
            <>
              {/* 핵심 지표 4개 */}
              <div className="grid grid-cols-2 gap-2">
                <StatCard label="발화" value={total} unit="건" color="text-blue-500" />
                <StatCard
                  label="PASS 드롭율"
                  value={`${(data.pass_drop_rate * 100).toFixed(1)}%`}
                  sub={`${data.pass_drop_count}건 드롭`}
                  color={data.pass_drop_rate > 0.5 ? 'text-yellow-500' : 'text-green-500'}
                />
                <StatCard label="중복 skip" value={data.dedup_skip_count} unit="건" color="text-purple-500" />
                <StatCard
                  label="주제 고착"
                  value={data.stuck_count}
                  unit="회"
                  color={data.stuck_count > 5 ? 'text-red-400' : 'text-gray-500'}
                />
              </div>

              {/* 모드 분포 바 */}
              {modes.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">모드 분포</p>
                  <div className="space-y-1">
                    {modes.map(([mode, count]) => (
                      <div key={mode} className="flex items-center gap-2">
                        <span className="w-14 text-[10px] text-gray-500 text-right shrink-0">
                          {MODE_LABEL[mode] ?? mode}
                        </span>
                        <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${MODE_COLOR[mode] ?? 'bg-gray-400'}`}
                            style={{ width: `${total > 0 ? Math.round((count / total) * 100) : 0}%` }}
                          />
                        </div>
                        <span className="w-6 text-[10px] text-gray-500 shrink-0">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 반복 키워드 */}
              {data.top_keywords.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
                    반복 키워드 top5
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {data.top_keywords.map((kw, i) => (
                      <span
                        key={kw}
                        className={`px-2 py-0.5 rounded-full text-[10px] font-medium
                          ${i === 0 ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-300'
                          : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'}`}
                      >
                        {kw}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* 총 시도 */}
              <p className="text-[10px] text-gray-400 text-right">
                총 시도 {totalAttempts}건 ({hours}시간)
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )

  return createPortal(panel, document.body)
}

function StatCard({
  label,
  value,
  unit,
  sub,
  color,
}: {
  label: string
  value: number | string
  unit?: string
  sub?: string
  color?: string
}) {
  return (
    <div className="bg-gray-50 dark:bg-gray-800/60 rounded-xl px-3 py-2.5">
      <p className="text-[10px] text-gray-400 mb-0.5">{label}</p>
      <p className={`text-lg font-bold ${color ?? 'text-gray-900 dark:text-white'}`}>
        {value}
        {unit && <span className="text-xs font-normal text-gray-400 ml-0.5">{unit}</span>}
      </p>
      {sub && <p className="text-[10px] text-gray-400">{sub}</p>}
    </div>
  )
}
