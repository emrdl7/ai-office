// 통합 검색 패널 — chat_logs / suggestions / dynamics 교차 검색
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { displayName } from '../config/team'
import { MatIcon } from './icons'

type SearchType = 'all' | 'logs' | 'suggestions' | 'dynamics'

interface LogHit {
  id: string
  agent_id: string
  event_type: string
  message: string
  timestamp: string
}
interface SuggestionHit {
  id: string
  title: string
  content: string
  category: string
  status: string
  agent_id: string
  target_agent?: string
  source_log_id?: string
  created_at: string
}
interface DynamicHit {
  from_agent: string
  to_agent: string
  dynamic_type: string
  description: string
  timestamp: string
}
interface SearchResponse {
  q: string
  type: string
  logs?: LogHit[]
  suggestions?: SuggestionHit[]
  dynamics?: DynamicHit[]
}

function jumpToLog(logId: string, onClose: () => void) {
  onClose()
  setTimeout(() => {
    const el = document.getElementById(`log-${logId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('ring-2', 'ring-amber-400')
      setTimeout(() => el.classList.remove('ring-2', 'ring-amber-400'), 1600)
    }
  }, 120)
}

export function SearchPanel({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState('')
  const [type, setType] = useState<SearchType>('all')
  const [includeArchive, setIncludeArchive] = useState(false)
  const [errorsPreset, setErrorsPreset] = useState(false)
  const [data, setData] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)

  // q 디바운스 — 400ms. errors preset은 q가 비어도 동작.
  const qTrim = q.trim()
  useEffect(() => {
    if (!errorsPreset && qTrim.length < 2) { setData(null); return }
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const params = new URLSearchParams({
          q: qTrim, type, include_archive: String(includeArchive), limit: '30',
        })
        if (errorsPreset) params.set('preset', 'errors')
        const res = await fetch(`/api/search?${params.toString()}`)
        setData(await res.json())
      } finally {
        setLoading(false)
      }
    }, 400)
    return () => clearTimeout(timer)
  }, [qTrim, type, includeArchive, errorsPreset])

  const totals = useMemo(() => ({
    logs: data?.logs?.length ?? 0,
    suggestions: data?.suggestions?.length ?? 0,
    dynamics: data?.dynamics?.length ?? 0,
  }), [data])

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 md:p-10 pt-20">
      <div className="absolute inset-0 bg-black/60 dark:bg-black/70" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-white dark:bg-gray-800
        border border-gray-200 dark:border-gray-700
        rounded-2xl shadow-2xl overflow-hidden max-h-[80vh] flex flex-col">
        <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 space-y-3">
          <div className="flex items-center gap-3">
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="검색어 (2글자 이상) — 로그·건의·팀 다이내믹"
              className="flex-1 px-3 py-2 rounded-lg text-sm
                bg-gray-50 dark:bg-gray-900
                border border-gray-200 dark:border-gray-700
                text-gray-900 dark:text-gray-100
                focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
                dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
                cursor-pointer transition-colors"
              aria-label="닫기">
              <MatIcon name="close" className="text-[20px]" />
            </button>
          </div>
          <div className="flex items-center gap-2 text-xs flex-wrap">
            <button
              onClick={() => setErrorsPreset((v) => !v)}
              className={`px-2.5 py-1 rounded-md cursor-pointer transition-colors whitespace-nowrap ${
                errorsPreset
                  ? 'bg-red-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
              title="error / system_notice 이벤트만"
            >
              <MatIcon name="warning" className="text-[13px] mr-0.5" /> 에러만
            </button>
            {(['all', 'logs', 'suggestions', 'dynamics'] as SearchType[]).map((t) => (
              <button
                key={t}
                onClick={() => setType(t)}
                className={`px-2.5 py-1 rounded-md cursor-pointer transition-colors whitespace-nowrap ${
                  type === t
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                }`}
              >
                {t === 'all' ? '전체' : t === 'logs' ? '로그' : t === 'suggestions' ? '건의' : '다이내믹'}
              </button>
            ))}
            <label className="ml-auto flex items-center gap-1.5 text-gray-500 dark:text-gray-400 cursor-pointer whitespace-nowrap">
              <input
                type="checkbox"
                checked={includeArchive}
                onChange={(e) => setIncludeArchive(e.target.checked)}
                className="rounded cursor-pointer"
              />
              아카이브 포함
            </label>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {!errorsPreset && qTrim.length < 2 && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">
              2글자 이상 입력하세요
            </p>
          )}
          {(errorsPreset || qTrim.length >= 2) && loading && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-4">검색 중...</p>
          )}
          {(errorsPreset || qTrim.length >= 2) && !loading && data && totals.logs + totals.suggestions + totals.dynamics === 0 && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">결과 없음</p>
          )}

          {data?.logs && data.logs.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                로그 ({data.logs.length})
              </h3>
              <ul className="space-y-1.5">
                {data.logs.map((l) => (
                  <li key={l.id}>
                    <button
                      onClick={() => jumpToLog(l.id, onClose)}
                      className="w-full text-left px-3 py-2 rounded-lg
                        bg-gray-50 dark:bg-gray-900 hover:bg-gray-100 dark:hover:bg-gray-700
                        cursor-pointer transition-colors"
                    >
                      <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                        <span className="font-medium">{displayName(l.agent_id)}</span>
                        <span>·</span>
                        <span>{new Date(l.timestamp).toLocaleString('ko-KR')}</span>
                      </div>
                      <p className="text-sm text-gray-800 dark:text-gray-200 mt-0.5 line-clamp-2">
                        {l.message}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {data?.suggestions && data.suggestions.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                건의 ({data.suggestions.length})
              </h3>
              <ul className="space-y-1.5">
                {data.suggestions.map((s) => (
                  <li key={s.id} className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                    <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                      <span className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700">{s.category}</span>
                      <span>·</span>
                      <span>{s.status}</span>
                      {s.target_agent && <><span>·</span><span>→ {displayName(s.target_agent)}</span></>}
                    </div>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100 mt-1">{s.title}</p>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5 line-clamp-2">{s.content}</p>
                    {s.source_log_id && (
                      <button
                        onClick={() => jumpToLog(s.source_log_id!, onClose)}
                        className="mt-1 text-xs text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
                      >
                        <span className="inline-flex items-center gap-1"><MatIcon name="my_location" className="text-[12px]" /> 원본 발화로 이동</span>
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {data?.dynamics && data.dynamics.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                팀 다이내믹 ({data.dynamics.length})
              </h3>
              <ul className="space-y-1.5">
                {data.dynamics.map((d, i) => (
                  <li key={i} className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-900">
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      <span>{displayName(d.from_agent)}</span>
                      <span className="mx-1">→</span>
                      <span>{displayName(d.to_agent)}</span>
                      <span className="mx-1.5 px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700">{d.dynamic_type}</span>
                      <span>· {new Date(d.timestamp).toLocaleString('ko-KR')}</span>
                    </div>
                    {d.description && (
                      <p className="text-sm text-gray-700 dark:text-gray-300 mt-0.5">{d.description}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
