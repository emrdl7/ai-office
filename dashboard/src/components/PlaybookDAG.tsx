// Playbook DAG 시각화 — 레벨별 토폴로지 레이아웃을 CSS 그리드로 렌더
import { useMemo } from 'react'

type PlaybookStep = {
  id: string
  spec_id: string
  title?: string
  after?: string[]
}

const SPEC_TONE: Record<string, string> = {
  research:         'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700/60',
  planning:         'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 border-indigo-300 dark:border-indigo-700/60',
  design_direction: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300 border-pink-300 dark:border-pink-700/60',
  review:           'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 border-yellow-300 dark:border-yellow-700/60',
  publishing:       'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 border-orange-300 dark:border-orange-700/60',
  coding:           'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700/60',
}

function levelize(steps: PlaybookStep[]): PlaybookStep[][] {
  const byId = new Map(steps.map(s => [s.id, s]))
  const level = new Map<string, number>()
  const resolve = (s: PlaybookStep): number => {
    if (level.has(s.id)) return level.get(s.id)!
    const deps = (s.after && s.after.length > 0)
      ? s.after
      : steps.slice(0, steps.indexOf(s)).map(x => x.id)
    const lv = deps.length === 0 ? 0 : Math.max(...deps.map(d => {
      const ds = byId.get(d); return ds ? resolve(ds) + 1 : 0
    }))
    level.set(s.id, lv)
    return lv
  }
  steps.forEach(resolve)
  const out: PlaybookStep[][] = []
  for (const s of steps) {
    const lv = level.get(s.id) ?? 0
    if (!out[lv]) out[lv] = []
    out[lv].push(s)
  }
  return out
}

export function PlaybookDAG({ steps }: { steps: PlaybookStep[] }) {
  const levels = useMemo(() => levelize(steps), [steps])
  if (!steps || steps.length === 0) return null

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/60 p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400">실행 DAG</span>
        <span className="text-[10px] text-gray-400">· 레벨별 병렬</span>
      </div>
      <div className="flex items-stretch gap-2 overflow-x-auto">
        {levels.map((lvSteps, li) => (
          <div key={li} className="flex flex-col gap-1.5 min-w-[120px]">
            <div className="text-[9px] text-gray-400 font-mono px-1">lv{li}</div>
            {lvSteps.map(s => {
              const tone = SPEC_TONE[s.spec_id] ?? 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-700'
              return (
                <div key={s.id} className={`rounded-md border px-2 py-1.5 ${tone}`}>
                  <div className="text-[11px] font-semibold leading-tight">{s.id}</div>
                  <div className="text-[10px] opacity-80 font-mono">{s.spec_id}</div>
                  {s.after && s.after.length > 0 && (
                    <div className="text-[9px] opacity-60 mt-0.5">← {s.after.join(', ')}</div>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
