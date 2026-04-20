// 인사이트 패널 — Job 파이프라인 통계
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { MatIcon } from './icons'

// ─── 타입 ──────────────────────────────────────────────────────────────────

interface TierStat {
  tier: string
  label: string
  calls: number
  cost_usd: number
  color: string
}

interface TodayCost {
  opus_calls_today: number
  opus_daily_limit: number
  opus_remaining: number
  total_cost_usd: number
  budget_usd: number
  by_tier: TierStat[]
}

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
  total_cost_usd: number
  step_cost_usd: number
}

// ─── 유틸 ──────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  done: '완료', running: '실행중', queued: '대기', failed: '실패',
  cancelled: '취소', waiting_gate: '게이트 대기',
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

  const { data: costData } = useQuery<TodayCost>({
    queryKey: ['cost-today'],
    queryFn: async () => (await fetch('/api/cost/today')).json(),
    refetchInterval: 30_000,
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
          {/* Opus 잔여 횟수 */}
          {costData && (
            <div className="mb-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">오늘 Opus 사용량</p>
              <div className="bg-purple-50 dark:bg-purple-900/20 rounded-xl px-3 py-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] text-purple-500 dark:text-purple-400 font-medium">
                    claude-opus (deep tier)
                  </span>
                  <span className={`text-sm font-bold font-mono
                    ${costData.opus_remaining === 0
                      ? 'text-red-500'
                      : costData.opus_remaining <= 3
                        ? 'text-orange-500'
                        : 'text-purple-600 dark:text-purple-300'
                    }`}>
                    {costData.opus_calls_today}/{costData.opus_daily_limit}회
                  </span>
                </div>
                <div className="h-1.5 bg-purple-100 dark:bg-purple-900/40 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all
                      ${costData.opus_remaining === 0
                        ? 'bg-red-500'
                        : costData.opus_remaining <= 3
                          ? 'bg-orange-400'
                          : 'bg-purple-500'
                      }`}
                    style={{ width: `${Math.min(100, Math.round((costData.opus_calls_today / costData.opus_daily_limit) * 100))}%` }}
                  />
                </div>
                <p className="text-[10px] text-purple-400 mt-1">
                  {costData.opus_remaining === 0
                    ? '오늘 한도 소진 — Gemini로 자동 폴백 중'
                    : `잔여 ${costData.opus_remaining}회`}
                </p>
              </div>
            </div>
          )}

          {/* Tier별 호출 수 */}
          {costData && costData.by_tier && costData.by_tier.some((t) => t.calls > 0) && (
            <div className="mb-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">오늘 Tier별 호출</p>
              <div className="space-y-1.5">
                {costData.by_tier.map((t) => {
                  const maxCalls = Math.max(...costData.by_tier.map((x) => x.calls), 1)
                  const COLOR_BAR: Record<string, string> = {
                    blue: 'bg-blue-400', green: 'bg-green-400',
                    purple: 'bg-purple-500', cyan: 'bg-cyan-400',
                  }
                  const COLOR_TEXT: Record<string, string> = {
                    blue: 'text-blue-500', green: 'text-green-500',
                    purple: 'text-purple-500', cyan: 'text-cyan-500',
                  }
                  return (
                    <div key={t.tier} className="flex items-center gap-2">
                      <span className={`w-24 text-[10px] text-right shrink-0 truncate ${COLOR_TEXT[t.color] ?? 'text-gray-400'}`}>
                        {t.label.split(' ')[0]}
                      </span>
                      <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${COLOR_BAR[t.color] ?? 'bg-gray-400'}`}
                          style={{ width: `${Math.round((t.calls / maxCalls) * 100)}%` }}
                        />
                      </div>
                      <span className="w-8 text-[10px] text-gray-500 shrink-0 text-right">{t.calls}회</span>
                      <span className="w-14 text-[10px] text-gray-400 shrink-0 text-right font-mono">${t.cost_usd.toFixed(4)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

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

              {/* 비용 추적 */}
              {(data.total_cost_usd > 0 || data.step_cost_usd > 0) && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">추정 비용</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded-xl px-3 py-2.5">
                      <p className="text-[10px] text-emerald-600 dark:text-emerald-400 mb-0.5">완료 Job 합산</p>
                      <p className="text-lg font-bold text-emerald-600 dark:text-emerald-400 font-mono">
                        ${data.total_cost_usd.toFixed(4)}
                      </p>
                    </div>
                    <div className="bg-gray-50 dark:bg-gray-800/60 rounded-xl px-3 py-2.5">
                      <p className="text-[10px] text-gray-400 mb-0.5">Step 합산</p>
                      <p className="text-lg font-bold text-gray-600 dark:text-gray-300 font-mono">
                        ${data.step_cost_usd.toFixed(4)}
                      </p>
                    </div>
                  </div>
                </div>
              )}

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
