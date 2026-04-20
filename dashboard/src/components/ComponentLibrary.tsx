// 컴포넌트 라이브러리 — 페르소나 / 스킬 / 도구 카탈로그 뷰
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MatIcon } from './icons'

type Persona = {
  id: string
  display_name: string
  description: string
  category: string
  tags?: string[]
}

type Skill = {
  id: string
  display_name: string
  description: string
  category: string
  tags?: string[]
}

type Tool = {
  id: string
  name: string
  description: string
  category: string
  enabled: boolean
  env_var?: string
  token_set?: boolean
}

type ComponentsData = {
  personas: Persona[]
  skills: Skill[]
  tools: Tool[]
}

const CATEGORY_BADGE: Record<string, string> = {
  general:     'bg-gray-500/20 text-gray-400',
  research:    'bg-blue-500/20 text-blue-400',
  planning:    'bg-indigo-500/20 text-indigo-400',
  design:      'bg-pink-500/20 text-pink-400',
  engineering: 'bg-orange-500/20 text-orange-400',
  review:      'bg-yellow-500/20 text-yellow-500',
  writing:     'bg-emerald-500/20 text-emerald-400',
  file:        'bg-purple-500/20 text-purple-400',
  code:        'bg-orange-500/20 text-orange-400',
  qa:          'bg-red-500/20 text-red-400',
  common:      'bg-gray-500/20 text-gray-400',
  integration: 'bg-teal-500/20 text-teal-400',
}

function Pill({ cat }: { cat: string }) {
  const cls = CATEGORY_BADGE[cat] ?? 'bg-gray-500/20 text-gray-400'
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${cls}`}>
      {cat || 'general'}
    </span>
  )
}

function Card({ title, id, cat, desc, tags, footer }: {
  title: string; id: string; cat: string; desc: string
  tags?: string[]; footer?: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 flex flex-col gap-2 hover:border-blue-500/50 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold text-gray-900 dark:text-gray-100 truncate">{title}</div>
          <div className="text-[11px] text-gray-400 font-mono truncate">{id}</div>
        </div>
        <Pill cat={cat} />
      </div>
      <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{desc || '(설명 없음)'}</p>
      {tags && tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {tags.map((t) => (
            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
              #{t}
            </span>
          ))}
        </div>
      )}
      {footer}
    </div>
  )
}

export function ComponentLibrary({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<'personas' | 'skills' | 'tools'>('personas')
  const [q, setQ] = useState('')

  const { data, isLoading, error } = useQuery<ComponentsData>({
    queryKey: ['components-catalog'],
    queryFn: async () => {
      const res = await fetch('/api/components')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    },
    staleTime: 60_000,
  })

  const personas = data?.personas ?? []
  const skills = data?.skills ?? []
  const tools = data?.tools ?? []

  const filter = (text: string) => !q || text.toLowerCase().includes(q.toLowerCase())

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50 dark:bg-gray-950">
      {/* 헤더 */}
      <header className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <button
          onClick={onBack}
          aria-label="뒤로"
          className="md:hidden p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
        >
          <MatIcon name="arrow_back" className="text-[20px]" />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-bold">컴포넌트 라이브러리</h1>
          <p className="text-[11px] text-gray-500">Job 파이프라인에서 선택 가능한 페르소나·스킬·도구</p>
        </div>
      </header>

      {/* 탭 + 검색 */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        {(['personas', 'skills', 'tools'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === t
                ? 'bg-blue-600/15 text-blue-500'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            {t === 'personas' ? `페르소나 (${personas.length})` : t === 'skills' ? `스킬 (${skills.length})` : `도구 (${tools.length})`}
          </button>
        ))}
        <div className="ml-auto">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="검색"
            className="px-3 py-1.5 rounded-lg text-sm bg-gray-100 dark:bg-gray-800 border border-transparent focus:border-blue-500 outline-none w-40 md:w-60"
          />
        </div>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-auto p-4">
        {isLoading && <p className="text-sm text-gray-500">불러오는 중...</p>}
        {error && <p className="text-sm text-red-500">로드 실패: {(error as Error).message}</p>}

        {tab === 'personas' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {personas.filter((p) => filter(p.display_name + p.id + p.description)).map((p) => (
              <Card key={p.id} id={p.id} title={p.display_name} cat={p.category} desc={p.description} tags={p.tags} />
            ))}
          </div>
        )}

        {tab === 'skills' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {skills.filter((s) => filter(s.display_name + s.id + s.description)).map((s) => (
              <Card key={s.id} id={s.id} title={s.display_name} cat={s.category} desc={s.description} tags={s.tags} />
            ))}
          </div>
        )}

        {tab === 'tools' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {tools.filter((t) => filter(t.name + t.id + t.description)).map((t) => (
              <Card
                key={t.id}
                id={t.id}
                title={t.name}
                cat={t.category}
                desc={t.description}
                footer={
                  <div className="flex items-center gap-2 mt-1 text-[11px]">
                    {t.enabled ? (
                      <span className="text-emerald-500">● 활성</span>
                    ) : (
                      <span className="text-gray-400">○ 비활성</span>
                    )}
                    {t.env_var && (
                      <span className={t.token_set ? 'text-emerald-500' : 'text-amber-500'}>
                        {t.env_var} {t.token_set ? '✓' : '미설정'}
                      </span>
                    )}
                  </div>
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
