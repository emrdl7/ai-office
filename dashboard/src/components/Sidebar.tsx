// 사이드바 — 채널 선택
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import type { ChannelId } from '../types'
import { MatIcon } from './icons'
import { SearchPanel } from './SearchPanel'
import { InsightPanel } from './InsightPanel'

// Gate Inbox 버튼 — 대기 수 실시간 뱃지
function GateInboxButton({
  activeChannel,
  selectChannel,
}: {
  activeChannel: string
  selectChannel: (ch: import('../types').ChannelId) => void
}) {
  const { data: gates = [] } = useQuery({
    queryKey: ['pending-gates'],
    queryFn: async () => {
      const res = await fetch('/api/jobs/gates/pending')
      if (!res.ok) return []
      return res.json() as Promise<{ gate_id: string }[]>
    },
    refetchInterval: 10000,
  })

  return (
    <button
      onClick={() => selectChannel('gates')}
      className={`w-full text-left px-3 py-2 rounded-xl text-sm cursor-pointer transition-colors touch-manipulation
        flex items-center gap-2 mt-0.5 min-h-[44px] md:min-h-0
        ${activeChannel === 'gates'
          ? 'bg-blue-600/15 text-blue-400 font-medium'
          : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-200'
        }`}
    >
      <MatIcon name="pending_actions" className="text-[16px]" />
      <span className="flex-1">Gate Inbox</span>
      {gates.length > 0 && (
        <span className="px-1.5 py-0.5 text-[9px] font-bold rounded-full bg-yellow-500 text-white">
          {gates.length}
        </span>
      )}
    </button>
  )
}

function SidebarBtn({
  icon, label, onClick, title,
}: {
  icon: string
  label: string
  onClick: () => void
  title?: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg touch-manipulation
        text-sm text-gray-600 dark:text-gray-400
        min-h-[44px] md:min-h-0
        hover:bg-gray-100 dark:hover:bg-gray-800
        cursor-pointer transition-colors"
    >
      <MatIcon name={icon} className="text-[18px] shrink-0" />
      <span>{label}</span>
    </button>
  )
}

interface SidebarProps {
  onClose?: () => void
  navigate?: (ch: ChannelId) => void
}

export function Sidebar({ onClose, navigate }: SidebarProps) {
  const { activeChannel, setActiveChannel, toggleTheme, theme } = useStore()
  const [showSearch, setShowSearch] = useState(false)
  const [showInsight, setShowInsight] = useState(false)

  function selectChannel(channel: ChannelId) {
    if (navigate) {
      navigate(channel)
    } else {
      setActiveChannel(channel)
      onClose?.()
    }
  }

  return (
    <aside
      className="w-[min(288px,85vw)] md:w-72 h-full flex-shrink-0 flex flex-col
        bg-white dark:bg-gray-950
        border-r border-gray-200 dark:border-gray-800
        pt-[env(safe-area-inset-top)]"
      aria-label="채널 목록"
    >
      {/* 헤더 */}
      <div className="px-4 py-3 flex items-center justify-between border-b border-gray-200 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-bold text-lg">AI</span>
          <h1 className="text-sm font-semibold text-gray-900 dark:text-white">Office</h1>
        </div>
        <div className="flex gap-1 items-center">
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded-lg text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800
              min-w-[44px] min-h-[44px] md:min-w-0 md:min-h-0
              flex items-center justify-center
              cursor-pointer transition-colors touch-manipulation"
            aria-label="테마 전환"
            title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
          >
            {theme === 'dark'
              ? <MatIcon name="light_mode" className="text-[16px]" />
              : <MatIcon name="dark_mode" className="text-[16px]" />
            }
          </button>
          {/* 모바일 전용 닫기 버튼 */}
          {onClose && (
            <button
              onClick={onClose}
              className="md:hidden p-2 rounded-lg min-w-[44px] min-h-[44px]
                flex items-center justify-center
                text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800
                cursor-pointer touch-manipulation"
              aria-label="사이드바 닫기"
            >
              <MatIcon name="close" className="text-[18px]" />
            </button>
          )}
        </div>
      </div>

      {/* 채널 */}
      <div className="px-3 pt-4 pb-2 flex-1">
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 px-2 mb-1.5">
          채널
        </h3>
        <button
          onClick={() => selectChannel('all')}
          className={`w-full text-left px-3 py-2 rounded-xl text-sm cursor-pointer transition-colors touch-manipulation
            flex items-center gap-2 min-h-[44px] md:min-h-0
            ${activeChannel === 'all'
              ? 'bg-blue-600/15 text-blue-400 font-medium'
              : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-200'
            }`}
        >
          <span className="text-base">#</span>
          <span>팀 채널</span>
        </button>

        {/* Job Board */}
        <button
          onClick={() => selectChannel('jobs')}
          className={`w-full text-left px-3 py-2 rounded-xl text-sm cursor-pointer transition-colors touch-manipulation
            flex items-center gap-2 mt-0.5 min-h-[44px] md:min-h-0
            ${activeChannel === 'jobs'
              ? 'bg-blue-600/15 text-blue-400 font-medium'
              : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-200'
            }`}
        >
          <MatIcon name="work" className="text-[16px]" />
          <span>Job Board</span>
        </button>

        {/* Gate Inbox */}
        <GateInboxButton activeChannel={activeChannel} selectChannel={selectChannel} />
      </div>

      {/* 하단 메뉴 */}
      <div className="mt-auto p-3 border-t border-gray-200 dark:border-gray-800 space-y-0.5
        pb-[max(12px,env(safe-area-inset-bottom))]">
        <SidebarBtn icon="search" label="통합 검색" onClick={() => setShowSearch(true)} />
        <SidebarBtn icon="insights" label="인사이트" onClick={() => setShowInsight(true)} />
        <SidebarBtn
          icon="restart_alt"
          label="서버 재시작"
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
          title="백엔드만 재시작 (코드 병합 후 반영용)"
        />
      </div>
      {showSearch && <SearchPanel onClose={() => setShowSearch(false)} />}
      {showInsight && <InsightPanel onClose={() => setShowInsight(false)} />}
    </aside>
  )
}
