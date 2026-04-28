// 업무일지 — 일별 작업 기록 / 등록 / 진행도 관리 + 주간 취합
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MatIcon } from './icons'

interface WeeklySummary {
  period: { start: string; end: string }
  groups: Record<string, WRTask[]>
  overdue: WRTask[]
  total: number
  copy_text: string
}

interface WRTask {
  id: number
  date: string
  time: string
  project: string
  task_name: string
  task_detail: string
  progress: number
  due_date: string | null
  created_at: string
}

interface Dashboard {
  today: string
  today_count: number
  total_count: number
  avg_progress_today: number
  overdue_count: number
  active_projects: number
  recent_tasks: WRTask[]
}

function progressColor(p: number) {
  if (p >= 100) return 'bg-green-500'
  if (p >= 60)  return 'bg-blue-500'
  if (p >= 30)  return 'bg-yellow-400'
  return 'bg-gray-300 dark:bg-gray-600'
}

function TaskCard({ task, onProgressChange, onDelete }: {
  task: WRTask
  onProgressChange: (id: number, progress: number) => void
  onDelete: (id: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(task.progress)

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {task.project && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full
                bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400">
                {task.project}
              </span>
            )}
            <span className="text-[10px] text-gray-400">{task.time}</span>
            {task.due_date && (
              <span className="text-[10px] text-orange-500">{task.due_date} 마감</span>
            )}
          </div>
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 mt-1">
            {task.task_name}
          </p>
          {task.task_detail && task.task_detail !== task.task_name && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
              {task.task_detail}
            </p>
          )}

          {/* 진행도 바 */}
          <div className="mt-2">
            {editing ? (
              <div className="flex items-center gap-2">
                <input
                  type="range" min={0} max={100} step={5}
                  value={draft}
                  onChange={e => setDraft(Number(e.target.value))}
                  className="flex-1 accent-teal-500"
                />
                <span className="text-xs tabular-nums w-8">{draft}%</span>
                <button
                  onClick={() => { onProgressChange(task.id, draft); setEditing(false) }}
                  className="text-xs px-2 py-0.5 rounded bg-teal-600 text-white cursor-pointer"
                >저장</button>
                <button
                  onClick={() => { setDraft(task.progress); setEditing(false) }}
                  className="text-xs text-gray-400 cursor-pointer"
                >취소</button>
              </div>
            ) : (
              <button
                onClick={() => setEditing(true)}
                className="w-full text-left cursor-pointer group"
              >
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${progressColor(task.progress)}`}
                      style={{ width: `${task.progress}%` }}
                    />
                  </div>
                  <span className="text-[10px] tabular-nums text-gray-500 group-hover:text-teal-500 transition-colors">
                    {task.progress}%
                  </span>
                </div>
              </button>
            )}
          </div>
        </div>

        <button
          onClick={() => onDelete(task.id)}
          className="p-1 rounded-lg text-gray-300 hover:text-red-400 dark:hover:text-red-500
            hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors cursor-pointer shrink-0"
        >
          <MatIcon name="close" className="text-[14px]" />
        </button>
      </div>
    </div>
  )
}

function AddTaskForm({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [project, setProject] = useState('')
  const [detail, setDetail] = useState('')
  const [progress, setProgress] = useState(0)

  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async () => {
      const res = await fetch('/api/workreport/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_name: name, project, task_detail: detail, progress }),
      })
      if (!res.ok) throw new Error('등록 실패')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['wr-daily'] })
      qc.invalidateQueries({ queryKey: ['wr-dashboard'] })
      setName(''); setProject(''); setDetail(''); setProgress(0)
      setOpen(false)
      onAdded()
    },
  })

  if (!open) return (
    <button
      onClick={() => setOpen(true)}
      className="w-full flex items-center gap-2 px-4 py-2.5 rounded-xl border-2 border-dashed
        border-gray-200 dark:border-gray-700 text-gray-400 hover:text-teal-500
        hover:border-teal-300 dark:hover:border-teal-700 transition-colors cursor-pointer text-sm"
    >
      <MatIcon name="add" className="text-[16px]" />
      작업 직접 추가
    </button>
  )

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-teal-300 dark:border-teal-700 p-4 space-y-3">
      <input
        autoFocus
        value={name}
        onChange={e => setName(e.target.value)}
        placeholder="작업명 *"
        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
          bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100
          focus:outline-none focus:ring-2 focus:ring-teal-400/50"
      />
      <div className="flex gap-2">
        <input
          value={project}
          onChange={e => setProject(e.target.value)}
          placeholder="프로젝트"
          className="flex-1 px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700
            bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100
            focus:outline-none focus:ring-2 focus:ring-teal-400/50"
        />
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-xs text-gray-500">진행도</span>
          <input
            type="number" min={0} max={100} step={10}
            value={progress}
            onChange={e => setProgress(Number(e.target.value))}
            className="w-16 px-2 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700
              bg-gray-50 dark:bg-gray-800 text-center
              focus:outline-none focus:ring-2 focus:ring-teal-400/50"
          />
          <span className="text-xs text-gray-500">%</span>
        </div>
      </div>
      <textarea
        value={detail}
        onChange={e => setDetail(e.target.value)}
        placeholder="세부 내용 (선택)"
        rows={2}
        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
          bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none
          focus:outline-none focus:ring-2 focus:ring-teal-400/50"
      />
      <div className="flex gap-2 justify-end">
        <button
          onClick={() => setOpen(false)}
          className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 cursor-pointer"
        >취소</button>
        <button
          onClick={() => add.mutate()}
          disabled={!name.trim() || add.isPending}
          className="px-4 py-1.5 text-sm font-medium text-white bg-teal-600 hover:bg-teal-700
            rounded-lg cursor-pointer disabled:opacity-50 transition-colors"
        >
          {add.isPending ? '등록 중...' : '등록'}
        </button>
      </div>
    </div>
  )
}

function toLocalISODate(dt: Date): string {
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const d = String(dt.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function getWeekStart(d: string): string {
  const dt = new Date(d + 'T00:00:00')
  const day = dt.getDay() // 0=일, 1=월 ...
  dt.setDate(dt.getDate() - (day === 0 ? 6 : day - 1)) // 월요일 기준
  return toLocalISODate(dt)
}

function WeeklySummaryView({ weekStart }: { weekStart: string }) {
  const [copied, setCopied] = useState(false)
  const { data, isLoading } = useQuery<WeeklySummary>({
    queryKey: ['wr-weekly-summary', weekStart],
    queryFn: async () => {
      const res = await fetch(`/api/workreport/weekly-summary?start=${weekStart}`)
      if (!res.ok) throw new Error()
      return res.json()
    },
  })

  function copy() {
    if (!data?.copy_text) return
    navigator.clipboard.writeText(data.copy_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (isLoading) return (
    <div className="flex items-center justify-center py-16 text-gray-400">
      <MatIcon name="hourglass_empty" className="text-[36px]" />
    </div>
  )

  if (!data || data.total === 0) return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <p className="text-sm text-gray-500">이번 주 기록된 작업이 없습니다</p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* 복사 텍스트 박스 */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 dark:border-gray-800
          bg-gray-50 dark:bg-gray-800/50">
          <div className="flex items-center gap-2">
            <MatIcon name="content_copy" className="text-[14px] text-gray-500" />
            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">주간업무 복사용 텍스트</span>
          </div>
          <button
            onClick={copy}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium
              transition-colors cursor-pointer
              ${copied
                ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                : 'bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400 hover:bg-teal-200 dark:hover:bg-teal-900/50'
              }`}
          >
            <MatIcon name={copied ? 'check' : 'content_copy'} className="text-[13px]" />
            {copied ? '복사됨' : '복사'}
          </button>
        </div>
        <pre className="px-4 py-3 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed font-mono">
          {data.copy_text}
        </pre>
      </div>

      {/* 프로젝트별 상세 */}
      <div className="space-y-3">
        {Object.entries(data.groups).map(([project, tasks]) => {
          const done = tasks.filter(t => t.progress >= 100).length
          const avg = Math.round(tasks.reduce((s, t) => s + t.progress, 0) / tasks.length)
          return (
            <div key={project} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 flex items-center gap-2">
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{project}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500">
                  {tasks.length}건 · 완료 {done}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden ml-2">
                  <div className={`h-full rounded-full ${progressColor(avg)}`} style={{ width: `${avg}%` }} />
                </div>
                <span className="text-[10px] text-gray-400 tabular-nums">{avg}%</span>
              </div>
              <ul className="divide-y divide-gray-50 dark:divide-gray-800">
                {tasks.map(t => (
                  <li key={t.id} className="px-4 py-2 flex items-center gap-3">
                    <span className="text-[10px] text-gray-400 tabular-nums w-16 shrink-0">{t.date.slice(5)}</span>
                    <span className="flex-1 text-xs text-gray-700 dark:text-gray-300">{t.task_name}</span>
                    <span className={`text-[10px] font-medium shrink-0 ${
                      t.progress >= 100 ? 'text-green-600 dark:text-green-400' :
                      t.progress > 0 ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400'
                    }`}>
                      {t.progress >= 100 ? '완료' : t.progress > 0 ? `${t.progress}%` : '-'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>

      {data.overdue.length > 0 && (
        <div className="bg-orange-50 dark:bg-orange-900/10 rounded-xl border border-orange-200 dark:border-orange-800/30 p-4">
          <p className="text-xs font-semibold text-orange-700 dark:text-orange-400 mb-2">
            마감 초과 작업 ({data.overdue.length}건)
          </p>
          <ul className="space-y-1">
            {data.overdue.map(t => (
              <li key={t.id} className="text-xs text-orange-600 dark:text-orange-400">
                {t.project} · {t.task_name} ({t.due_date} 마감)
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function WorkReport({ onBack }: { onBack?: () => void } = {}) {
  const today = toLocalISODate(new Date())
  const [viewDate, setViewDate] = useState(today)
  const [tab, setTab] = useState<'daily' | 'weekly'>('daily')
  const [weekStart, setWeekStart] = useState(() => getWeekStart(today))
  const qc = useQueryClient()

  const { data: tasks = [], isLoading } = useQuery<WRTask[]>({
    queryKey: ['wr-daily', viewDate],
    queryFn: async () => {
      const res = await fetch(`/api/workreport/tasks/daily?work_date=${viewDate}`)
      if (!res.ok) return []
      return res.json()
    },
    refetchInterval: 10000,
  })

  // 최근 기록 — 오늘 데이터 없을 때 안내용
  const { data: recentTasks = [] } = useQuery<WRTask[]>({
    queryKey: ['wr-recent'],
    queryFn: async () => {
      const res = await fetch('/api/workreport/tasks/recent?limit=1')
      if (!res.ok) return []
      return res.json()
    },
  })

  // 오늘 로드 완료 후 데이터 없으면 최근 데이터 있는 날짜로 자동 이동
  useEffect(() => {
    if (!isLoading && tasks.length === 0 && viewDate === today && recentTasks.length > 0) {
      const lastDate = recentTasks[0].date
      if (lastDate && lastDate !== today) setViewDate(lastDate)
    }
  }, [isLoading, tasks.length, viewDate, today, recentTasks])

  const { data: dash } = useQuery<Dashboard>({
    queryKey: ['wr-dashboard'],
    queryFn: async () => {
      const res = await fetch('/api/workreport/dashboard')
      if (!res.ok) throw new Error()
      return res.json()
    },
    refetchInterval: 30000,
  })

  const updateProgress = useMutation({
    mutationFn: async ({ id, progress }: { id: number; progress: number }) => {
      const res = await fetch(`/api/workreport/tasks/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ progress }),
      })
      if (!res.ok) throw new Error()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['wr-daily', viewDate] })
      qc.invalidateQueries({ queryKey: ['wr-dashboard'] })
    },
  })

  const deleteTask = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`/api/workreport/tasks/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['wr-daily', viewDate] })
      qc.invalidateQueries({ queryKey: ['wr-dashboard'] })
    },
  })

  function prevDay() {
    const d = new Date(viewDate + 'T00:00:00')
    d.setDate(d.getDate() - 1)
    setViewDate(toLocalISODate(d))
  }
  function nextDay() {
    const d = new Date(viewDate + 'T00:00:00')
    d.setDate(d.getDate() + 1)
    const next = toLocalISODate(d)
    if (next <= today) setViewDate(next)
  }
  function prevWeek() {
    const d = new Date(weekStart + 'T00:00:00')
    d.setDate(d.getDate() - 7)
    setWeekStart(toLocalISODate(d))
  }
  function nextWeek() {
    const d = new Date(weekStart + 'T00:00:00')
    d.setDate(d.getDate() + 7)
    const next = toLocalISODate(d)
    if (next <= today) setWeekStart(next)
  }

  const isToday = viewDate === today
  const isCurrentWeek = weekStart === getWeekStart(today)
  const avgProgress = tasks.length
    ? Math.round(tasks.reduce((s, t) => s + t.progress, 0) / tasks.length)
    : 0

  const weekEndDt = new Date(weekStart + 'T00:00:00')
  weekEndDt.setDate(weekEndDt.getDate() + 6)
  const weekEnd = weekEndDt

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50 dark:bg-gray-950">
      {/* 헤더 */}
      <div className="px-4 md:px-5 h-[60px] shrink-0 flex items-center gap-2
        border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        {onBack && (
          <button
            onClick={onBack}
            className="md:hidden flex items-center justify-center w-8 h-8 -ml-1
              rounded-lg text-slate-500 dark:text-slate-400
              hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
          >
            <MatIcon name="arrow_back_ios_new" className="text-[16px]" />
          </button>
        )}
        <div className="flex items-center gap-3 flex-1">
          <div className="w-8 h-8 rounded-xl bg-teal-100 dark:bg-teal-900/30 flex items-center justify-center">
            <MatIcon name="edit_note" className="text-[18px] text-teal-600 dark:text-teal-400" />
          </div>
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">업무일지</h2>
        </div>
        {/* 탭 */}
        <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-0.5">
          {(['daily', 'weekly'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer
                ${tab === t
                  ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
            >
              {t === 'daily' ? '일별' : '주간'}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-5 space-y-4 max-w-2xl w-full mx-auto">

        {/* 주간 탭 */}
        {tab === 'weekly' && (
          <>
            <div className="flex items-center justify-between bg-white dark:bg-gray-900 rounded-xl
              border border-gray-200 dark:border-gray-800 px-4 py-2.5">
              <button onClick={prevWeek}
                className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors">
                <MatIcon name="chevron_left" className="text-[20px] text-gray-500" />
              </button>
              <div className="text-center">
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {new Date(weekStart + 'T00:00:00').toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })}
                  {' ~ '}
                  {weekEnd.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })}
                </p>
                {isCurrentWeek && (
                  <span className="text-[10px] text-teal-600 dark:text-teal-400 font-medium">이번 주</span>
                )}
              </div>
              <button onClick={nextWeek}
                disabled={isCurrentWeek}
                className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800
                  cursor-pointer transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
                <MatIcon name="chevron_right" className="text-[20px] text-gray-500" />
              </button>
            </div>
            <WeeklySummaryView weekStart={weekStart} />
          </>
        )}

        {/* 일별 탭 */}
        {tab === 'daily' && <>

        {/* 오늘 요약 카드 */}
        {dash && isToday && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: '오늘 작업', value: dash.today_count, icon: 'task_alt', color: 'teal' },
              { label: '평균 진행도', value: `${dash.avg_progress_today}%`, icon: 'trending_up', color: 'blue' },
              { label: '마감 초과', value: dash.overdue_count, icon: 'warning', color: 'orange' },
              { label: '활성 프로젝트', value: dash.active_projects, icon: 'folder_open', color: 'violet' },
            ].map(({ label, value, icon, color }) => (
              <div key={label} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-3">
                <div className={`w-7 h-7 rounded-lg flex items-center justify-center mb-2
                  bg-${color}-100 dark:bg-${color}-900/30`}>
                  <MatIcon name={icon} className={`text-[15px] text-${color}-600 dark:text-${color}-400`} />
                </div>
                <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{value}</p>
                <p className="text-[11px] text-gray-500">{label}</p>
              </div>
            ))}
          </div>
        )}

        {/* 날짜 네비게이션 */}
        <div className="flex items-center justify-between bg-white dark:bg-gray-900 rounded-xl
          border border-gray-200 dark:border-gray-800 px-4 py-2.5">
          <button onClick={prevDay}
            className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors">
            <MatIcon name="chevron_left" className="text-[20px] text-gray-500" />
          </button>
          <div className="text-center">
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {new Date(viewDate + 'T00:00:00').toLocaleDateString('ko-KR', {
                month: 'long', day: 'numeric', weekday: 'short',
              })}
            </p>
            {isToday && (
              <span className="text-[10px] text-teal-600 dark:text-teal-400 font-medium">오늘</span>
            )}
          </div>
          <button onClick={nextDay}
            disabled={isToday}
            className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
            <MatIcon name="chevron_right" className="text-[20px] text-gray-500" />
          </button>
        </div>

        {/* 진행도 요약 바 */}
        {tasks.length > 0 && (
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-3">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-gray-500">전체 진행도</span>
              <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">{avgProgress}%</span>
            </div>
            <div className="h-2 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${progressColor(avgProgress)}`}
                style={{ width: `${avgProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* 작업 목록 */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <MatIcon name="hourglass_empty" className="text-[40px]" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="w-14 h-14 rounded-2xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-3">
              <MatIcon name="edit_note" className="text-[28px] text-gray-400" />
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {isToday ? '오늘 기록된 작업이 없습니다' : '이 날 기록된 작업이 없습니다'}
            </p>
            {isToday && (
              <p className="text-xs text-gray-400 mt-1">채팅에서 "X 작업 시작" 이라고 말하면 자동 등록됩니다</p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                onProgressChange={(id, progress) => updateProgress.mutate({ id, progress })}
                onDelete={(id) => deleteTask.mutate(id)}
              />
            ))}
          </div>
        )}

        {/* 직접 추가 폼 */}
        {isToday && (
          <AddTaskForm onAdded={() => qc.invalidateQueries({ queryKey: ['wr-daily', viewDate] })} />
        )}

        </>}
      </div>
    </div>
  )
}
