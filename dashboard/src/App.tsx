// AI Office 메신저 — 업무용 채팅 앱
import { useEffect, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatRoom } from './components/ChatRoom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { JobBoard } from './components/JobBoard'
import { GateInbox } from './components/GateInbox'
import { ComponentLibrary } from './components/ComponentLibrary'
import { ToastHost } from './components/ToastHost'
import type { ChannelId } from './types'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 0,
    },
  },
})

const VALID_CHANNELS: ChannelId[] = ['all', 'jobs', 'gates', 'components']

function isChannelId(v: unknown): v is ChannelId {
  return typeof v === 'string' && (VALID_CHANNELS as string[]).includes(v)
}

function MessengerApp() {
  const { theme, activeChannel, setActiveChannel } = useStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const sidebarRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  // 시스템 테마 변경 감지 (사용자가 수동 설정하지 않은 경우)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem('ai-office-theme')) {
        useStore.setState({ theme: e.matches ? 'dark' : 'light' })
      }
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // 초기 진입 시 해시에 채널이 있으면 해당 채널로 이동
  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, '')
    if (isChannelId(hash) && hash !== activeChannel) {
      setActiveChannel(hash)
    }
    // 초기 상태를 history에 기록 (뒤로가기 기준점)
    if (!window.history.state || !isChannelId(window.history.state.channel)) {
      window.history.replaceState({ channel: activeChannel }, '', `#${activeChannel}`)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 채널 변경 시 pushState + 사이드바 닫기 (뒤로가기 대상)
  const navigate = (ch: ChannelId) => {
    if (ch === activeChannel) {
      setSidebarOpen(false)
      return
    }
    setActiveChannel(ch)
    setSidebarOpen(false)
    window.history.pushState({ channel: ch }, '', `#${ch}`)
  }

  // Android 하드웨어 백버튼 / 브라우저 뒤로가기 처리
  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      const state = e.state
      if (state && isChannelId(state.channel)) {
        setActiveChannel(state.channel)
      } else {
        setActiveChannel('all')
      }
      setSidebarOpen(false)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [setActiveChannel])

  // 사이드바 스와이프 닫기 (모바일)
  useEffect(() => {
    const el = sidebarRef.current
    if (!el || !sidebarOpen) return
    let startX = 0
    let dx = 0
    const onStart = (e: TouchEvent) => { startX = e.touches[0].clientX; dx = 0 }
    const onMove = (e: TouchEvent) => {
      dx = e.touches[0].clientX - startX
      if (dx < 0) el.style.transform = `translateX(${Math.max(dx, -288)}px)`
    }
    const onEnd = () => {
      el.style.transform = ''
      if (dx < -60) setSidebarOpen(false)
    }
    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchmove', onMove, { passive: true })
    el.addEventListener('touchend', onEnd)
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
    }
  }, [sidebarOpen])

  return (
    <div className="h-[100dvh] flex bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-gray-100
      pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">

      {/* 모바일 백드롭 */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 좌측 사이드바 */}
      <div
        ref={sidebarRef}
        className={`
          fixed inset-y-0 left-0 z-40 w-[min(288px,85vw)] md:w-72
          transform transition-transform duration-200 ease-in-out
          md:relative md:translate-x-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}>
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      <ToastHost />

      {/* 중앙: 메인 뷰 */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeChannel === 'jobs' ? (
          <JobBoard />
        ) : activeChannel === 'gates' ? (
          <GateInbox />
        ) : activeChannel === 'components' ? (
          <ComponentLibrary onBack={() => navigate('all')} />
        ) : (
          <ChatRoom onMenuClick={() => setSidebarOpen(true)} />
        )}
      </div>

    </div>
  )
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <MessengerApp />
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
