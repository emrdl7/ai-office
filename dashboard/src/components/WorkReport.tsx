// 업무일지 — 일별 작업 기록 / 등록 / 진행도 관리 + 주간 취합
import { useMemo, useRef, useState } from 'react'
import { useQueries, useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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
  status: string
  started_at?: string | null
  completed_at?: string | null
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

interface MonthlyDay {
  date: string
  task_count: number
  avg_progress: number
  done_count: number
  overdue_count: number
  projects: string[]
  tasks: CalendarTask[]
}

interface PublicHoliday {
  date: string
  name: string
  kind?: string
  sequence?: string
}

interface DayOff {
  date: string
  name: string
  kind: string
  created_at?: string
}

const DAY_OFF_OPTIONS = [
  { name: '휴가', kind: 'vacation' },
  { name: '오전반차', kind: 'half_day_am' },
  { name: '오후반차', kind: 'half_day_pm' },
]

function dayOffLabel(dayOff: DayOff): string {
  if (dayOff.kind === 'half_day_am') return '오전반차'
  if (dayOff.kind === 'half_day_pm') return '오후반차'
  if (dayOff.kind === 'half_day') return '반차'
  return dayOff.name || '휴가'
}

interface MonthlyCalendar {
  month: string
  period: { start: string; end: string }
  total: number
  days: MonthlyDay[]
  tasks?: CalendarTask[]
  holidays?: PublicHoliday[]
  days_off?: DayOff[]
}

type CalendarTask = Pick<
  WRTask,
  'id' | 'date' | 'time' | 'project' | 'task_name' | 'progress' | 'due_date' | 'status' | 'started_at' | 'completed_at'
>

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
    <div className="rounded-2xl border border-white/70 bg-white/82 p-4 shadow-sm shadow-slate-900/5 backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-md hover:border-teal-300/70 dark:border-slate-700/70 dark:bg-slate-900/72">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {task.project && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full
                bg-teal-100/90 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300">
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
      className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-2xl border border-dashed
        border-teal-300/60 bg-white/54 dark:bg-slate-950/30 text-slate-500 dark:text-slate-400 hover:text-teal-700 dark:hover:text-teal-300
        hover:border-teal-400 dark:hover:border-teal-600 transition-colors cursor-pointer text-sm backdrop-blur"
    >
      <MatIcon name="add" className="text-[16px]" />
      작업 직접 추가
    </button>
  )

  return (
    <div className="rounded-2xl border border-teal-300/70 bg-white/88 p-4 shadow-lg shadow-teal-500/10 backdrop-blur dark:border-teal-700/70 dark:bg-slate-900/82 space-y-3">
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

function shiftMonth(month: string, delta: number): string {
  const d = new Date(month + '-01T00:00:00')
  d.setMonth(d.getMonth() + delta)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function monthLabel(month: string): string {
  return new Date(month + '-01T00:00:00').toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
  })
}

function buildCalendarCells(month: string) {
  const first = new Date(month + '-01T00:00:00')
  const next = new Date(first)
  next.setMonth(next.getMonth() + 1)
  const totalDays = Math.round((next.getTime() - first.getTime()) / 86400000)
  return Array.from({ length: totalDays }, (_, i) => {
    const d = new Date(first)
    d.setDate(first.getDate() + i)
    return {
      date: toLocalISODate(d),
      day: d.getDate(),
      dayOfWeek: d.getDay(),
    }
  })
}

function chunkWeeks<T extends { dayOfWeek: number }>(items: T[]): T[][] {
  const weeks: T[][] = []
  let current: T[] = []
  for (const item of items) {
    if (current.length > 0 && item.dayOfWeek === 0) {
      weeks.push(current)
      current = []
    }
    current.push(item)
  }
  if (current.length > 0) weeks.push(current)
  return weeks
}

function buildMonthRange(anchorMonth: string, before: number, after: number): string[] {
  return Array.from({ length: before + after + 1 }, (_, i) => shiftMonth(anchorMonth, i - before))
}

function taskStartDate(task: CalendarTask): string {
  return task.started_at || task.date
}

function taskEndDate(task: CalendarTask): string {
  return task.completed_at || task.due_date || task.date
}

const RIBBON_TONES = [
  'bg-blue-600 text-white dark:bg-blue-400 dark:text-slate-950',
  'bg-emerald-600 text-white dark:bg-emerald-400 dark:text-slate-950',
  'bg-amber-500 text-white dark:bg-amber-300 dark:text-slate-950',
  'bg-rose-500 text-white dark:bg-rose-400 dark:text-slate-950',
  'bg-violet-600 text-white dark:bg-violet-400 dark:text-slate-950',
  'bg-cyan-600 text-white dark:bg-cyan-300 dark:text-slate-950',
  'bg-orange-600 text-white dark:bg-orange-400 dark:text-slate-950',
  'bg-teal-600 text-white dark:bg-teal-300 dark:text-slate-950',
  'bg-fuchsia-600 text-white dark:bg-fuchsia-400 dark:text-slate-950',
  'bg-lime-600 text-white dark:bg-lime-300 dark:text-slate-950',
]

function stableColorIndex(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0
  }
  return hash % RIBBON_TONES.length
}

function ribbonTone(task: CalendarTask): string {
  if (task.due_date && task.due_date < toLocalISODate(new Date()) && task.progress < 100) {
    return 'bg-red-600 text-white dark:bg-red-400 dark:text-slate-950'
  }
  return RIBBON_TONES[stableColorIndex(task.project || task.task_name)]
}

async function fetchMonthlyCalendar(month: string): Promise<MonthlyCalendar> {
  const res = await fetch(`/api/workreport/tasks/monthly?month=${month}`)
  const contentType = res.headers.get('content-type') ?? ''
  if (res.ok && contentType.includes('application/json')) {
    return res.json()
  }

  const recentRes = await fetch('/api/workreport/tasks/recent?limit=500')
  if (!recentRes.ok) throw new Error('업무일지 월간 데이터를 불러오지 못했습니다')
  const tasks = (await recentRes.json() as WRTask[]).filter((task) => {
    const start = taskStartDate(task)
    const end = taskEndDate(task)
    return start.slice(0, 7) <= month && end.slice(0, 7) >= month
  })
  const byDate = new Map<string, WRTask[]>()
  for (const task of tasks) {
    byDate.set(task.date, [...(byDate.get(task.date) ?? []), task])
  }
  const days = Array.from(byDate.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([date, dayTasks]) => {
    const projects = Array.from(new Set(dayTasks.map((task) => task.project).filter(Boolean)))
    const avg = dayTasks.reduce((sum, task) => sum + task.progress, 0) / dayTasks.length
    return {
      date,
      task_count: dayTasks.length,
      avg_progress: Math.round(avg * 10) / 10,
      done_count: dayTasks.filter((task) => task.progress >= 100).length,
      overdue_count: dayTasks.filter((task) => task.due_date && task.due_date < date && task.progress < 100).length,
      projects,
      tasks: dayTasks
        .sort((a, b) => `${a.time}-${a.id}`.localeCompare(`${b.time}-${b.id}`)),
    }
  })
  return {
    month,
    period: { start: `${month}-01`, end: `${month}-31` },
    total: tasks.length,
    days,
    tasks,
    holidays: [],
    days_off: [],
  }
}

function WorkCalendar({
  month,
  today,
  onMonthChange,
  onSelectDate,
}: {
  month: string
  today: string
  onMonthChange: (month: string) => void
  onSelectDate: (date: string) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [months, setMonths] = useState(() => buildMonthRange(month, 0, 6))
  const [visibleMonth, setVisibleMonth] = useState(month)
  const ribbonTop = 40
  const ribbonRowHeight = 24
  const ribbonRowGap = 6
  const ribbonBottomPadding = 14
  const monthQueries = useQueries({
    queries: months.map((m) => ({
      queryKey: ['wr-monthly', m],
      queryFn: () => fetchMonthlyCalendar(m),
      refetchInterval: 30000,
    })),
  })
  const dataByMonth = useMemo(() => {
    const map = new Map<string, MonthlyCalendar>()
    monthQueries.forEach((query, i) => {
      if (query.data) map.set(months[i], query.data)
    })
    return map
  }, [monthQueries, months])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    const probeY = el.getBoundingClientRect().top + 72
    const visibleDate = Array.from(el.querySelectorAll<HTMLElement>('[data-calendar-date]'))
      .find((node) => node.getBoundingClientRect().bottom >= probeY)
      ?.dataset.calendarDate
    if (visibleDate) {
      const nextVisibleMonth = visibleDate.slice(0, 7)
      if (nextVisibleMonth !== visibleMonth) setVisibleMonth(nextVisibleMonth)
    }
    if (el.scrollTop < 280) {
      const previousHeight = el.scrollHeight
      setMonths((prev) => {
        const first = prev[0]
        const additions = Array.from({ length: 3 }, (_, i) => shiftMonth(first, i - 3))
        return Array.from(new Set([...additions, ...prev])).sort()
      })
      requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop += scrollRef.current.scrollHeight - previousHeight
      })
    }
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 420) {
      setMonths((prev) => {
        const last = prev[prev.length - 1]
        const additions = Array.from({ length: 3 }, (_, i) => shiftMonth(last, i + 1))
        return Array.from(new Set([...prev, ...additions])).sort()
      })
    }
  }

  function renderCalendarRows() {
    const cells = months.flatMap((m) => buildCalendarCells(m))
    const weeks = chunkWeeks(cells)
    const byDate = new Map<string, MonthlyDay>()
    const holidaysByDate = new Map<string, PublicHoliday[]>()
    const daysOffByDate = new Map<string, DayOff[]>()
    for (const data of dataByMonth.values()) {
      for (const day of data.days ?? []) byDate.set(day.date, day)
      for (const holiday of data.holidays ?? []) {
        holidaysByDate.set(holiday.date, [...(holidaysByDate.get(holiday.date) ?? []), holiday])
      }
      for (const dayOff of data.days_off ?? []) {
        daysOffByDate.set(dayOff.date, [...(daysOffByDate.get(dayOff.date) ?? []), dayOff])
      }
    }
    const allTasks = Array.from(new Map(
      Array.from(dataByMonth.values()).flatMap((data) => {
        const tasks = data.tasks ?? data.days.flatMap((day) => day.tasks ?? [])
        return tasks.map((task) => [task.id, task] as const)
      }),
    ).values())

    return (
      <>
        {weeks.map((week, weekIndex) => {
          const weekStart = week[0].date
          const weekEnd = week[week.length - 1].date
          const weekTasks = allTasks
            .filter((task) => taskStartDate(task) <= weekEnd && taskEndDate(task) >= weekStart)
            .sort((a, b) => {
              const startCompare = taskStartDate(a).localeCompare(taskStartDate(b))
              if (startCompare !== 0) return startCompare
              return `${a.time}-${a.id}`.localeCompare(`${b.time}-${b.id}`)
            })
          const lanes: boolean[][] = []
          const weekRibbons = weekTasks.map((task) => {
            const segmentStart = taskStartDate(task) > weekStart ? taskStartDate(task) : weekStart
            const segmentEnd = taskEndDate(task) < weekEnd ? taskEndDate(task) : weekEnd
            const startCol = new Date(segmentStart + 'T00:00:00').getDay() + 1
            const endCol = new Date(segmentEnd + 'T00:00:00').getDay() + 1
            let laneIndex = lanes.findIndex((lane) => {
              for (let col = startCol; col <= endCol; col += 1) {
                if (lane[col]) return false
              }
              return true
            })
            if (laneIndex === -1) {
              laneIndex = lanes.length
              lanes.push([])
            }
            for (let col = startCol; col <= endCol; col += 1) {
              lanes[laneIndex][col] = true
            }
            return {
              task,
              startCol,
              endCol,
              row: laneIndex + 1,
              startsBefore: taskStartDate(task) < segmentStart,
              endsAfter: taskEndDate(task) > segmentEnd,
            }
          })
          const weekHeight = Math.max(
            126,
            ribbonTop + lanes.length * ribbonRowHeight + Math.max(0, lanes.length - 1) * ribbonRowGap + ribbonBottomPadding,
          )
          return (
            <div
              key={`${weekStart}-${weekEnd}`}
              className="relative grid grid-cols-7 overflow-hidden border-t border-slate-300/80 first:border-t-0 dark:border-slate-700/80"
              style={{ minHeight: weekHeight }}
            >
              {week.map((cell) => {
                const day = byDate.get(cell.date)
                const isToday = cell.date === today
                const isFirstDay = cell.day === 1
                const cellMonth = cell.date.slice(0, 7)
                const monthData = dataByMonth.get(cellMonth)
                const isMonthLoading = monthQueries[months.indexOf(cellMonth)]?.isLoading
                const holidays = holidaysByDate.get(cell.date) ?? []
                const daysOff = daysOffByDate.get(cell.date) ?? []
                const isHoliday = holidays.length > 0
                const isSunday = cell.dayOfWeek === 0
                const isSaturday = cell.dayOfWeek === 6
                const isDayOff = daysOff.length > 0
                const dayLabels = [
                  ...daysOff.map(dayOffLabel),
                  ...holidays.map((holiday) => holiday.name),
                ]
                return (
                  <button
                    key={cell.date}
                    data-calendar-date={cell.date}
                    onClick={() => {
                      onMonthChange(cellMonth)
                      onSelectDate(cell.date)
                    }}
                    className={`relative h-full min-h-[126px] border-l border-slate-300/80 p-2 text-left transition-colors first:border-l-0 hover:bg-teal-50/70 dark:border-slate-700/80 dark:hover:bg-teal-950/20
                      ${isDayOff ? 'bg-amber-50/78 dark:bg-amber-950/16' : isHoliday || isSunday ? 'bg-rose-50/68 dark:bg-rose-950/10' : isSaturday ? 'bg-sky-50/68 dark:bg-sky-950/10' : 'bg-white/62 dark:bg-slate-950/24'}
                      ${isToday ? 'shadow-[inset_0_0_0_2px_rgba(34,211,238,0.65)]' : ''}`}
                    style={{ gridColumn: cell.dayOfWeek + 1 }}
                  >
                    {isFirstDay && (
                      <span className="absolute left-2 top-1.5 rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-black text-white shadow-sm dark:bg-cyan-300 dark:text-slate-950">
                        {monthLabel(cellMonth)}
                        {isMonthLoading ? '' : ` · ${monthData?.total ?? 0}`}
                      </span>
                    )}
                    <span className={`absolute right-2 top-1.5 text-base font-black tabular-nums ${isDayOff ? 'text-amber-700 dark:text-amber-200' : isHoliday || isSunday ? 'text-rose-600 dark:text-rose-300' : isSaturday ? 'text-sky-600 dark:text-sky-300' : isToday ? 'text-teal-700 dark:text-cyan-200' : 'text-slate-800 dark:text-slate-100'}`}>
                      {cell.day}
                    </span>
                    {dayLabels.length > 0 && (
                      <span className={`absolute left-2 max-w-[calc(100%-1rem)] truncate text-[9px] font-semibold ${isDayOff ? 'text-amber-700/85 dark:text-amber-200/85' : 'text-rose-600/85 dark:text-rose-300/85'} ${isFirstDay ? 'top-7' : 'top-2'}`}>
                        {dayLabels.join(', ')}
                      </span>
                    )}
                    {day && (
                      <span className={`absolute left-2 text-[10px] font-black text-slate-500 dark:text-slate-300 ${dayLabels.length > 0 && isFirstDay ? 'top-12' : dayLabels.length > 0 || isFirstDay ? 'top-7' : 'top-2'}`}>
                        {day.task_count}
                      </span>
                    )}
                  </button>
                )
              })}

              <div
                className="pointer-events-none absolute inset-x-0 grid grid-cols-7 gap-y-1.5 overflow-hidden px-1.5"
                style={{ top: ribbonTop, gridAutoRows: ribbonRowHeight }}
              >
                {weekRibbons.map(({ task, startCol, endCol, row, startsBefore, endsAfter }) => {
                  return (
                    <div
                      key={`${task.id}-${weekIndex}`}
                      className={`min-w-0 self-start px-2.5 py-1 text-[10px] font-black leading-none shadow-sm ring-1 ring-white/20 ${ribbonTone(task)} ${startsBefore ? 'rounded-l-none' : 'rounded-l-full'} ${endsAfter ? 'rounded-r-none' : 'rounded-r-full'}`}
                      style={{ gridColumn: `${startCol} / span ${Math.max(1, endCol - startCol + 1)}`, gridRow: row }}
                      title={`${taskStartDate(task)}~${taskEndDate(task)} ${task.project ? `[${task.project}] ` : ''}${task.task_name}`}
                    >
                      <span className="block truncate">{task.task_name}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </>
    )
  }

  return (
    <div className="rounded-[2rem] border border-white/70 bg-white/84 p-5 shadow-xl shadow-slate-900/8 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-3xl font-black tracking-[-0.04em] text-slate-950 dark:text-white">{monthLabel(visibleMonth)}</p>
          <p className="mt-0.5 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            {dataByMonth.get(visibleMonth)?.total ?? 0}개 작업 기록
          </p>
        </div>
        <button
          onClick={() => {
            onMonthChange(today.slice(0, 7))
            setVisibleMonth(today.slice(0, 7))
            onSelectDate(today)
          }}
          className="rounded-2xl bg-slate-950 px-3 py-2 text-xs font-black text-white shadow-sm transition-colors hover:bg-teal-700 dark:bg-cyan-300 dark:text-slate-950 dark:hover:bg-cyan-200"
        >
          오늘
        </button>
      </div>

      <div className="sticky top-0 z-10 grid grid-cols-7 rounded-t-2xl border border-x-0 border-slate-300/80 bg-white/82 text-center shadow-sm backdrop-blur-xl dark:border-slate-700/80 dark:bg-slate-950/82">
        {['일', '월', '화', '수', '목', '금', '토'].map((d) => (
          <div key={d} className="py-2.5 text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">{d}</div>
        ))}
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="max-h-[calc(100vh-214px)] min-h-[640px] overflow-y-auto pr-2"
      >
        <div className="overflow-hidden rounded-b-2xl border-b border-slate-300/80 bg-white/38 dark:border-slate-700/80 dark:bg-slate-950/20">
          {renderCalendarRows()}
        </div>
      </div>
    </div>
  )
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
      <div className="overflow-hidden rounded-2xl border border-white/70 bg-white/82 shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-100/80 dark:border-slate-800
          bg-white/54 dark:bg-slate-800/50">
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
            <div key={project} className="overflow-hidden rounded-2xl border border-white/70 bg-white/82 shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
              <div className="px-4 py-2.5 border-b border-slate-100/80 dark:border-slate-800 flex items-center gap-2">
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
        <div className="rounded-2xl border border-orange-200/80 bg-orange-50/82 p-4 shadow-sm shadow-orange-500/10 backdrop-blur dark:border-orange-800/30 dark:bg-orange-900/10">
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
  const [calendarMonth, setCalendarMonth] = useState(today.slice(0, 7))
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


  const { data: dash } = useQuery<Dashboard>({
    queryKey: ['wr-dashboard'],
    queryFn: async () => {
      const res = await fetch('/api/workreport/dashboard')
      if (!res.ok) throw new Error()
      return res.json()
    },
    refetchInterval: 30000,
  })

  const { data: daysOff = [] } = useQuery<DayOff[]>({
    queryKey: ['wr-days-off', viewDate.slice(0, 7)],
    queryFn: async () => {
      const res = await fetch(`/api/workreport/days-off?month=${viewDate.slice(0, 7)}`)
      if (!res.ok) return []
      return res.json()
    },
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

  const registerDayOff = useMutation({
    mutationFn: async ({ name, kind }: { name: string; kind: string }) => {
      const res = await fetch('/api/workreport/days-off', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: viewDate, name, kind }),
      })
      if (!res.ok) throw new Error()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['wr-days-off', viewDate.slice(0, 7)] })
      qc.invalidateQueries({ queryKey: ['wr-monthly'] })
    },
  })

  const deleteDayOff = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/workreport/days-off/${viewDate}`, { method: 'DELETE' })
      if (!res.ok && res.status !== 404) throw new Error()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['wr-days-off', viewDate.slice(0, 7)] })
      qc.invalidateQueries({ queryKey: ['wr-monthly'] })
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
  const selectedDayOff = daysOff.find((item) => item.date === viewDate)
  const avgProgress = tasks.length
    ? Math.round(tasks.reduce((s, t) => s + t.progress, 0) / tasks.length)
    : 0

  const weekEndDt = new Date(weekStart + 'T00:00:00')
  weekEndDt.setDate(weekEndDt.getDate() + 6)
  const weekEnd = weekEndDt

  const statCards = [
    { label: '오늘 작업', value: dash?.today_count ?? 0, icon: 'task_alt', cls: 'bg-teal-100 dark:bg-teal-900/30 text-teal-600 dark:text-teal-400' },
    { label: '평균 진행도', value: `${dash?.avg_progress_today ?? 0}%`, icon: 'trending_up', cls: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' },
    { label: '마감 초과', value: dash?.overdue_count ?? 0, icon: 'warning', cls: 'bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400' },
    { label: '활성 프로젝트', value: dash?.active_projects ?? 0, icon: 'folder_open', cls: 'bg-violet-100 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400' },
  ]
  const latestTaskMonth = dash?.recent_tasks?.[0]?.date?.slice(0, 7)
  const calendarAnchorMonth = calendarMonth === today.slice(0, 7) && dash?.today_count === 0 && latestTaskMonth
    ? latestTaskMonth
    : calendarMonth

  return (
    <div className="chat-canvas flex-1 flex flex-col min-h-0 bg-transparent">
      {/* 헤더 */}
      <div className="px-4 md:px-5 h-[64px] shrink-0 flex items-center gap-2
        border-b border-slate-200/70 dark:border-slate-800/70 glass-panel rounded-none border-x-0 border-t-0">
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
          <div className="w-9 h-9 rounded-2xl bg-slate-950 dark:bg-cyan-300 flex items-center justify-center shadow-sm">
            <MatIcon name="edit_note" className="text-[18px] text-white dark:text-slate-950" />
          </div>
          <div>
            <h2 className="text-sm font-black tracking-tight text-slate-900 dark:text-white">업무일지</h2>
            <p className="hidden sm:block text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Calendar log</p>
          </div>
        </div>
        {/* 탭 */}
        <div className="flex items-center gap-1 rounded-2xl border border-white/70 bg-white/60 p-1 shadow-sm backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/60">
          {(['daily', 'weekly'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-colors cursor-pointer
                ${tab === t
                  ? 'bg-slate-950 text-white shadow-sm dark:bg-cyan-300 dark:text-slate-950'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
            >
              {t === 'daily' ? '일별' : '주간'}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-5 space-y-4 w-full">

        {/* 주간 탭 */}
        {tab === 'weekly' && (
          <>
            <div className="flex items-center justify-between rounded-2xl border border-white/70 bg-white/82 px-4 py-2.5 shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
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
        {tab === 'daily' && (
          <div className="grid gap-5 lg:grid-cols-[minmax(620px,1fr)_380px] xl:grid-cols-[minmax(760px,1fr)_390px]">
            <aside className="hidden lg:block">
              <div className="sticky top-0">
                <WorkCalendar
                  key={calendarAnchorMonth}
                  month={calendarAnchorMonth}
                  today={today}
                  onMonthChange={setCalendarMonth}
                  onSelectDate={(date) => {
                    setViewDate(date)
                    setCalendarMonth(date.slice(0, 7))
                  }}
                />
              </div>
            </aside>

            <section className="space-y-4 min-w-0">

        {/* 오늘 요약 카드 */}
        {dash && isToday && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {statCards.map(({ label, value, icon, cls }) => (
              <div key={label} className="rounded-2xl border border-white/70 bg-white/78 p-3 shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-950/42">
                <div className={`w-7 h-7 rounded-lg flex items-center justify-center mb-2 ${cls}`}>
                  <MatIcon name={icon} className="text-[15px]" />
                </div>
                <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{value}</p>
                <p className="text-[11px] text-gray-500">{label}</p>
              </div>
            ))}
          </div>
        )}

        {/* 날짜 네비게이션 */}
        <div className="flex items-center justify-between rounded-2xl border border-white/70 bg-white/82 px-4 py-2.5 shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
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

        <div className={`flex items-center justify-between gap-3 rounded-2xl border px-4 py-3 shadow-sm backdrop-blur ${
          selectedDayOff
            ? 'border-amber-200/80 bg-amber-50/84 text-amber-900 shadow-amber-500/10 dark:border-amber-700/40 dark:bg-amber-950/20 dark:text-amber-100'
            : 'border-white/70 bg-white/76 text-slate-700 shadow-slate-900/5 dark:border-slate-700/70 dark:bg-slate-950/38 dark:text-slate-300'
        }`}>
          <div className="min-w-0">
            <p className="text-xs font-black">{selectedDayOff ? dayOffLabel(selectedDayOff) : '이 날짜를 휴무로 표시'}</p>
            <p className="mt-0.5 text-[11px] opacity-70">
              {selectedDayOff ? '업무 캘린더에서 직접 등록 휴무로 표시됩니다' : '휴가, 오전반차, 오후반차처럼 공휴일이 아닌 휴무를 등록합니다'}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {selectedDayOff ? (
              <button
                onClick={() => deleteDayOff.mutate()}
                disabled={deleteDayOff.isPending}
                className="rounded-xl bg-amber-200 px-3 py-2 text-xs font-bold text-amber-950 transition-colors hover:bg-amber-300 disabled:opacity-50 dark:bg-amber-300 dark:hover:bg-amber-200"
              >
                휴무 해제
              </button>
            ) : (
              DAY_OFF_OPTIONS.map((option) => (
                <button
                  key={option.kind}
                  onClick={() => registerDayOff.mutate(option)}
                  disabled={registerDayOff.isPending}
                  className="rounded-xl bg-slate-950 px-3 py-2 text-xs font-bold text-white transition-colors hover:bg-amber-600 disabled:opacity-50 dark:bg-amber-300 dark:text-slate-950 dark:hover:bg-amber-200"
                >
                  {option.name}
                </button>
              ))
            )}
          </div>
        </div>

        {/* 진행도 요약 바 */}
        {tasks.length > 0 && (
          <div className="rounded-2xl border border-white/70 bg-white/82 p-3 shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
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
          <div className="rounded-[2rem] border border-white/70 bg-white/62 px-5 py-12 text-center shadow-sm shadow-slate-900/5 backdrop-blur dark:border-slate-700/70 dark:bg-slate-950/36">
            <div className="mx-auto w-14 h-14 rounded-3xl bg-slate-950 dark:bg-cyan-300 flex items-center justify-center mb-3 shadow-sm">
              <MatIcon name="edit_note" className="text-[28px] text-white dark:text-slate-950" />
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

            </section>
          </div>
        )}
      </div>
    </div>
  )
}
