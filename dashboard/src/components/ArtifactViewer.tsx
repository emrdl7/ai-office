// 산출물 뷰어 — 최종 산출물 중심, 작업 과정은 접기
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'
import Markdown from 'react-markdown'
import { useStore } from '../store'
// selectedTaskId는 store에서 가져옴

interface ArtifactEntry {
  task_id: string
  path: string
  name: string
  type: string
  size: number
}

const LANG_MAP: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript',
  js: 'javascript', jsx: 'javascript', html: 'html',
  css: 'css', json: 'json', yaml: 'yaml', yml: 'yaml',
  md: 'markdown', txt: 'plaintext', sh: 'shell',
}

function getLanguage(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return LANG_MAP[ext] ?? 'plaintext'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  return `${(bytes / 1024).toFixed(1)}KB`
}

export function ArtifactViewer() {
  const { theme } = useStore()
  const [selectedPath, setSelectedPath] = useState<string>('')
  const [showProcess, setShowProcess] = useState(false)

  const selectedTaskId = useStore((s) => s.selectedTaskId)

  const { data: artifacts = [] } = useQuery<ArtifactEntry[]>({
    queryKey: ['artifacts', selectedTaskId],
    queryFn: async () => {
      const url = selectedTaskId ? `/api/artifacts?task_id=${selectedTaskId}` : '/api/artifacts'
      const res = await fetch(url)
      if (!res.ok) throw new Error('산출물 로드 실패')
      return res.json()
    },
    refetchInterval: 5000,
  })

  const { data: fileData, isLoading: contentLoading } = useQuery<{ path: string; content: string }>({
    queryKey: ['artifact-content', selectedPath],
    queryFn: async () => {
      const res = await fetch(`/api/artifacts/${selectedPath}`)
      if (!res.ok) throw new Error('파일 내용 로드 실패')
      return res.json()
    },
    enabled: !!selectedPath,
  })

  // 최종 산출물 (final/ 폴더) vs 작업 과정 파일 분리
  const finalFiles = artifacts.filter((a) => a.path.startsWith('final/'))
  const processFiles = artifacts.filter((a) => !a.path.startsWith('final/') && a.name !== 'result.json')

  // 최종 산출물 자동 선택
  const [autoSelected, setAutoSelected] = useState(false)
  useEffect(() => {
    if (!autoSelected && finalFiles.length > 0 && !selectedPath) {
      const md = finalFiles.find((a) => a.name.endsWith('.md'))
      if (md) {
        setSelectedPath(md.path)
        setAutoSelected(true)
      }
    }
  }, [finalFiles, selectedPath, autoSelected])

  const isMarkdown = selectedPath.endsWith('.md')

  // 다운로드 핸들러
  function handleDownload() {
    if (!fileData) return
    const blob = new Blob([fileData.content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = selectedPath.split('/').pop() || 'download.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  if (artifacts.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 text-sm">
        <p className="text-2xl mb-2 opacity-30">📄</p>
        <p>아직 산출물이 없습니다</p>
        <p className="text-xs mt-1 opacity-60">작업이 완료되면 결과물이 표시됩니다</p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col" role="region" aria-label="산출물 뷰어">

      {/* 헤더 — 최종 산출물 탭 + 다운로드 */}
      <div className="flex items-center justify-between mb-3 flex-shrink-0">
        <h2 className="text-xs font-semibold uppercase tracking-wider opacity-60">
          {finalFiles.length > 0 ? '최종 산출물' : '산출물'}
        </h2>
        <div className="flex gap-2">
          {fileData && (
            <button
              onClick={handleDownload}
              className="text-xs px-2 py-1 rounded
                bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400
                hover:bg-blue-100 dark:hover:bg-blue-900/50
                cursor-pointer transition-colors"
              aria-label="다운로드"
            >
              ⬇ 다운로드
            </button>
          )}
        </div>
      </div>

      {/* 최종 산출물 파일 선택 */}
      {finalFiles.length > 0 && (
        <div className="flex gap-1 mb-2 flex-shrink-0 flex-wrap">
          {finalFiles.map((f) => (
            <button
              key={f.path}
              onClick={() => setSelectedPath(f.path)}
              className={`text-xs px-2 py-1 rounded cursor-pointer transition-colors
                ${selectedPath === f.path
                  ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                }`}
            >
              📄 {f.name} <span className="opacity-50">{formatSize(f.size)}</span>
            </button>
          ))}
        </div>
      )}

      {/* 문서 내용 */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {!selectedPath ? (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm">
            파일을 선택하세요
          </div>
        ) : contentLoading ? (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm">
            로딩 중...
          </div>
        ) : fileData ? (
          <div className="h-full flex flex-col">
            <div className="text-[10px] text-gray-400 mb-1 font-mono">{selectedPath}</div>
            {isMarkdown ? (
              <div className="flex-1 overflow-auto prose dark:prose-invert prose-sm max-w-none
                px-4 py-3 bg-white dark:bg-gray-900 rounded-lg
                border border-gray-200 dark:border-gray-700">
                <Markdown>{fileData.content}</Markdown>
              </div>
            ) : (
              <div className="flex-1 rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                <Editor
                  value={fileData.content}
                  language={getLanguage(selectedPath)}
                  theme={theme === 'dark' ? 'vs-dark' : 'light'}
                  options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    fontSize: 13,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    wordWrap: 'on',
                  }}
                />
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* 작업 과정 파일 — 접기/펼치기 */}
      {processFiles.length > 0 && (
        <div className="mt-3 flex-shrink-0">
          <button
            onClick={() => setShowProcess(!showProcess)}
            className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300
              cursor-pointer transition-colors"
          >
            {showProcess ? '▼' : '▶'} 작업 과정 파일 ({processFiles.length}개)
          </button>
          {showProcess && (
            <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
              {processFiles.map((f) => (
                <li key={f.path}>
                  <button
                    onClick={() => setSelectedPath(f.path)}
                    className={`w-full text-left text-[11px] px-2 py-1 rounded cursor-pointer
                      ${selectedPath === f.path
                        ? 'bg-gray-200 dark:bg-gray-700'
                        : 'hover:bg-gray-100 dark:hover:bg-gray-800'
                      } text-gray-500 dark:text-gray-400`}
                  >
                    {f.task_id}/{f.name} <span className="opacity-50">{formatSize(f.size)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
