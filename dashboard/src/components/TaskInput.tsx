// 작업 지시 입력 컴포넌트 (DASH-01, DASH-05)
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Task } from '../types'

async function fetchTasks(): Promise<Task[]> {
  const res = await fetch('/api/tasks')
  if (!res.ok) throw new Error('태스크 목록 로드 실패')
  return res.json() as Promise<Task[]>
}

async function submitTask(instruction: string): Promise<{ task_id: string; status: string }> {
  const res = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction }),
  })
  if (!res.ok) throw new Error('작업 지시 제출 실패')
  return res.json() as Promise<{ task_id: string; status: string }>
}

// 상태에 따른 배지 색상
function stateBadgeClass(state: string): string {
  switch (state) {
    case 'IDLE': return 'bg-gray-500'
    case 'RUNNING': return 'bg-blue-500'
    case 'DONE': return 'bg-green-500'
    case 'FAILED': return 'bg-red-500'
    default: return 'bg-gray-400'
  }
}

export function TaskInput() {
  const [instruction, setInstruction] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const queryClient = useQueryClient()

  const { data: tasks = [], isLoading: tasksLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: fetchTasks,
    refetchInterval: 3000,
  })

  const mutation = useMutation({
    mutationFn: submitTask,
    onSuccess: () => {
      setInstruction('')
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  function handleSubmit() {
    const trimmed = instruction.trim()
    if (!trimmed) return
    mutation.mutate(trimmed)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit()
    }
  }

  return (
    <section aria-label="작업 지시">
      <h2 className="text-sm font-semibold uppercase tracking-wider mb-2 opacity-60">
        작업 지시
      </h2>

      {/* 입력 영역 */}
      <div className="flex flex-col gap-2 mb-4">
        <textarea
          ref={textareaRef}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Claude 팀장에게 작업을 지시하세요... (Cmd+Enter로 전송)"
          rows={4}
          className="w-full px-3 py-2 rounded-lg border text-sm resize-none
            bg-white dark:bg-gray-800
            border-gray-300 dark:border-gray-600
            text-gray-900 dark:text-gray-100
            placeholder-gray-400 dark:placeholder-gray-500
            focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label="작업 지시 입력"
          disabled={mutation.isPending}
        />
        <button
          onClick={handleSubmit}
          disabled={mutation.isPending || !instruction.trim()}
          className="px-4 py-2 rounded-lg text-sm font-medium
            bg-blue-600 hover:bg-blue-700 disabled:opacity-50
            text-white transition-colors cursor-pointer disabled:cursor-not-allowed"
          aria-label="작업 지시하기"
        >
          {mutation.isPending ? '전송 중...' : '지시하기'}
        </button>
        {mutation.isError && (
          <p className="text-red-500 text-xs" role="alert">
            {mutation.error instanceof Error ? mutation.error.message : '오류가 발생했습니다'}
          </p>
        )}
      </div>

      {/* 지시 내역 목록 */}
      <h3 className="text-xs font-semibold uppercase tracking-wider mb-2 opacity-50">
        지시 내역
      </h3>
      {tasksLoading ? (
        <p className="text-xs opacity-50">로딩 중...</p>
      ) : tasks.length === 0 ? (
        <p className="text-xs opacity-40">아직 작업 지시가 없습니다</p>
      ) : (
        <ul className="space-y-1 max-h-48 overflow-y-auto" aria-label="작업 지시 내역">
          {tasks.map((task) => (
            <li
              key={task.task_id}
              className="flex items-center gap-2 text-xs px-2 py-1 rounded
                bg-gray-50 dark:bg-gray-800/50"
            >
              <span
                className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${stateBadgeClass(task.state)}`}
                aria-label={`상태: ${task.state}`}
              />
              <span className="font-mono text-gray-500 dark:text-gray-400 truncate">
                {task.task_id.slice(0, 8)}...
              </span>
              <span className="ml-auto text-gray-400 dark:text-gray-500">
                {task.state}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
