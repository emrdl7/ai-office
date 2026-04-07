// 작업 지시 입력 컴포넌트 (DASH-01, DASH-05)
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useStore } from '../store'
import type { Task } from '../types'

async function fetchTasks(): Promise<Task[]> {
  const res = await fetch('/api/tasks')
  if (!res.ok) throw new Error('태스크 목록 로드 실패')
  return res.json() as Promise<Task[]>
}

async function submitTask(instruction: string, files: File[], baseTaskId: string = ''): Promise<{ task_id: string }> {
  const form = new FormData()
  form.append('instruction', instruction)
  if (baseTaskId) form.append('base_task_id', baseTaskId)
  for (const f of files) {
    form.append('files', f)
  }
  const res = await fetch('/api/tasks', { method: 'POST', body: form })
  if (!res.ok) throw new Error('작업 지시 제출 실패')
  return res.json()
}

function stateDot(state: string): string {
  if (state === 'completed') return 'bg-green-400'
  if (state === 'running') return 'bg-blue-400 animate-pulse'
  if (state.startsWith('error')) return 'bg-red-400'
  return 'bg-gray-400'
}

export function TaskInput() {
  const [instruction, setInstruction] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [baseTaskId, setBaseTaskId] = useState('')
  const setSelectedTaskId = useStore((s) => s.setSelectedTaskId)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const { data: tasks = [], isLoading: tasksLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: fetchTasks,
    refetchInterval: 3000,
  })

  const mutation = useMutation({
    mutationFn: () => submitTask(instruction, files, baseTaskId),
    onSuccess: () => {
      setInstruction('')
      setFiles([])
      setBaseTaskId('')
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  function handleSubmit() {
    if (!instruction.trim()) return
    mutation.mutate()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit()
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files)
      setFiles((prev) => [...prev, ...newFiles])
    }
    e.target.value = ''
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  return (
    <section aria-label="작업 지시">
      <h2 className="text-xs font-semibold uppercase tracking-wider mb-2 opacity-60">
        작업 지시
      </h2>

      <div className="flex flex-col gap-2 mb-4">
        <textarea
          ref={textareaRef}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="팀장에게 작업을 지시하세요... (Cmd+Enter)"
          rows={3}
          className="w-full px-3 py-2 rounded-lg border text-sm resize-none
            bg-white dark:bg-gray-800
            border-gray-300 dark:border-gray-600
            text-gray-900 dark:text-gray-100
            placeholder-gray-400 dark:placeholder-gray-500
            focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label="작업 지시 입력"
          disabled={mutation.isPending}
        />

        {/* 첨부파일 목록 */}
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {files.map((f, i) => (
              <span
                key={`${f.name}-${i}`}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs
                  bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300
                  border border-blue-200 dark:border-blue-800"
              >
                📎 {f.name}
                <button
                  onClick={() => removeFile(i)}
                  className="text-blue-400 hover:text-red-400 cursor-pointer ml-0.5"
                  aria-label={`${f.name} 제거`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* 이전 작업 기반 표시 */}
        {baseTaskId && (
          <div className="flex items-center gap-1 text-xs text-purple-600 dark:text-purple-400">
            <span>🔗 이전 작업 기반:</span>
            <span className="truncate flex-1">
              {tasks.find(t => t.task_id === baseTaskId)?.instruction?.slice(0, 30) || baseTaskId.slice(0, 8)}...
            </span>
            <button onClick={() => setBaseTaskId('')} className="text-purple-400 hover:text-red-400 cursor-pointer">×</button>
          </div>
        )}

        {/* 버튼 영역 */}
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="*/*"
            onChange={handleFileChange}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-2 rounded-lg text-sm
              bg-gray-100 dark:bg-gray-800
              hover:bg-gray-200 dark:hover:bg-gray-700
              border border-gray-300 dark:border-gray-600
              text-gray-600 dark:text-gray-300
              transition-colors cursor-pointer"
            aria-label="파일 첨부"
            disabled={mutation.isPending}
          >
            📎 첨부
          </button>
          <button
            onClick={handleSubmit}
            disabled={mutation.isPending || !instruction.trim()}
            className="flex-1 px-4 py-2 rounded-lg text-sm font-medium
              bg-blue-600 hover:bg-blue-700 disabled:opacity-50
              text-white transition-colors cursor-pointer disabled:cursor-not-allowed"
            aria-label="작업 지시하기"
          >
            {mutation.isPending ? '전송 중...' : '지시하기'}
          </button>
        </div>

        {mutation.isError && (
          <p className="text-red-500 text-xs" role="alert">
            {mutation.error instanceof Error ? mutation.error.message : '오류가 발생했습니다'}
          </p>
        )}
      </div>

      {/* 지시 내역 */}
      <h3 className="text-xs font-semibold uppercase tracking-wider mb-2 opacity-50">
        지시 내역
      </h3>
      {tasksLoading ? (
        <p className="text-xs opacity-50">로딩 중...</p>
      ) : tasks.length === 0 ? (
        <p className="text-xs opacity-40">아직 작업 지시가 없습니다</p>
      ) : (
        <ul className="space-y-1 max-h-48 overflow-y-auto" aria-label="작업 지시 내역">
          {[...tasks].reverse().map((task) => (
            <li
              key={task.task_id}
              className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded cursor-pointer transition-colors
                ${baseTaskId === task.task_id
                  ? 'bg-purple-50 dark:bg-purple-900/30 border border-purple-300 dark:border-purple-700'
                  : 'bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-700/50'
                }`}
              onClick={() => {
                setSelectedTaskId(task.task_id)
                setBaseTaskId(baseTaskId === task.task_id ? '' : task.task_id)
              }}
              title="클릭: 산출물 보기 / 더블클릭: 기반 지시 선택"
            >
              <span
                className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${stateDot(task.state)}`}
              />
              <span className="text-gray-700 dark:text-gray-300 flex-1 min-w-0">
                <span className="truncate block">
                  {task.instruction?.slice(0, 35) || task.task_id.slice(0, 8)}
                  {(task.instruction?.length ?? 0) > 35 ? '...' : ''}
                </span>
                {task.attachments && (
                  <span className="flex flex-wrap gap-0.5 mt-0.5">
                    {task.attachments.split(',').map((name: string, i: number) => (
                      <span
                        key={i}
                        className="inline-block text-[10px] px-1 py-0 rounded
                          bg-blue-50 dark:bg-blue-900/30 text-blue-500 dark:text-blue-400
                          border border-blue-200 dark:border-blue-800 truncate max-w-[120px]"
                        title={name.trim()}
                      >
                        📎 {name.trim()}
                      </span>
                    ))}
                  </span>
                )}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  if (confirm('이 작업을 삭제할까요?')) {
                    fetch(`/api/tasks/${task.task_id}`, { method: 'DELETE' })
                      .then(() => queryClient.invalidateQueries({ queryKey: ['tasks'] }))
                  }
                }}
                className="text-[10px] text-gray-400 hover:text-red-500 cursor-pointer flex-shrink-0 ml-1"
                aria-label="삭제"
              >✕</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
