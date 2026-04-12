// 산출물 모달 — 모든 산출물을 날짜별·태스크별로 정리
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import Markdown from 'react-markdown'

interface TaskItem {
  task_id: string
  state: string
  instruction?: string
  created_at?: string
}

interface ArtifactEntry {
  task_id: string
  path: string
  name: string
  type: string
  size: number
  project_title?: string
  created_at?: string
  state?: string
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ko-KR', {
    year: 'numeric', month: 'long', day: 'numeric',
  })
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

const FILE_ICONS: Record<string, { icon: string; color: string }> = {
  md: { icon: 'M', color: 'bg-blue-500' },
  html: { icon: '<>', color: 'bg-orange-500' },
  css: { icon: '#', color: 'bg-purple-500' },
  js: { icon: 'JS', color: 'bg-yellow-500' },
  ts: { icon: 'TS', color: 'bg-blue-600' },
  tsx: { icon: 'TX', color: 'bg-blue-600' },
  py: { icon: 'PY', color: 'bg-green-600' },
  json: { icon: '{}', color: 'bg-gray-500' },
  png: { icon: '🖼', color: 'bg-pink-500' },
  jpg: { icon: '🖼', color: 'bg-pink-500' },
  svg: { icon: 'SV', color: 'bg-pink-400' },
  pdf: { icon: 'PDF', color: 'bg-red-600' },
}

function fileIconBadge(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  const info = FILE_ICONS[ext] ?? { icon: '📄', color: 'bg-gray-400' }
  return (
    <div className={`w-9 h-9 rounded-lg ${info.color} flex items-center justify-center
      text-white text-[10px] font-bold flex-shrink-0`}>
      {info.icon}
    </div>
  )
}

function stateBadge(state: string) {
  const map: Record<string, { style: string; label: string }> = {
    completed: { style: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400', label: '완료' },
    escalated: { style: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400', label: '제출' },
    cancelled: { style: 'bg-gray-100 dark:bg-gray-800 text-gray-500', label: '취소' },
  }
  const info = map[state] ?? { style: 'bg-gray-100 dark:bg-gray-800 text-gray-500', label: state }
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${info.style}`}>{info.label}</span>
}

// 마크다운/텍스트 미리보기 가능 여부
const PREVIEWABLE = new Set(['md', 'txt', 'html', 'css', 'js', 'ts', 'tsx', 'py', 'json', 'yaml', 'yml', 'sh'])

export function ArtifactModal() {
  const { toggleArtifacts } = useStore()
  const [selectedPath, setSelectedPath] = useState('')

  const { data: artifacts = [] } = useQuery<ArtifactEntry[]>({
    queryKey: ['all-artifacts'],
    queryFn: async () => (await fetch('/api/artifacts')).json(),
    refetchInterval: 5000,
  })

  const { data: fileData, isLoading: contentLoading } = useQuery<{ path: string; content: string }>({
    queryKey: ['artifact-content', selectedPath],
    queryFn: async () => {
      const ext = selectedPath.split('.').pop()?.toLowerCase() ?? ''
      // HTML 파일은 서버가 HTMLResponse로 반환하므로 text()로 읽고 래핑
      if (ext === 'html') {
        const text = await (await fetch(`/api/artifacts/${selectedPath}`)).text()
        return { path: selectedPath, content: text }
      }
      const res = await fetch(`/api/artifacts/${selectedPath}`, {
        headers: { 'Accept': 'application/json' },
      })
      return res.json()
    },
    enabled: !!selectedPath,
  })

  // 태스크별 산출물 그룹화 — API가 project_title/created_at/state를 직접 제공
  const taskGroups = new Map<string, ArtifactEntry[]>()
  for (const art of artifacts) {
    if (!taskGroups.has(art.task_id)) taskGroups.set(art.task_id, [])
    taskGroups.get(art.task_id)!.push(art)
  }

  // 날짜별 그룹화 — artifact 자체의 메타데이터 사용 (taskMap join 불필요)
  const dateGroups = new Map<string, { task: TaskItem; files: ArtifactEntry[] }[]>()
  for (const [taskId, files] of taskGroups) {
    // .DS_Store, 빈 파일 필터링
    const visibleFiles = files.filter(f => !f.name.startsWith('.') && f.size > 10)
    if (visibleFiles.length === 0) continue

    // 첫 번째 artifact에서 메타데이터 추출 (같은 task_id의 artifact는 모두 동일한 메타)
    const meta = files[0]
    const task: TaskItem = {
      task_id: taskId,
      state: meta.state || 'completed',
      instruction: meta.project_title || visibleFiles[0]?.path.split('/').slice(1, -1).join('/') || taskId.slice(0, 8),
      created_at: meta.created_at || undefined,
    }

    const dateKey = task.created_at ? formatDate(task.created_at) : '기타'
    if (!dateGroups.has(dateKey)) dateGroups.set(dateKey, [])
    dateGroups.get(dateKey)!.push({ task, files: visibleFiles })
  }
  const sortedDates = Array.from(dateGroups.keys()).sort((a, b) => {
    const da = dateGroups.get(a)![0]?.task.created_at ?? ''
    const db = dateGroups.get(b)![0]?.task.created_at ?? ''
    return db.localeCompare(da)
  })

  // 선택한 파일 확장자
  const selectedExt = selectedPath.split('.').pop()?.toLowerCase() ?? ''
  const isPreviewable = PREVIEWABLE.has(selectedExt)
  const isMarkdown = selectedExt === 'md'
  const isImage = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(selectedExt)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-10">
      <div className="absolute inset-0 bg-black/60" onClick={toggleArtifacts} />

      <div className="relative w-full max-w-3xl h-full max-h-[85vh] flex flex-col
        bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden">

        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-4
          border-b border-gray-200 dark:border-gray-800 flex-shrink-0">
          <div className="flex items-center gap-3">
            {selectedPath && (
              <button
                onClick={() => setSelectedPath('')}
                className="p-1 rounded-lg text-gray-400 hover:text-gray-600
                  dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
                  cursor-pointer transition-colors"
                aria-label="뒤로"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
            )}
            <h2 className="text-base font-semibold">
              {selectedPath ? selectedPath.split('/').pop() : '산출물'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {selectedPath && (
              <a
                href={`/api/artifacts/${selectedPath}`}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
                  dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
                  transition-colors"
                title="새 탭에서 열기"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            )}
            <button
              onClick={toggleArtifacts}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
                dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
                cursor-pointer transition-colors"
              aria-label="닫기"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* 내용 */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {selectedPath ? (
            // 파일 미리보기
            <div className="p-6 md:p-8">
              {contentLoading ? (
                <p className="text-sm text-gray-400 text-center py-8">로딩 중...</p>
              ) : isImage ? (
                <div className="flex justify-center">
                  <img
                    src={`/api/artifacts/${selectedPath}`}
                    alt={selectedPath}
                    className="max-w-full max-h-[60vh] rounded-lg"
                  />
                </div>
              ) : isMarkdown && fileData ? (
                <div className="prose dark:prose-invert prose-sm max-w-none">
                  <Markdown>{fileData.content}</Markdown>
                </div>
              ) : isPreviewable && fileData ? (
                <pre className="text-xs font-mono bg-gray-50 dark:bg-gray-800 rounded-lg p-4
                  overflow-auto max-h-[60vh] whitespace-pre-wrap">
                  {fileData.content}
                </pre>
              ) : (
                <div className="text-center text-gray-400 py-12">
                  <p className="text-sm mb-3">미리보기를 지원하지 않는 파일입니다.</p>
                  <a
                    href={`/api/artifacts/${selectedPath}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-blue-500 hover:text-blue-400"
                  >
                    다운로드
                  </a>
                </div>
              )}
            </div>
          ) : (
            // 날짜별 산출물 목록
            <div className="p-6 md:p-8">
              {sortedDates.length === 0 ? (
                <div className="text-center text-gray-400 py-16">
                  <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p className="text-sm">아직 산출물이 없습니다</p>
                </div>
              ) : (
                sortedDates.map((dateKey) => (
                  <div key={dateKey} className="mb-6">
                    <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                      {dateKey}
                    </h3>
                    {[...dateGroups.get(dateKey)!].sort((a, b) =>
                      (b.task.created_at ?? '').localeCompare(a.task.created_at ?? '')
                    ).map(({ task, files }) => (
                      <div key={task.task_id} className="mb-4">
                        {/* 태스크 헤더 */}
                        <div className="flex items-center gap-2 mb-2">
                          <p className="text-sm font-medium text-gray-700 dark:text-gray-300 truncate flex-1">
                            {task.instruction?.slice(0, 50) || task.task_id.slice(0, 8)}
                          </p>
                          {stateBadge(task.state)}
                          <span className="text-[10px] text-gray-400">
                            {task.created_at ? formatTime(task.created_at) : ''}
                          </span>
                        </div>

                        {/* 파일 목록 */}
                        <ul className="space-y-1 pl-1">
                          {files.map((file) => (
                            <li key={file.path}>
                              <button
                                onClick={() => setSelectedPath(file.path)}
                                className="w-full text-left flex items-center gap-3 p-2.5 rounded-xl
                                  hover:bg-gray-50 dark:hover:bg-gray-800/50
                                  cursor-pointer transition-colors"
                              >
                                {fileIconBadge(file.name)}
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm text-gray-800 dark:text-gray-200 truncate">
                                    {file.name}
                                  </p>
                                  <p className="text-[10px] text-gray-400">
                                    {file.path.split('/').slice(1, -1).join('/') || '루트'} · {formatSize(file.size)}
                                  </p>
                                </div>
                                <svg className="w-4 h-4 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                </svg>
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
