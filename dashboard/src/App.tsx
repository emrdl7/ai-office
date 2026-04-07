// AI Office 대시보드 메인 앱 컴포넌트
import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useStore } from './store'
import { TaskInput } from './components/TaskInput'
import { AgentBoard } from './components/AgentBoard'
import { LogStream } from './components/LogStream'
import { ArtifactViewer } from './components/ArtifactViewer'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 0,
    },
  },
})

function DashboardContent() {
  const { theme, toggleTheme } = useStore()

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  return (
    <div className="min-h-screen bg-gray-100 dark:bg-gray-950 text-gray-900 dark:text-gray-100 transition-colors">

      {/* 상단 헤더 */}
      <header
        className="flex items-center justify-between px-6 py-3
          bg-white dark:bg-gray-900
          border-b border-gray-200 dark:border-gray-800
          sticky top-0 z-10"
        role="banner"
      >
        <div className="flex items-center gap-3">
          <span className="text-blue-500 font-bold text-lg" aria-hidden="true">AI</span>
          <h1 className="text-base font-semibold">AI Office</h1>
        </div>
        <button
          onClick={toggleTheme}
          className="px-3 py-1.5 rounded-lg text-sm
            bg-gray-100 dark:bg-gray-800
            hover:bg-gray-200 dark:hover:bg-gray-700
            border border-gray-200 dark:border-gray-700
            transition-colors cursor-pointer"
          aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </header>

      {/* 메인 레이아웃: 3단 구성 */}
      <main className="flex h-[calc(100vh-53px)]" role="main">

        {/* 좌측: 작업지시 + 에이전트 상태 */}
        <aside
          className="w-72 flex-shrink-0 flex flex-col p-4 overflow-y-auto
            bg-white dark:bg-gray-900
            border-r border-gray-200 dark:border-gray-800"
          aria-label="작업 제어 패널"
        >
          <TaskInput />
          <hr className="border-gray-200 dark:border-gray-800 my-4" />
          <AgentBoard />
        </aside>

        {/* 중앙: 실시간 로그 */}
        <section
          className="flex-1 flex flex-col min-w-0 border-r border-gray-200 dark:border-gray-800"
          aria-label="실시간 로그"
        >
          <div className="p-4 h-full">
            <LogStream />
          </div>
        </section>

        {/* 우측: 산출물 */}
        <section
          className="w-[40%] flex-shrink-0 flex flex-col min-w-0 overflow-hidden"
          aria-label="산출물"
        >
          <div className="p-4 h-full overflow-auto">
            <ArtifactViewer />
          </div>
        </section>

      </main>
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <DashboardContent />
    </QueryClientProvider>
  )
}

export default App
