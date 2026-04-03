// 산출물 뷰어 컴포넌트 (DASH-04)
// 파일 트리 + Monaco Editor(코드) + react-markdown(마크다운) 뷰어
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'
import Markdown from 'react-markdown'
import { useStore } from '../store'
import type { Task, FileEntry } from '../types'

// 파일 확장자 → Monaco 언어 매핑
const LANG_MAP: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  html: 'html',
  css: 'css',
  scss: 'scss',
  sh: 'shell',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  md: 'markdown',
  txt: 'plaintext',
  rst: 'restructuredtext',
}

function getLanguage(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
  return LANG_MAP[ext] ?? 'plaintext'
}

function isMarkdown(filePath: string): boolean {
  return filePath.endsWith('.md')
}

async function fetchTasks(): Promise<Task[]> {
  const res = await fetch('/api/tasks')
  if (!res.ok) throw new Error('태스크 목록 로드 실패')
  return res.json() as Promise<Task[]>
}

async function fetchFiles(taskId: string): Promise<FileEntry[]> {
  const res = await fetch(`/api/files/${taskId}`)
  if (!res.ok) throw new Error('파일 목록 로드 실패')
  return res.json() as Promise<FileEntry[]>
}

async function fetchFileContent(taskId: string, filePath: string): Promise<string> {
  const res = await fetch(`/api/files/${taskId}/${filePath}`)
  if (!res.ok) throw new Error('파일 내용 로드 실패')
  const data = await res.json() as { path: string; content: string }
  return data.content
}

// 파일 크기 포맷 (bytes → KB)
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  return `${(bytes / 1024).toFixed(1)}KB`
}

// 파일 타입 색상
function typeColor(type: string): string {
  switch (type) {
    case 'code': return 'text-blue-400'
    case 'doc': return 'text-green-400'
    case 'design': return 'text-purple-400'
    case 'data': return 'text-yellow-400'
    default: return 'text-gray-400'
  }
}

export function ArtifactViewer() {
  const { theme } = useStore()
  const [selectedTaskId, setSelectedTaskId] = useState<string>('')
  const [selectedFile, setSelectedFile] = useState<string>('')

  // 태스크 목록
  const { data: tasks = [] } = useQuery({
    queryKey: ['tasks'],
    queryFn: fetchTasks,
    refetchInterval: 5000,
  })

  // 파일 목록 (태스크 선택 시)
  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ['files', selectedTaskId],
    queryFn: () => fetchFiles(selectedTaskId),
    enabled: !!selectedTaskId,
  })

  // 파일 내용 (파일 선택 시)
  const { data: fileContent, isLoading: contentLoading } = useQuery({
    queryKey: ['fileContent', selectedTaskId, selectedFile],
    queryFn: () => fetchFileContent(selectedTaskId, selectedFile),
    enabled: !!(selectedTaskId && selectedFile),
  })

  const editorTheme = theme === 'dark' ? 'vs-dark' : 'light'

  return (
    <div className="flex h-full gap-3" aria-label="산출물 뷰어">

      {/* 좌측: 파일 트리 */}
      <aside
        className="w-64 flex-shrink-0 flex flex-col gap-3
          bg-white dark:bg-gray-900
          border border-gray-200 dark:border-gray-700
          rounded-lg p-3 overflow-y-auto"
        aria-label="파일 트리"
      >
        {/* 태스크 선택 */}
        <div>
          <label
            htmlFor="task-select"
            className="block text-xs font-semibold uppercase tracking-wider mb-1 opacity-60"
          >
            태스크 선택
          </label>
          <select
            id="task-select"
            value={selectedTaskId}
            onChange={(e) => {
              setSelectedTaskId(e.target.value)
              setSelectedFile('')
            }}
            className="w-full text-xs px-2 py-1.5 rounded border
              bg-gray-50 dark:bg-gray-800
              border-gray-300 dark:border-gray-600
              text-gray-900 dark:text-gray-100
              focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label="태스크 선택"
          >
            <option value="">— 태스크 선택 —</option>
            {tasks.map((task) => (
              <option key={task.task_id} value={task.task_id}>
                {task.task_id.slice(0, 12)}... ({task.state})
              </option>
            ))}
          </select>
        </div>

        {/* 파일 목록 */}
        {selectedTaskId && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-2 opacity-60">
              파일 목록
            </p>
            {filesLoading ? (
              <p className="text-xs opacity-40">로딩 중...</p>
            ) : files.length === 0 ? (
              <p className="text-xs opacity-40">산출물 파일이 없습니다</p>
            ) : (
              <ul className="space-y-0.5" role="list" aria-label="산출물 파일 목록">
                {files.map((file) => (
                  <li key={file.path}>
                    <button
                      onClick={() => setSelectedFile(file.path)}
                      className={`w-full text-left text-xs px-2 py-1 rounded truncate
                        transition-colors cursor-pointer
                        ${selectedFile === file.path
                          ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                          : 'hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300'
                        }`}
                      title={file.path}
                      aria-label={`${file.path} (${formatSize(file.size)})`}
                      aria-pressed={selectedFile === file.path}
                    >
                      <span className={`mr-1 ${typeColor(file.type)}`} aria-hidden="true">
                        {file.type === 'code' ? '' : file.type === 'doc' ? '' : ''}
                      </span>
                      {file.path}
                      <span className="ml-1 text-gray-400 text-[10px]">
                        {formatSize(file.size)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </aside>

      {/* 우측: 파일 내용 뷰어 */}
      <div
        className="flex-1 overflow-hidden rounded-lg border
          border-gray-200 dark:border-gray-700"
        role="region"
        aria-label="파일 내용"
      >
        {!selectedTaskId || !selectedFile ? (
          <div className="h-full flex items-center justify-center text-sm text-gray-400">
            {!selectedTaskId
              ? '좌측에서 태스크를 선택하세요'
              : '파일을 선택하면 내용이 표시됩니다'}
          </div>
        ) : contentLoading ? (
          <div className="h-full flex items-center justify-center text-sm text-gray-400">
            로딩 중...
          </div>
        ) : fileContent == null ? (
          <div className="h-full flex items-center justify-center text-sm text-gray-400">
            파일 내용을 불러올 수 없습니다
          </div>
        ) : isMarkdown(selectedFile) ? (
          // 마크다운 렌더링
          <div
            className="h-full overflow-auto p-4
              prose prose-sm dark:prose-invert max-w-none
              bg-white dark:bg-gray-900"
          >
            <Markdown>{fileContent}</Markdown>
          </div>
        ) : (
          // Monaco Editor (코드 파일)
          <Editor
            height="100%"
            language={getLanguage(selectedFile)}
            value={fileContent}
            theme={editorTheme}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 13,
              lineNumbers: 'on',
              wordWrap: 'on',
            }}
            aria-label={`${selectedFile} 코드 뷰어`}
          />
        )}
      </div>
    </div>
  )
}
