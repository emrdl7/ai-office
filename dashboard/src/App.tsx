// AI Office 대시보드 메인 앱 컴포넌트
import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useStore } from './store'
import { TaskInput } from './components/TaskInput'
import { AgentBoard } from './components/AgentBoard'
import { LogStream } from './components/LogStream'
import { ArtifactViewer } from './components/ArtifactViewer'
import { DagView } from './components/DagView'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 0,
    },
  },
})

// 탭 설정
const TABS: { key: 'logs' | 'artifacts' | 'dag'; label: string }[] = [
  { key: 'logs', label: '로그' },
  { key: 'artifacts', label: '산출물' },
  { key: 'dag', label: 'DAG' },
]

function DashboardContent() {
  const { theme, toggleTheme, activeTab, setActiveTab } = useStore()

  // 다크/라이트 클래스를 html 루트에 적용
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
          <h1 className="text-base font-semibold">AI Office Dashboard</h1>
        </div>

        {/* 다크/라이트 토글 */}
        <button
          onClick={toggleTheme}
          className="px-3 py-1.5 rounded-lg text-sm
            bg-gray-100 dark:bg-gray-800
            hover:bg-gray-200 dark:hover:bg-gray-700
            border border-gray-200 dark:border-gray-700
            transition-colors cursor-pointer"
          aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
        >
          {theme === 'dark' ? '라이트' : '다크'}
        </button>
      </header>

      {/* 메인 레이아웃 */}
      <main className="flex gap-0 h-[calc(100vh-53px)]" role="main">

        {/* 좌측 패널 (1/3): 작업 지시 + 에이전트 상태 */}
        <aside
          className="w-1/3 flex flex-col gap-6 p-4 overflow-y-auto
            bg-white dark:bg-gray-900
            border-r border-gray-200 dark:border-gray-800"
          aria-label="작업 제어 패널"
        >
          <TaskInput />
          <hr className="border-gray-200 dark:border-gray-800" />
          <AgentBoard />
        </aside>

        {/* 우측 패널 (2/3): 탭 구성 */}
        <section
          className="flex-1 flex flex-col overflow-hidden"
          aria-label="콘텐츠 패널"
        >
          {/* 탭 헤더 */}
          <div
            className="flex border-b border-gray-200 dark:border-gray-800
              bg-white dark:bg-gray-900"
            role="tablist"
            aria-label="대시보드 탭"
          >
            {TABS.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={activeTab === tab.key}
                aria-controls={`tabpanel-${tab.key}`}
                onClick={() => setActiveTab(tab.key)}
                className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer
                  ${activeTab === tab.key
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                  }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* 탭 패널 */}
          <div className="flex-1 overflow-hidden p-4">
            {activeTab === 'logs' && (
              <div
                id="tabpanel-logs"
                role="tabpanel"
                aria-label="로그 탭"
                className="h-full"
              >
                <LogStream />
              </div>
            )}
            {activeTab === 'artifacts' && (
              <div
                id="tabpanel-artifacts"
                role="tabpanel"
                aria-label="산출물 탭"
                className="h-full overflow-auto"
              >
                <ArtifactViewer />
              </div>
            )}
            {activeTab === 'dag' && (
              <div
                id="tabpanel-dag"
                role="tabpanel"
                aria-label="DAG 탭"
                className="h-full"
              >
                <DagView />
              </div>
            )}
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
