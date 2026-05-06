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
  total_revised: number
  total_steps_done: number
  revision_rate: number
  daily_done: { day: string; count: number }[]
  routing_quality?: RoutingQuality
}

interface RoutingQualityItem {
  id: string
  steps: number
  done: number
  failed: number
  success_rate: number
  revised: number
  revision_rate: number
  fallback_count: number
  avg_quality_score: number
}

interface RoutingQuality {
  overall: RoutingQualityItem
  by_execution_mode: RoutingQualityItem[]
  risk_items: {
    personas: RoutingQualityItem[]
    skills: RoutingQualityItem[]
    tools: RoutingQualityItem[]
  }
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
const MODE_LABEL: Record<string, string> = {
  single: '단일 실행',
  tool_assisted: '툴 보조',
  research: '리서치',
  review: '검토',
  parallel_safe: '병렬 안전',
  unknown: '미분류',
}

function fmtSec(sec: number): string {
  if (!sec) return '—'
  if (sec < 60) return `${sec}초`
  if (sec < 3600) return `${Math.floor(sec / 60)}분 ${sec % 60}초`
  return `${Math.floor(sec / 3600)}시간 ${Math.floor((sec % 3600) / 60)}분`
}

function qualityTone(score: number): string {
  if (score >= 85) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 65) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

// ─── 메인 패널 ──────────────────────────────────────────────────────────────

export function InsightPanel({
  onClose,
  onOpenComponents,
}: {
  onClose: () => void
  onOpenComponents?: () => void
}) {
  const [auditState, setAuditState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const { data, isLoading } = useQuery<JobInsights>({
    queryKey: ['job-insights'],
    queryFn: async () => (await fetch('/api/jobs/insights')).json(),
    refetchInterval: 15_000,
  })

  const { data: agreement } = useQuery<{
    days: number; total: number; matched: number; mismatched: number; match_rate: number
    by_gate: { gate_id: string; count: number; matched: number; match_rate: number }[]
  }>({
    queryKey: ['gate-agreement', 7],
    queryFn: async () => (await fetch('/api/jobs/gates/agreement_stats?days=7')).json(),
    refetchInterval: 60_000,
  })

  const maxDaily = Math.max(...(data?.daily_done ?? []).map((d) => d.count), 1)
  const riskItems = data?.routing_quality
    ? [
        ...data.routing_quality.risk_items.personas.map((x) => ({ ...x, kind: 'persona' })),
        ...data.routing_quality.risk_items.skills.map((x) => ({ ...x, kind: 'skill' })),
        ...data.routing_quality.risk_items.tools.map((x) => ({ ...x, kind: 'tool' })),
      ]
        .filter((x) => x.steps > 0 && (x.avg_quality_score < 85 || x.failed > 0 || x.revision_rate > 0))
        .sort((a, b) => a.avg_quality_score - b.avg_quality_score)
        .slice(0, 6)
    : []
  const runCapabilityAudit = async () => {
    setAuditState('running')
    try {
      const res = await fetch('/api/improvement/capability-audit?register=true', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAuditState('done')
    } catch {
      setAuditState('error')
    }
  }

  const panel = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-panel rounded-3xl shadow-2xl w-full max-w-lg
        flex flex-col max-h-[88vh] overflow-hidden">

        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200/70 dark:border-gray-700/70 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-slate-950 text-white dark:bg-cyan-300 dark:text-slate-950">
              <MatIcon name="insights" className="text-[18px]" />
            </span>
            <div>
              <h2 className="text-sm font-black text-gray-900 dark:text-white">운영 인사이트</h2>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">gate, 라우팅 품질, 완료 추세</p>
            </div>
          </div>
          <button onClick={onClose}
            className="p-1 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200
              hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors"
            aria-label="닫기">
            <MatIcon name="close" className="text-[18px]" />
          </button>
        </div>

        {/* 콘텐츠 */}
        <div className="overflow-y-auto p-5">
          {(riskItems.length > 0 || (agreement && agreement.total > 0 && agreement.match_rate < 0.8)) && (
            <div className="mb-4 rounded-2xl border border-white/70 bg-white/76 p-3 shadow-sm backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
              <div className="flex items-center gap-2">
                <MatIcon name="bolt" className="text-[16px] text-amber-500" />
                <p className="text-xs font-black text-slate-900 dark:text-white">바로 조치</p>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {riskItems.length > 0 && (
                  <button
                    onClick={() => { onOpenComponents?.(); onClose() }}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-slate-950 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-teal-700 dark:bg-cyan-300 dark:text-slate-950 dark:hover:bg-cyan-200"
                  >
                    <MatIcon name="widgets" className="text-[14px]" />
                    컴포넌트 점검
                  </button>
                )}
                <button
                  onClick={runCapabilityAudit}
                  disabled={auditState === 'running'}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200/80 bg-white/80 px-3 py-2 text-xs font-semibold text-slate-700 transition-colors hover:border-teal-300 disabled:opacity-50 dark:border-slate-700/80 dark:bg-slate-950/40 dark:text-slate-200"
                >
                  <MatIcon name={auditState === 'running' ? 'hourglass_empty' : 'fact_check'} className="text-[14px]" />
                  {auditState === 'running' ? '감사 중' : auditState === 'done' ? '감사 완료' : auditState === 'error' ? '감사 실패' : '능력 감사 실행'}
                </button>
              </div>
            </div>
          )}

          {/* Gate AI ↔ 사람 일치율 */}
          {agreement && agreement.total > 0 && (
            <div className="mt-4 p-3 bg-indigo-50 dark:bg-indigo-900/15 rounded-lg border border-indigo-200 dark:border-indigo-700/30">
              <div className="flex items-baseline gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                  Gate AI 일치율 (최근 {agreement.days}일)
                </span>
                <span className="text-[10px] text-gray-500 ml-auto">총 {agreement.total}건</span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <div className="flex-1 h-2 bg-white/60 dark:bg-gray-900/60 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full"
                    style={{ width: `${Math.round(agreement.match_rate * 100)}%` }}
                  />
                </div>
                <span className="text-xs font-bold text-indigo-700 dark:text-indigo-300 tabular-nums">
                  {Math.round(agreement.match_rate * 100)}%
                </span>
              </div>
              <div className="text-[10px] text-gray-500 mt-1">
                일치 {agreement.matched} · 불일치 {agreement.mismatched}
              </div>
              {agreement.by_gate.length > 0 && (
                <div className="mt-2 space-y-1">
                  {agreement.by_gate.slice(0, 5).map(g => (
                    <div key={g.gate_id} className="flex items-center gap-2">
                      <span className="w-24 text-[10px] text-right text-gray-600 dark:text-gray-400 truncate">{g.gate_id}</span>
                      <div className="flex-1 h-1.5 bg-white/60 dark:bg-gray-900/60 rounded-full overflow-hidden">
                        <div className="h-full bg-indigo-400 rounded-full" style={{ width: `${Math.round(g.match_rate * 100)}%` }} />
                      </div>
                      <span className="w-10 text-[10px] text-gray-500 text-right tabular-nums">{Math.round(g.match_rate * 100)}%</span>
                      <span className="w-8 text-[10px] text-gray-400 text-right">({g.count})</span>
                    </div>
                  ))}
                </div>
              )}
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

              {/* 라우팅 품질 */}
              {data.routing_quality && data.routing_quality.overall.steps > 0 && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">라우팅 품질</p>
                  <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/60 p-3">
                    <div className="flex items-baseline justify-between">
                      <span className="text-[10px] text-gray-500">최근 Step {data.routing_quality.overall.steps}건</span>
                      <span className={`text-lg font-black tabular-nums ${qualityTone(data.routing_quality.overall.avg_quality_score)}`}>
                        {Math.round(data.routing_quality.overall.avg_quality_score)}점
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                      <div>
                        <p className="text-[9px] text-gray-400">성공률</p>
                        <p className="text-xs font-bold text-gray-700 dark:text-gray-200">{data.routing_quality.overall.success_rate}%</p>
                      </div>
                      <div>
                        <p className="text-[9px] text-gray-400">수정률</p>
                        <p className="text-xs font-bold text-gray-700 dark:text-gray-200">{data.routing_quality.overall.revision_rate}%</p>
                      </div>
                      <div>
                        <p className="text-[9px] text-gray-400">Fallback</p>
                        <p className="text-xs font-bold text-gray-700 dark:text-gray-200">{data.routing_quality.overall.fallback_count}건</p>
                      </div>
                    </div>
                    {data.routing_quality.by_execution_mode.length > 0 && (
                      <div className="mt-3 space-y-1.5">
                        {data.routing_quality.by_execution_mode.slice(0, 5).map((m) => (
                          <div key={m.id} className="flex items-center gap-2">
                            <span className="w-20 text-[10px] text-right text-gray-500 truncate">{MODE_LABEL[m.id] ?? m.id}</span>
                            <div className="flex-1 h-2 bg-white dark:bg-gray-800 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${m.avg_quality_score >= 85 ? 'bg-emerald-500' : m.avg_quality_score >= 65 ? 'bg-amber-500' : 'bg-red-500'}`}
                                style={{ width: `${Math.max(4, Math.round(m.avg_quality_score))}%` }}
                              />
                            </div>
                            <span className={`w-10 text-[10px] text-right font-bold tabular-nums ${qualityTone(m.avg_quality_score)}`}>
                              {Math.round(m.avg_quality_score)}
                            </span>
                            <span className="w-8 text-[10px] text-gray-400 text-right">({m.steps})</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 위험 조합 */}
              {riskItems.length > 0 && (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">점검 필요 조합</p>
                      <div className="space-y-1">
                        {riskItems.map((item) => (
                          <div key={`${item.kind}:${item.id}`} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-50/70 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30">
                            <span className="w-12 text-[9px] uppercase tracking-wide text-red-400">{item.kind}</span>
                            <span className="text-xs font-medium text-gray-700 dark:text-gray-200 flex-1 truncate">{item.id}</span>
                            <span className={`text-[10px] font-bold tabular-nums ${qualityTone(item.avg_quality_score)}`}>{Math.round(item.avg_quality_score)}점</span>
                            <span className="text-[10px] text-gray-400">{item.steps}건</span>
                          </div>
                        ))}
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
