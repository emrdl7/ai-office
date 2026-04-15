// 인사이트 통합 패널 — 리액션 / 자가개선 / 자율대화 / 드리프트 4탭
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { MatIcon } from './icons'
import { displayName, AGENT_IDS } from '../config/team'
import { formatDuration } from './MetricsPanel'

// ─── 타입 ──────────────────────────────────────────────────────────────────

interface ReactionStats {
  per_agent: Record<string, Record<string, number>>
  totals: Record<string, number>
}

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

interface AgentDrift {
  agent: string
  score: number | null
  reason: string
  sample_count: number
}

interface PersonaDriftData {
  computed_at: string
  period_hours: number
  agents: AgentDrift[]
  drift_count: number
}

// ─── 탭 정의 ────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'reaction',   label: '리액션',   icon: 'favorite'       },
  { id: 'metrics',    label: '자가개선', icon: 'auto_fix_high'  },
  { id: 'autonomous', label: '자율대화', icon: 'smart_toy'      },
  { id: 'drift',      label: '드리프트', icon: 'manage_accounts'},
] as const

type TabId = typeof TABS[number]['id']

// ─── 공통 유틸 ──────────────────────────────────────────────────────────────

const MODE_LABEL: Record<string, string> = {
  improvement: '개선 제안', joke: '농담', reaction: '리액션',
  closing: '마무리', trend_research: '트렌드', unknown: '기타',
}
const MODE_COLOR: Record<string, string> = {
  improvement: 'bg-blue-500', joke: 'bg-yellow-400', reaction: 'bg-purple-400',
  closing: 'bg-green-400', trend_research: 'bg-cyan-400', unknown: 'bg-gray-400',
}
const AGENT_LABEL: Record<string, string> = {
  teamlead: '잡스', planner: '드러커', designer: '아이브', developer: '튜링', qa: '데밍',
}

function scoreColor(s: number | null) {
  if (s === null) return 'text-gray-400'
  if (s >= 8) return 'text-green-500'
  if (s >= 6) return 'text-blue-500'
  if (s >= 4) return 'text-yellow-500'
  return 'text-red-500'
}
function scoreBg(s: number | null) {
  if (s === null) return 'bg-gray-50 dark:bg-gray-800/50'
  if (s >= 8) return 'bg-green-50 dark:bg-green-900/20'
  if (s >= 6) return 'bg-blue-50 dark:bg-blue-900/20'
  if (s >= 4) return 'bg-yellow-50 dark:bg-yellow-900/20'
  return 'bg-red-50 dark:bg-red-900/20'
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-10">{text}</p>
}

function Loading() {
  return <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-10">로딩 중...</p>
}

// ─── 탭 콘텐츠 ──────────────────────────────────────────────────────────────

function TabReaction() {
  const { data, isLoading } = useQuery<ReactionStats>({
    queryKey: ['reaction-stats'],
    queryFn: async () => (await fetch('/api/reactions/stats')).json(),
    refetchInterval: 10_000,
  })
  const perAgent = data?.per_agent ?? {}
  const totals = data?.totals ?? {}
  const hasData = Object.keys(totals).length > 0

  if (isLoading) return <Loading />
  if (!hasData) return <Empty text="아직 리액션이 없습니다" />
  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">전체 합계</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(totals).sort((a, b) => b[1] - a[1]).map(([emoji, count]) => (
            <span key={emoji}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg
                bg-gray-100 dark:bg-gray-700 text-sm text-gray-800 dark:text-gray-100">
              {emoji}<span className="font-medium">{count}</span>
            </span>
          ))}
        </div>
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">에이전트별</p>
        <div className="space-y-1.5">
          {AGENT_IDS.map((id) => {
            const bucket = perAgent[id] ?? {}
            const sum = Object.values(bucket).reduce((a, b) => a + b, 0)
            return (
              <div key={id}
                className="flex items-center justify-between px-3 py-2 rounded-xl
                  bg-gray-50 dark:bg-gray-900/60 border border-transparent dark:border-gray-700/50">
                <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  {displayName(id)}
                </span>
                <div className="flex flex-wrap gap-1">
                  {sum === 0
                    ? <span className="text-xs text-gray-400">없음</span>
                    : Object.entries(bucket).sort((a, b) => b[1] - a[1]).map(([emoji, count]) => (
                        <span key={emoji}
                          className="text-xs px-1.5 py-0.5 rounded bg-white dark:bg-gray-700
                            text-gray-800 dark:text-gray-100">
                          {emoji} {count}
                        </span>
                      ))
                  }
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function TabMetrics() {
  const { data, isLoading } = useQuery<ProjectMetric[]>({
    queryKey: ['improvement-metrics'],
    queryFn: async () => (await fetch('/api/improvement/metrics')).json(),
    refetchInterval: 15_000,
  })
  const agg = useMemo(() => {
    const rows = data ?? []
    if (!rows.length) return null
    const finished = rows.filter((r) => r.finished_at)
    const passed = rows.filter((r) => r.final_review_passed).length
    return {
      n: rows.length,
      passRate: (passed / rows.length) * 100,
      avgRevisions: rows.reduce((s, r) => s + (r.final_review_rounds || 0), 0) / rows.length,
      avgPhases: rows.reduce((s, r) => s + (r.phase_count || 0), 0) / rows.length,
      avgDuration: finished.length
        ? finished.reduce((s, r) => s + (r.total_duration || 0), 0) / finished.length
        : 0,
    }
  }, [data])
  const recent = useMemo(
    () => (data ?? []).slice().sort((a, b) => (b.started_at || '').localeCompare(a.started_at || '')).slice(0, 8),
    [data],
  )

  if (isLoading) return <Loading />
  if (!agg) return <Empty text="수집된 프로젝트 메트릭이 없습니다" />
  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">누적 요약 (총 {agg.n}건)</p>
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'QA 합격률', value: `${agg.passRate.toFixed(1)}%` },
            { label: '평균 revision', value: agg.avgRevisions.toFixed(2) },
            { label: '평균 phase', value: agg.avgPhases.toFixed(1) },
            { label: '평균 소요', value: formatDuration(agg.avgDuration) },
          ].map(({ label, value }) => (
            <div key={label} className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
              <p className="text-[10px] text-gray-500 dark:text-gray-400">{label}</p>
              <p className="text-base font-semibold text-gray-900 dark:text-gray-100">{value}</p>
            </div>
          ))}
        </div>
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2">최근 프로젝트</p>
        <ul className="space-y-1.5">
          {recent.map((p) => (
            <li key={p.task_id} className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
              <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                <span className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700">
                  {p.project_type || 'unknown'}
                </span>
                <span>·</span>
                <span>{p.started_at ? new Date(p.started_at).toLocaleString('ko-KR') : '-'}</span>
                <span className="ml-auto flex items-center gap-1"><MatIcon name={p.final_review_passed ? 'check_circle' : 'cancel'} className={`text-[12px] ${p.final_review_passed ? 'text-green-500' : 'text-red-500'}`} fill /> rev {p.final_review_rounds}</span>
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
    </div>
  )
}

function TabAutonomous() {
  const [hours, setHours] = useState(24)
  const { data, isLoading } = useQuery<AutonomousStats>({
    queryKey: ['autonomous-stats', hours],
    queryFn: async () => (await fetch(`/api/autonomous/stats?hours=${hours}`)).json(),
    refetchInterval: 30_000,
  })
  const total = data?.total_count ?? 0
  const totalAttempts = total + (data?.pass_drop_count ?? 0)
  const modes = Object.entries(data?.mode_distribution ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))}
          className="text-xs px-2 py-1 rounded border border-gray-200 dark:border-gray-600
            bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 cursor-pointer">
          <option value={6}>6시간</option>
          <option value={24}>24시간</option>
          <option value={48}>48시간</option>
          <option value={168}>7일</option>
        </select>
      </div>
      {isLoading ? <Loading /> : !data ? <Empty text="데이터 없음" /> : (
        <>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: '발화', value: total, unit: '건', color: 'text-blue-500' },
              { label: 'PASS 드롭율', value: `${(data.pass_drop_rate * 100).toFixed(1)}%`,
                sub: `${data.pass_drop_count}건 드롭`,
                color: data.pass_drop_rate > 0.5 ? 'text-yellow-500' : 'text-green-500' },
              { label: '중복 skip', value: data.dedup_skip_count, unit: '건', color: 'text-purple-500' },
              { label: '주제 고착', value: data.stuck_count, unit: '회',
                color: data.stuck_count > 5 ? 'text-red-400' : 'text-gray-500' },
            ].map(({ label, value, unit, sub, color }) => (
              <div key={label} className="bg-gray-50 dark:bg-gray-800/60 rounded-xl px-3 py-2.5">
                <p className="text-[10px] text-gray-400 mb-0.5">{label}</p>
                <p className={`text-lg font-bold ${color}`}>
                  {value}{unit && <span className="text-xs font-normal text-gray-400 ml-0.5">{unit}</span>}
                </p>
                {sub && <p className="text-[10px] text-gray-400">{sub}</p>}
              </div>
            ))}
          </div>
          {modes.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1.5">모드 분포</p>
              <div className="space-y-1">
                {modes.map(([mode, count]) => (
                  <div key={mode} className="flex items-center gap-2">
                    <span className="w-14 text-[10px] text-gray-500 text-right shrink-0">
                      {MODE_LABEL[mode] ?? mode}
                    </span>
                    <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${MODE_COLOR[mode] ?? 'bg-gray-400'}`}
                        style={{ width: `${total > 0 ? Math.round((count / total) * 100) : 0}%` }} />
                    </div>
                    <span className="w-5 text-[10px] text-gray-500 shrink-0">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.top_keywords.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1.5">반복 키워드 top5</p>
              <div className="flex flex-wrap gap-1.5">
                {data.top_keywords.map((kw, i) => (
                  <span key={kw}
                    className={`px-2 py-0.5 rounded-full text-[10px] font-medium
                      ${i === 0 ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-300'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'}`}>
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="text-[10px] text-gray-400 text-right">총 시도 {totalAttempts}건 ({hours}시간)</p>
        </>
      )}
    </div>
  )
}

function TabDrift() {
  const [hours, setHours] = useState(48)
  const { data, isLoading } = useQuery<PersonaDriftData>({
    queryKey: ['persona-drift', hours],
    queryFn: async () => (await fetch(`/api/team/persona-drift?hours=${hours}`)).json(),
    refetchInterval: 60_000,
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        {data && data.drift_count > 0 && (
          <span className="px-2 py-0.5 text-[10px] font-bold bg-red-100 dark:bg-red-900/40
            text-red-600 dark:text-red-300 rounded-full">
            {data.drift_count}건 이탈 감지
          </span>
        )}
        <div className="ml-auto">
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}
            className="text-xs px-2 py-1 rounded border border-gray-200 dark:border-gray-600
              bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 cursor-pointer">
            <option value={24}>24시간</option>
            <option value={48}>48시간</option>
            <option value={168}>7일</option>
          </select>
        </div>
      </div>
      {isLoading ? <Loading /> : !data ? <Empty text="데이터 없음" /> : (
        <>
          {data.agents.map((a) => (
            <div key={a.agent} className={`rounded-xl px-3 py-2.5 ${scoreBg(a.score)}`}>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
                  {AGENT_LABEL[a.agent] ?? a.agent}
                </span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-gray-400">{a.sample_count}건</span>
                  <span className={`text-base font-bold ${scoreColor(a.score)}`}>
                    {a.score !== null ? `${a.score}/10` : '—'}
                  </span>
                </div>
              </div>
              <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-relaxed">{a.reason}</p>
              {a.score !== null && a.score < 10 && (
                <div className="mt-1.5 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${a.score >= 6 ? 'bg-blue-400' : a.score >= 4 ? 'bg-yellow-400' : 'bg-red-400'}`}
                    style={{ width: `${Math.round((a.score / 10) * 100)}%` }}
                  />
                </div>
              )}
            </div>
          ))}
          <p className="text-[10px] text-gray-400 text-right">
            {data.computed_at
              ? `마지막 분석 ${new Date(data.computed_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`
              : '—'}
            &nbsp;· {hours}시간 기준
          </p>
        </>
      )}
    </div>
  )
}

// ─── 메인 패널 ──────────────────────────────────────────────────────────────

export function InsightPanel({ onClose, defaultTab = 'reaction' }: {
  onClose: () => void
  defaultTab?: TabId
}) {
  const [activeTab, setActiveTab] = useState<TabId>(defaultTab)

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

        {/* 탭 바 */}
        <div className="flex border-b border-gray-200 dark:border-gray-700 shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium
                cursor-pointer transition-colors relative
                ${activeTab === tab.id
                  ? 'text-blue-500 dark:text-blue-400'
                  : 'text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
            >
              <MatIcon name={tab.icon} className="text-[18px]"
                fill={activeTab === tab.id} />
              <span>{tab.label}</span>
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 rounded-t-full" />
              )}
            </button>
          ))}
        </div>

        {/* 탭 콘텐츠 */}
        <div className="overflow-y-auto p-4">
          {activeTab === 'reaction'   && <TabReaction />}
          {activeTab === 'metrics'    && <TabMetrics />}
          {activeTab === 'autonomous' && <TabAutonomous />}
          {activeTab === 'drift'      && <TabDrift />}
        </div>
      </div>
    </div>
  )

  return createPortal(panel, document.body)
}
