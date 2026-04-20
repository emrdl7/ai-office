// 사이드바 — v2 리디자인: 브랜드 마크 + 채널 pill + 팀 상태 위젯
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { ChannelId } from '../types'
import { MatIcon } from './icons'
import { SearchPanel } from './SearchPanel'
import { InsightPanel } from './InsightPanel'

type ChannelDef = {
  id: ChannelId
  label: string
  icon: string
  accent: string  // active 색상 (indigo/emerald/amber/violet)
}

const CHANNELS: ChannelDef[] = [
  { id: 'all',        label: 'TALK',              icon: 'forum',            accent: 'indigo'  },
  { id: 'jobs',       label: '작업 보드',          icon: 'view_kanban',      accent: 'emerald' },
  { id: 'gates',      label: '검토 수신함',        icon: 'rule',             accent: 'amber'   },
  { id: 'components', label: '컴포넌트 라이브러리', icon: 'widgets',          accent: 'violet'  },
]

const ACCENT_ACTIVE: Record<string, string> = {
  indigo:  'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 ring-1 ring-inset ring-indigo-500/30',
  emerald: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-1 ring-inset ring-emerald-500/30',
  amber:   'bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-1 ring-inset ring-amber-500/30',
  violet:  'bg-violet-500/15 text-violet-700 dark:text-violet-300 ring-1 ring-inset ring-violet-500/30',
}
const ACCENT_BAR: Record<string, string> = {
  indigo:  'bg-indigo-500',
  emerald: 'bg-emerald-500',
  amber:   'bg-amber-500',
  violet:  'bg-violet-500',
}

// ── Gate 대기 수 뱃지 ────────────────────────────────────────────
function useGatesCount() {
  const { data: gates = [] } = useQuery({
    queryKey: ['pending-gates'],
    queryFn: async () => {
      const res = await fetch('/api/jobs/gates/pending')
      if (!res.ok) return []
      return res.json() as Promise<{ gate_id: string }[]>
    },
    refetchInterval: 10000,
  })
  return gates.length
}

// ── 채널 버튼 (통합) ────────────────────────────────────────────
function ChannelItem({
  def, active, onClick, badge,
}: { def: ChannelDef; active: boolean; onClick: () => void; badge?: number }) {
  return (
    <button
      onClick={onClick}
      className={`group relative w-full flex items-center gap-3 pl-3 pr-3 py-2.5 rounded-xl
        text-sm cursor-pointer transition-all duration-150
        ${active
          ? ACCENT_ACTIVE[def.accent] + ' font-semibold'
          : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-slate-100'}`}
    >
      {/* 좌측 accent bar (active 때만) */}
      <span className={`absolute left-0 top-2 bottom-2 w-[3px] rounded-full transition-opacity
        ${active ? ACCENT_BAR[def.accent] : 'opacity-0'}`} />
      <MatIcon name={def.icon} className={`text-[18px] shrink-0 transition-transform group-hover:scale-110
        ${active ? '' : 'opacity-80'}`} />
      <span className="flex-1 text-left">{def.label}</span>
      {badge !== undefined && badge > 0 && (
        <span className={`inline-flex items-center justify-center min-w-[20px] h-[20px] px-1.5
          rounded-full text-[10px] font-bold ${ACCENT_BAR[def.accent]} text-white shadow-sm`}>
          {badge}
        </span>
      )}
    </button>
  )
}

// ── 오늘의 비용/호출 요약 위젯 (하단) ─────────────────────────
function TodayCostWidget() {
  const { data } = useQuery<{
    total_cost_usd: number; budget_usd: number; budget_remaining: number
    by_model: { runner: string; model: string; calls: number; cost_usd: number }[]
  }>({
    queryKey: ['cost-today-sidebar'],
    queryFn: async () => (await fetch('/api/cost/today')).json(),
    refetchInterval: 30_000,
  })
  if (!data) return null
  const totalCalls = (data.by_model || []).reduce((a, b) => a + b.calls, 0)
  const pct = data.budget_usd > 0 ? Math.min(100, Math.round((data.total_cost_usd / data.budget_usd) * 100)) : 0
  return (
    <div className="px-3 pt-3 pb-2">
      <p className="px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500 mb-1.5">
        오늘 사용량
      </p>
      <div className="px-2 space-y-1.5">
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-bold text-slate-900 dark:text-slate-100 tabular-nums">
            ${data.total_cost_usd.toFixed(3)}
          </span>
          <span className="text-[10px] text-slate-400">/ ${data.budget_usd}</span>
          <span className="ml-auto text-[10px] text-slate-500 font-mono">{totalCalls}회</span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${pct >= 80 ? 'bg-rose-500' : pct >= 50 ? 'bg-amber-500' : 'bg-indigo-500'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  )
}

// ── 하단 유틸 버튼 ───────────────────────────────────────────
function UtilBtn({ icon, label, onClick, title }: {
  icon: string; label: string; onClick: () => void; title?: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg
        text-[13px] text-slate-600 dark:text-slate-400
        hover:bg-slate-100 dark:hover:bg-slate-800/60
        hover:text-slate-900 dark:hover:text-slate-100
        cursor-pointer transition-colors"
    >
      <MatIcon name={icon} className="text-[16px] shrink-0 opacity-80" />
      <span>{label}</span>
    </button>
  )
}

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const { activeChannel, setActiveChannel, toggleTheme, theme } = useStore()
  const [showSearch, setShowSearch] = useState(false)
  const [showInsight, setShowInsight] = useState(false)
  const gatesCount = useGatesCount()

  const selectChannel = (channel: ChannelId) => {
    setActiveChannel(channel)
    onClose?.()
  }

  return (
    <aside
      className="w-72 h-full flex-shrink-0 flex flex-col relative
        bg-white dark:bg-slate-950
        border-r border-slate-200 dark:border-slate-800"
      aria-label="채널 목록"
    >
      {/* 다크모드 상단 은은한 accent glow */}
      <div aria-hidden className="absolute inset-x-0 top-0 h-[160px] pointer-events-none opacity-0 dark:opacity-100
        bg-[radial-gradient(ellipse_at_top_left,rgba(99,102,241,0.18),transparent_60%)]" />

      {/* 브랜드 헤더 */}
      <div className="relative px-4 h-[60px] flex items-center justify-between shrink-0
        border-b border-slate-200 dark:border-slate-800/70">
        <div className="flex items-center gap-2.5">
          <div className="relative w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600
            flex items-center justify-center shadow-lg shadow-indigo-500/30">
            <MatIcon name="auto_awesome" className="text-white text-[18px]" />
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-white dark:ring-slate-950" />
          </div>
          <div className="leading-tight">
            <h1 className="text-[13px] font-bold text-slate-900 dark:text-white tracking-tight">AI Office</h1>
            <p className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">Job pipeline studio</p>
          </div>
        </div>
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg text-slate-500 dark:text-slate-400
            hover:text-slate-900 dark:hover:text-white
            hover:bg-slate-100 dark:hover:bg-slate-800/60
            cursor-pointer transition-colors"
          aria-label="테마 전환"
          title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
        >
          {theme === 'dark'
            ? <MatIcon name="light_mode" className="text-[16px]" />
            : <MatIcon name="dark_mode" className="text-[16px]" />
          }
        </button>
      </div>

      {/* 채널 */}
      <nav className="relative px-3 pt-4 pb-2">
        <h3 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500 px-2 mb-2">
          워크스페이스
        </h3>
        <div className="space-y-1">
          {CHANNELS.map(c => (
            <ChannelItem
              key={c.id}
              def={c}
              active={activeChannel === c.id}
              onClick={() => selectChannel(c.id)}
              badge={c.id === 'gates' ? gatesCount : undefined}
            />
          ))}
        </div>
      </nav>

      {/* 오늘 사용량 */}
      <div className="relative flex-1 overflow-y-auto">
        <TodayCostWidget />
      </div>

      {/* 하단 유틸 */}
      <div className="relative mt-auto p-3 border-t border-slate-200 dark:border-slate-800/70 space-y-0.5">
        <UtilBtn icon="search"      label="통합 검색"   onClick={() => setShowSearch(true)} />
        <UtilBtn icon="insights"    label="인사이트"    onClick={() => setShowInsight(true)} />
        <UtilBtn
          icon="restart_alt"
          label="서버 재시작"
          title="백엔드만 재시작 (코드 병합 후 반영용)"
          onClick={async () => {
            if (!confirm('백엔드 서버를 재시작합니다. 5초 내 자동 재연결됩니다. 계속할까요?')) return
            try {
              const r = await fetch('/api/server/restart', { method: 'POST' })
              if (r.status === 409) {
                const err = await r.json().catch(() => ({}))
                if (confirm(`${err.detail || '코드 패치 진행 중'}\n\n그래도 강제 재시작할까요? (작업 중단됨)`)) {
                  await fetch('/api/server/restart?force=true', { method: 'POST' })
                }
              }
            } catch { /* 프로세스 종료로 인한 네트워크 에러 무시 */ }
          }}
        />
      </div>
      {showSearch && <SearchPanel onClose={() => setShowSearch(false)} />}
      {showInsight && <InsightPanel onClose={() => setShowInsight(false)} />}
    </aside>
  )
}
