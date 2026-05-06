// 사이드바 — v2 리디자인: 브랜드 마크 + 채널 pill + 유틸리티
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
}

const CHANNELS: ChannelDef[] = [
  { id: 'all',         label: 'TALK',              icon: 'forum'        },
  { id: 'jobs',        label: '작업 보드',          icon: 'view_kanban'  },
  { id: 'gates',       label: '검토 수신함',        icon: 'rule'         },
  { id: 'workreport',  label: '업무일지',           icon: 'edit_note'    },
  { id: 'components',  label: '컴포넌트 라이브러리', icon: 'widgets'      },
]

const ACCENT_ACTIVE = 'bg-white/10 text-white'
const ACCENT_BAR = 'bg-indigo-400'
const BADGE_BG = 'bg-indigo-500'

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
      className={`group relative w-full flex items-center gap-3 pl-3 pr-3 py-2.5 rounded-lg
        text-sm cursor-pointer transition-colors
        ${active
          ? ACCENT_ACTIVE + ' font-semibold'
          : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'}`}
    >
      <span className={`absolute left-0 top-2 bottom-2 w-[3px] rounded-full
        ${active ? ACCENT_BAR : 'opacity-0'}`} />
      <MatIcon name={def.icon} className={`text-[18px] shrink-0
        ${active ? '' : 'opacity-80'}`} />
      <span className="flex-1 text-left">{def.label}</span>
      {badge !== undefined && badge > 0 && (
        <span className={`inline-flex items-center justify-center min-w-[20px] h-[20px] px-1.5
          rounded-full text-[10px] font-bold ${BADGE_BG} text-white`}>
          {badge}
        </span>
      )}
    </button>
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
        text-[13px] text-slate-400
        hover:bg-white/5 hover:text-slate-100
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
      className="w-72 h-full flex-shrink-0 flex flex-col relative overflow-hidden
        sidebar-shell text-slate-100"
      aria-label="채널 목록"
    >
      {/* 브랜드 헤더 */}
      <div className="relative px-4 h-[64px] flex items-center justify-between shrink-0
        border-b border-white/10">
        <div className="flex items-center gap-2.5">
          <div className="relative w-9 h-9 rounded-lg bg-indigo-500
            flex items-center justify-center">
            <MatIcon name="auto_awesome" className="text-white text-[18px]" />
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-slate-950" />
          </div>
          <div className="leading-tight">
            <h1 className="text-[14px] font-semibold text-white tracking-tight">AI Office</h1>
            <p className="text-[10px] text-slate-400 font-medium tracking-[0.08em] uppercase">Work agent</p>
          </div>
        </div>
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg text-slate-400
            hover:text-white hover:bg-white/10
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
        <h3 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500 px-2 mb-2">
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

      <div className="relative flex-1" />

      {/* 하단 유틸 */}
      <div className="relative mt-auto p-3 border-t border-white/10 space-y-0.5">
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
      {showInsight && (
        <InsightPanel
          onClose={() => setShowInsight(false)}
          onOpenComponents={() => setActiveChannel('components')}
        />
      )}
    </aside>
  )
}
