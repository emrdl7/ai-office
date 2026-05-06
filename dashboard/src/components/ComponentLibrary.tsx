// 컴포넌트 라이브러리 — 비서 실행 자산 레지스트리
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MatIcon } from './icons'

type UsedBy = {
  spec_id: string
  spec_title: string
  step_id: string
}

type RegistryStatus = 'ok' | 'warning' | 'error'
type QualityBand = 'ready' | 'needs_review' | 'blocked'

type RegistryItem = {
  id: string
  display_name: string
  description: string
  category: string
  tags?: string[]
  source?: string
  used_by?: UsedBy[]
  usage_count?: number
  failure_count?: number
  last_used_at?: string
  last_error?: string
  issues?: string[]
  status?: RegistryStatus
  quality_score?: number
  quality_band?: QualityBand
}

type Persona = RegistryItem
type Skill = RegistryItem

type Tool = RegistryItem & {
  id: string
  name: string
  description: string
  category: string
  enabled: boolean
  env_var?: string
  token_set?: boolean
  maturity?: 'core' | 'optional' | 'experimental' | 'disabled'
  input_contract?: string[]
  output_contract?: string
  failure_policy?: string
  recovery_hint?: string
}

type ComponentsData = {
  personas: Persona[]
  skills: Skill[]
  tools: Tool[]
  summary?: {
    total: number
    ok: number
    warning: number
    error: number
    ready: number
    needs_review: number
    blocked: number
    avg_quality_score: number
    unused: number
    broken_ref_count: number
    broken_refs: Array<{ kind: string; id: string; spec_id: string; step_id: string }>
  }
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

const STATUS_STYLE: Record<RegistryStatus, string> = {
  ok: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  warning: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  error: 'bg-red-500/15 text-red-600 dark:text-red-400',
}

const QUALITY_STYLE: Record<QualityBand, string> = {
  ready: 'text-emerald-600 dark:text-emerald-400',
  needs_review: 'text-amber-600 dark:text-amber-400',
  blocked: 'text-red-600 dark:text-red-400',
}

const ISSUE_LABEL: Record<string, string> = {
  unused: '미사용',
  disabled: '비활성',
  token_missing: '토큰 필요',
  missing_display_name: '이름 누락',
  missing_description: '설명 누락',
  missing_category: '분류 누락',
  missing_identity: '정체성 누락',
  missing_skill_body: '스킬 본문 누락',
  id_filename_mismatch: 'ID/파일명 불일치',
  recent_execution_failure: '최근 실패',
  experimental: '실험',
  missing_selection_criteria: '선택 기준 누락',
  missing_output_contract: '산출물 계약 누락',
  missing_quality_rubric: '품질 기준 누락',
  missing_input_conditions: '입력 조건 누락',
  missing_output_template: '출력 템플릿 누락',
}

function CapabilityMap({ personas, skills, tools }: { personas: Persona[]; skills: Skill[]; tools: Tool[] }) {
  const groups = [
    { label: 'Persona', items: personas, color: 'bg-cyan-500' },
    { label: 'Skill', items: skills, color: 'bg-emerald-500' },
    { label: 'Tool', items: tools, color: 'bg-amber-500' },
  ]
  return (
    <div className="rounded-[2rem] border border-white/70 bg-white/82 p-4 shadow-sm backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-400">Capability Map</p>
          <h2 className="mt-1 text-lg font-black tracking-tight text-slate-950 dark:text-white">업무 실행 능력 지도</h2>
        </div>
        <div className="hidden sm:grid grid-cols-3 gap-2 text-right">
          {groups.map((group) => (
            <div key={group.label}>
              <p className="text-[10px] text-slate-400">{group.label}</p>
              <p className="text-xl font-black text-slate-900 dark:text-white">{group.items.length}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {groups.map((group) => {
          const ready = group.items.filter((item) => item.quality_band === 'ready').length
          const avg = group.items.length
            ? Math.round(group.items.reduce((sum, item) => sum + (item.quality_score ?? 0), 0) / group.items.length)
            : 0
          return (
            <div key={group.label} className="rounded-2xl bg-slate-50/82 p-3 ring-1 ring-slate-200/80 dark:bg-slate-950/40 dark:ring-slate-800/80">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-700 dark:text-slate-200">{group.label}</span>
                <span className="text-[10px] text-slate-400">{ready}/{group.items.length} ready</span>
              </div>
              <div className="mt-3 h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div className={`h-full rounded-full ${group.color}`} style={{ width: `${avg}%` }} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">평균 품질 {avg}점</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Pill({ cat }: { cat: string }) {
  const cls = CATEGORY_BADGE[cat] ?? 'bg-gray-500/20 text-gray-400'
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${cls}`}>
      {cat || 'general'}
    </span>
  )
}

function StatusPill({ status = 'ok' }: { status?: RegistryStatus }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${STATUS_STYLE[status]}`}>
      {status === 'ok' ? '정상' : status === 'warning' ? '확인' : '오류'}
    </span>
  )
}

function Card({ title, id, cat, desc, tags, item, footer }: {
  title: string; id: string; cat: string; desc: string
  tags?: string[]; item: RegistryItem; footer?: React.ReactNode
}) {
  const issues = item.issues ?? []
  const usedBy = item.used_by ?? []
  const usageCount = item.usage_count ?? 0
  const failureCount = item.failure_count ?? 0
  const qualityScore = item.quality_score ?? 0
  const qualityBand = item.quality_band ?? 'blocked'
  return (
    <div className="rounded-2xl border border-white/70 bg-white/82 p-4 flex flex-col gap-2 shadow-sm backdrop-blur transition-colors hover:border-teal-300/80 dark:border-slate-700/70 dark:bg-slate-900/72 dark:hover:border-cyan-500/45">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold text-gray-900 dark:text-gray-100 truncate">{title}</div>
          <div className="text-[11px] text-gray-400 font-mono truncate">{id}</div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <StatusPill status={item.status} />
          <Pill cat={cat} />
        </div>
      </div>
      <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{desc || '(설명 없음)'}</p>
      <div className="grid grid-cols-3 gap-2 text-[11px] text-gray-500 dark:text-gray-400">
        <div className="rounded-xl bg-slate-50/82 dark:bg-slate-950/40 px-2 py-1">
          <div className="text-gray-400">Spec</div>
          <div className="font-semibold text-gray-700 dark:text-gray-200">{usedBy.length}</div>
        </div>
        <div className="rounded-xl bg-slate-50/82 dark:bg-slate-950/40 px-2 py-1">
          <div className="text-gray-400">실행</div>
          <div className="font-semibold text-gray-700 dark:text-gray-200">{usageCount}</div>
        </div>
        <div className="rounded-xl bg-slate-50/82 dark:bg-slate-950/40 px-2 py-1">
          <div className="text-gray-400">실패</div>
          <div className={failureCount ? 'font-semibold text-red-500' : 'font-semibold text-gray-700 dark:text-gray-200'}>
            {failureCount}
          </div>
        </div>
      </div>
      <div className="rounded-xl bg-slate-50/82 dark:bg-slate-950/40 px-2 py-1 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-gray-400">품질 점수</span>
          <span className={`font-semibold ${QUALITY_STYLE[qualityBand]}`}>
            {qualityScore} / {qualityBand === 'ready' ? 'ready' : qualityBand === 'needs_review' ? 'review' : 'blocked'}
          </span>
        </div>
        <div className="mt-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
          <div
            className={`h-full ${qualityBand === 'ready' ? 'bg-emerald-500' : qualityBand === 'needs_review' ? 'bg-amber-500' : 'bg-red-500'}`}
            style={{ width: `${Math.max(0, Math.min(100, qualityScore))}%` }}
          />
        </div>
      </div>
      {issues.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {issues.map((issue) => (
            <span key={issue} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300">
              {ISSUE_LABEL[issue] ?? issue}
            </span>
          ))}
        </div>
      )}
      {tags && tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {tags.map((t) => (
            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
              #{t}
            </span>
          ))}
        </div>
      )}
      {usedBy.length > 0 && (
        <div className="text-[11px] text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-800 pt-2 mt-1">
          <div className="font-medium text-gray-600 dark:text-gray-300 mb-1">사용처</div>
          <div className="space-y-0.5">
            {usedBy.slice(0, 3).map((u) => (
              <div key={`${u.spec_id}:${u.step_id}`} className="truncate">
                {u.spec_title || u.spec_id} / <span className="font-mono">{u.step_id}</span>
              </div>
            ))}
            {usedBy.length > 3 && <div>외 {usedBy.length - 3}개</div>}
          </div>
        </div>
      )}
      {footer}
    </div>
  )
}

export function ComponentLibrary({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<'personas' | 'skills' | 'tools'>('personas')
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | RegistryStatus | 'issue'>('all')
  const [categoryFilter, setCategoryFilter] = useState('all')

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
  const activeItems: Array<RegistryItem | Tool> = tab === 'personas' ? personas : tab === 'skills' ? skills : tools
  const categories = useMemo(
    () => Array.from(new Set(activeItems.map((item) => item.category || 'general'))).sort(),
    [activeItems],
  )

  const filteredItems = useMemo(() => {
    const query = q.trim().toLowerCase()
    return activeItems.filter((item) => {
      const title = 'name' in item ? item.name : item.display_name
      const haystack = [
        title,
        item.id,
        item.description,
        item.category,
        ...(item.tags ?? []),
        ...(item.issues ?? []),
      ].join(' ').toLowerCase()
      if (query && !haystack.includes(query)) return false
      if (categoryFilter !== 'all' && item.category !== categoryFilter) return false
      if (statusFilter === 'issue') return (item.issues ?? []).length > 0
      if (statusFilter !== 'all' && item.status !== statusFilter) return false
      return true
    })
  }, [activeItems, categoryFilter, q, statusFilter])

  const summary = data?.summary

  return (
    <div className="chat-canvas flex-1 flex flex-col min-h-0 bg-transparent">
      {/* 헤더 */}
      <header className="flex items-center gap-2 px-4 md:px-5 h-[64px] shrink-0 border-b border-slate-200/70 dark:border-slate-800/70 glass-panel rounded-none border-x-0 border-t-0">
        <button
          onClick={onBack}
          aria-label="뒤로"
          className="md:hidden p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <MatIcon name="arrow_back" className="text-[20px]" />
        </button>
        <div className="w-8 h-8 rounded-xl bg-slate-950 dark:bg-cyan-300 flex items-center justify-center shrink-0">
          <MatIcon name="widgets" className="text-[18px] text-white dark:text-slate-950" />
        </div>
        <div className="flex-1 min-w-0 leading-tight">
          <h1 className="text-sm font-black tracking-tight text-slate-900 dark:text-white">컴포넌트 라이브러리</h1>
        </div>
      </header>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 px-4 py-3 border-b border-gray-200/70 dark:border-gray-800/70 bg-white/50 dark:bg-slate-950/24 backdrop-blur">
          {[
            ['전체', summary.total],
            ['정상', summary.ok],
            ['확인', summary.warning],
            ['오류', summary.error + summary.broken_ref_count],
            ['평균품질', summary.avg_quality_score],
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl border border-white/70 bg-white/74 px-3 py-2 shadow-sm dark:border-slate-700/70 dark:bg-slate-900/62">
              <div className="text-[11px] text-gray-500">{label}</div>
              <div className="text-lg font-semibold text-gray-900 dark:text-white">{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* 탭 + 검색 */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-gray-200/70 dark:border-gray-800/70 bg-white/50 dark:bg-slate-950/24 backdrop-blur">
        {(['personas', 'skills', 'tools'] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setCategoryFilter('all') }}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === t
                ? 'bg-slate-950 dark:bg-cyan-300 text-white dark:text-slate-950'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            {t === 'personas' ? `페르소나 (${personas.length})` : t === 'skills' ? `스킬 (${skills.length})` : `도구 (${tools.length})`}
          </button>
        ))}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
            className="px-2 py-1.5 rounded-xl text-sm bg-white/76 dark:bg-slate-900/72 border border-white/70 dark:border-slate-700/70 focus:border-teal-400 outline-none"
          >
            <option value="all">전체 상태</option>
            <option value="ok">정상</option>
            <option value="warning">확인 필요</option>
            <option value="error">오류</option>
            <option value="issue">문제 있음</option>
          </select>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="px-2 py-1.5 rounded-xl text-sm bg-white/76 dark:bg-slate-900/72 border border-white/70 dark:border-slate-700/70 focus:border-teal-400 outline-none"
          >
            <option value="all">전체 분류</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="검색"
            className="px-3 py-1.5 rounded-xl text-sm bg-white/76 dark:bg-slate-900/72 border border-white/70 dark:border-slate-700/70 focus:border-teal-400 outline-none w-40 md:w-60"
          />
        </div>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-auto p-4">
        {isLoading && <p className="text-sm text-gray-500">불러오는 중...</p>}
        {error && <p className="text-sm text-red-500">로드 실패: {(error as Error).message}</p>}
        {summary && summary.broken_ref_count > 0 && (
          <div className="mb-3 rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/20 px-4 py-3 text-sm text-red-700 dark:text-red-300">
            깨진 참조 {summary.broken_ref_count}개가 있습니다. spec이 존재하지 않는 실행 자산을 참조합니다.
          </div>
        )}
        {summary && (
          <div className="mb-4">
            <CapabilityMap personas={personas} skills={skills} tools={tools} />
          </div>
        )}
        {summary && (
          <div className="mb-3 rounded-2xl border border-white/70 bg-white/76 px-4 py-3 text-xs text-gray-600 shadow-sm backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/72 dark:text-gray-300">
            실행 준비도: ready {summary.ready}개 · review {summary.needs_review}개 · blocked {summary.blocked}개 · 미사용 {summary.unused}개
          </div>
        )}

        {tab === 'personas' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {(filteredItems as Persona[]).map((p) => (
              <Card key={p.id} id={p.id} title={p.display_name} cat={p.category} desc={p.description} tags={p.tags} item={p} />
            ))}
          </div>
        )}

        {tab === 'skills' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {(filteredItems as Skill[]).map((s) => (
              <Card key={s.id} id={s.id} title={s.display_name} cat={s.category} desc={s.description} tags={s.tags} item={s} />
            ))}
          </div>
        )}

        {tab === 'tools' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {(filteredItems as Tool[]).map((t) => (
              <Card
                key={t.id}
                id={t.id}
                title={t.name}
                cat={t.category}
                desc={t.description}
                item={t}
                footer={
                  <div className="mt-1 text-[11px] space-y-1">
                    <div className="flex items-center gap-2">
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
                      {t.maturity && (
                        <span className="text-gray-400">tier: {t.maturity}</span>
                      )}
                    </div>
                    <div className="text-gray-500 dark:text-gray-400">
                      입력: {(t.input_contract ?? []).join(', ') || '필수 입력 없음'}
                    </div>
                    {t.failure_policy && (
                      <div className="text-gray-500 dark:text-gray-400 line-clamp-2">
                        실패: {t.failure_policy}
                      </div>
                    )}
                  </div>
                }
              />
            ))}
          </div>
        )}
        {!isLoading && filteredItems.length === 0 && (
          <p className="text-sm text-gray-500">조건에 맞는 항목이 없습니다.</p>
        )}
      </div>
    </div>
  )
}
