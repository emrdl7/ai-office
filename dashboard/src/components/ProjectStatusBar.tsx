// 프로젝트 실시간 상태 바 — /api/project/status 2초 폴링
import { useQuery } from '@tanstack/react-query'

interface ProjectStatus {
  state: string
  project_id: string
  title: string
  active_agent: string
  current_phase: string
  work_started_at: string
  elapsed_sec: number
  revision_count: number
  nodes: { total: number; completed: number; in_progress: number } | null
}

function formatElapsed(sec: number): string {
  if (sec <= 0) return ''
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m === 0) return `${s}s`
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

const STATE_LABEL: Record<string, string> = {
  idle: '대기',
  working: '작업중',
  qa_review: 'QA 검토',
  revising: '수정중',
  meeting: '회의',
  teamlead_review: '팀장 리뷰',
}

export function ProjectStatusBar() {
  const { data } = useQuery<ProjectStatus>({
    queryKey: ['project-status'],
    queryFn: async () => {
      const r = await fetch('/api/project/status')
      return r.json()
    },
    refetchInterval: 2000,
  })

  if (!data || data.state === 'idle') return null

  const stateLabel = STATE_LABEL[data.state] ?? data.state
  const elapsed = formatElapsed(data.elapsed_sec)

  return (
    <div className="px-4 py-1.5 bg-amber-50 dark:bg-amber-900/20
      border-b border-amber-100 dark:border-amber-800
      flex flex-wrap items-center gap-x-3 gap-y-1 text-xs
      text-amber-700 dark:text-amber-300">
      <span className="inline-flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
        <span className="font-medium">{stateLabel}</span>
      </span>
      {data.current_phase && (
        <span>· <span className="font-medium">{data.current_phase}</span></span>
      )}
      {data.active_agent && (
        <span>· {data.active_agent}</span>
      )}
      {elapsed && <span>· ⏱ {elapsed}</span>}
      {data.revision_count > 0 && <span>· rev {data.revision_count}</span>}
      {data.nodes && data.nodes.total > 0 && (
        <span>
          · 노드 {data.nodes.completed}/{data.nodes.total}
          {data.nodes.in_progress > 0 && ` (진행 ${data.nodes.in_progress})`}
        </span>
      )}
    </div>
  )
}
