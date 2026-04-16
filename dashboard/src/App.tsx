// AI Office 메신저 — 업무용 채팅 앱
import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatRoom } from './components/ChatRoom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { JobBoard } from './components/JobBoard'
import { GateInbox } from './components/GateInbox'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 0,
    },
  },
})

function MessengerApp() {
  const { theme, activeChannel } = useStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)

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

  return (
    <div className="h-screen flex bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-gray-100">

      {/* 모바일 백드롭 */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 좌측 사이드바 */}
      <div className={`
        fixed inset-y-0 left-0 z-40 w-72
        transform transition-transform duration-200 ease-in-out
        md:relative md:translate-x-0
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      {/* 중앙: 메인 뷰 */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeChannel === 'jobs' ? (
          <JobBoard />
        ) : activeChannel === 'gates' ? (
          <GateInbox />
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
