// 건의게시판 모달 — 팀원 건의 목록 + 상태 관리
import { useState, useEffect } from 'react'
import { useStore } from '../store'
import { AGENT_PROFILE } from './Sidebar'
import { IconBrain, IconWrench, IconSearch, IconGitMerge, IconTrash, IconGitBranch } from './icons'

interface Suggestion {
  id: string
  agent_id: string
  category: string
  title: string
  content: string
  status: string
  response: string
  created_at: string
  updated_at: string
  suggestion_type?: string  // 'prompt' | 'rule' | 'code'
  target_agent?: string     // 적용 대상 에이전트 (빈 값이면 제안자 본인)
  auto_applied?: number     // 자동 반영 여부 (0/1)
  auto_applied_at?: string  // ISO timestamp
}

const TYPE_BADGE: Record<string, { Icon: typeof IconBrain; label: string; color: string }> = {
  prompt: { Icon: IconBrain, label: '프롬프트', color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
  rule: { Icon: IconBrain, label: '규칙', color: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400' },
  code: { Icon: IconWrench, label: '코드 수정', color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
}

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  pending: { text: '대기', color: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
  accepted: { text: '처리 중...', color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse' },
  review_pending: { text: '검토 대기', color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  supplementing: { text: '보완 중...', color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 animate-pulse' },
  rejected: { text: '반려', color: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
  done: { text: '반영 완료', color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
}

const CATEGORY_LABEL: Record<string, string> = {
  general: '일반',
  '도구 부족': '도구',
  '정보 부족': '정보',
  '데이터 부족': '데이터',
}

export function SuggestionModal() {
  const show = useStore((s) => s.showSuggestions)
  const setShow = useStore((s) => s.setShowSuggestions)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Suggestion | null>(null)
  const [comment, setComment] = useState('')
  const [tab, setTab] = useState<string>('pending')
  const [query, setQuery] = useState('')
  const [events, setEvents] = useState<Record<string, Array<{id: number; ts: string; kind: string; payload: Record<string, unknown>}>>>({})

  async function loadEvents(id: string) {
    if (events[id]) return
    try {
      const r = await fetch(`/api/suggestions/${id}/events`)
      const data = await r.json()
      setEvents((prev) => ({ ...prev, [id]: data }))
    } catch { /* 무시 */ }
  }

  const fetchSuggestions = () =>
    fetch('/api/suggestions')
      .then((r) => r.json())
      .then(setSuggestions)

  useEffect(() => {
    if (!show) return
    setLoading(true)
    fetchSuggestions().finally(() => setLoading(false))
  }, [show])

  // accepted/supplementing 상태(작업 중) 항목이 있으면 3초마다 자동 갱신
  useEffect(() => {
    const hasActive = suggestions.some((s) => s.status === 'accepted' || s.status === 'supplementing')
    if (!hasActive) return
    const timer = setInterval(() => fetchSuggestions(), 3000)
    return () => clearInterval(timer)
  }, [suggestions])

  const [branchDiff, setBranchDiff] = useState<{ id: string; stat: string; diff: string; files: string[] } | null>(null)
  const [explain, setExplain] = useState<{
    intent?: string; effects?: string[]; risks?: string[];
    verdict?: string; verdict_reason?: string;
    recommendation?: string; recommendation_reason?: string;
    supplement_count?: number;
    error?: string;
  } | null>(null)
  const [explainLoading, setExplainLoading] = useState(false)

  async function loadBranchDiff(id: string) {
    try {
      const r = await fetch(`/api/suggestions/${id}/branch`)
      if (!r.ok) { alert('브랜치 정보를 가져올 수 없습니다'); return }
      const data = await r.json()
      setBranchDiff({ id, stat: data.stat, diff: data.diff, files: data.files || [] })
      // AI 리뷰는 비동기 로드
      setExplain(null); setExplainLoading(true)
      fetch(`/api/suggestions/${id}/branch/explain`)
        .then((r) => r.json())
        .then(setExplain)
        .catch(() => setExplain({ error: '분석 실패' }))
        .finally(() => setExplainLoading(false))
    } catch { alert('네트워크 오류') }
  }

  async function mergeBranch(id: string) {
    if (!confirm(`improvement/${id} 브랜치를 main으로 병합합니다. 계속할까요?\n(병합 후 서버 재시작이 필요합니다)`)) return
    const r = await fetch(`/api/suggestions/${id}/branch/merge`, { method: 'POST' })
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: '알 수 없는 오류' }))
      alert('병합 실패: ' + (err.detail || ''))
      return
    }
    setBranchDiff(null)
    fetchSuggestions()
    if (confirm('병합 완료. 지금 서버를 재시작할까요?\n(백엔드만 재기동 — 5초 내 자동 복귀)')) {
      await fetch('/api/server/restart', { method: 'POST' })
    }
  }

  async function discardBranch(id: string) {
    if (!confirm(`improvement/${id} 브랜치를 폐기합니다 (변경사항 버림). 계속할까요?`)) return
    await fetch(`/api/suggestions/${id}/branch/discard`, { method: 'POST' })
    setBranchDiff(null)
    fetchSuggestions()
  }

  async function supplementBranch(id: string) {
    const instruction = prompt(
      '추가 지시사항 (선택) — AI 리뷰 위험사항 외에 더 보완할 내용:',
      '',
    )
    if (instruction === null) return
    const iterStr = prompt('자동 반복 최대 횟수 (1~5, 기본 3)', '3')
    if (iterStr === null) return
    const max_iterations = Math.min(5, Math.max(1, parseInt(iterStr || '3', 10) || 3))
    const r = await fetch(`/api/suggestions/${id}/branch/supplement`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction, max_iterations }),
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: '실패' }))
      alert('보완 요청 실패: ' + (err.detail || ''))
      return
    }
    alert(`보완 대기열 투입 — 최대 ${max_iterations}회 반복. 진행 상황은 채팅에 공지됩니다.\n중간 수렴(merge/discard 판정) 시 조기 종료.`)
    setBranchDiff(null)
    fetchSuggestions()
  }

  async function rollbackAuto(id: string) {
    if (!confirm(`자동 반영된 건의 #${id}를 되돌립니다.\n에이전트 규칙·팀 메모리에서 해당 항목이 제거됩니다. 계속할까요?`)) return
    const r = await fetch(`/api/suggestions/${id}/rollback`, { method: 'POST' })
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: '실패' }))
      alert('롤백 실패: ' + (err.detail || ''))
      return
    }
    fetchSuggestions()
  }

  async function handleStatusChange(id: string, status: string, response: string = '') {
    await fetch(`/api/suggestions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, response }),
    })
    setSuggestions((prev) => prev.map((s) => (s.id === id ? { ...s, status, response } : s)))
    setComment('')
  }

  async function handleDelete(id: string) {
    await fetch(`/api/suggestions/${id}`, { method: 'DELETE' })
    setSuggestions((prev) => prev.filter((s) => s.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  if (!show) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={() => setShow(false)}
    >
      <div
        className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-[92vw] max-w-3xl
          max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-gray-900 dark:text-gray-100">
              건의게시판
            </h2>
            <button
              onClick={() => setShow(false)}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-xl cursor-pointer leading-none"
            >
              &times;
            </button>
          </div>
          {/* 탭 + 검색 */}
          <div className="flex items-center gap-1.5 mt-3 flex-wrap">
            {(() => {
              const counts: Record<string, number> = { all: suggestions.length }
              suggestions.forEach((s) => { counts[s.status] = (counts[s.status] || 0) + 1 })
              // auto_applied 별도 집계
              counts['auto_applied'] = suggestions.filter((s) => s.auto_applied === 1).length
              const tabs: [string, string][] = [
                ['pending', '대기'],
                ['review_pending', '검토 대기'],
                ['accepted', '처리 중'],
                ['supplementing', '🛠️ 보완 중'],
                ['auto_applied', '🤖 자동 반영'],
                ['done', '완료'],
                ['rejected', '반려'],
                ['all', '전체'],
              ]
              return tabs.map(([key, label]) => {
                const n = counts[key] || 0
                if (n === 0 && key !== 'pending' && key !== 'all') return null
                const active = tab === key
                return (
                  <button key={key} onClick={() => setTab(key)}
                    className={`text-xs px-2.5 py-1 rounded-full cursor-pointer transition
                      ${active
                        ? 'bg-blue-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'}`}>
                    {label} {n > 0 && <span className={active ? 'opacity-80' : 'opacity-60'}>{n}</span>}
                  </button>
                )
              })
            })()}
            <div className="flex-1" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="검색..."
              className="text-xs px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-800
                text-gray-700 dark:text-gray-200 placeholder-gray-400 w-32
                focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
        </div>

        {/* 본문 */}
        <div className="flex-1 overflow-y-auto p-3">
          {(() => {
            const filtered = suggestions.filter((s) => {
              if (tab === 'auto_applied') {
                if (s.auto_applied !== 1) return false
              } else if (tab !== 'all' && s.status !== tab) return false
              if (query && !`${s.title} ${s.content}`.toLowerCase().includes(query.toLowerCase())) return false
              return true
            })
            if (loading) return <p className="text-center text-gray-400 py-8">로딩 중...</p>
            if (filtered.length === 0) return (
              <p className="text-center text-gray-400 py-8">
                {query ? '검색 결과 없음' : '건의 사항이 없습니다'}
              </p>
            )
            return (
            <div className="space-y-2">
              {filtered.map((s) => {
                const profile = AGENT_PROFILE[s.agent_id]
                const statusInfo = STATUS_LABEL[s.status] || STATUS_LABEL.pending
                const catLabel = CATEGORY_LABEL[s.category] || s.category
                const isExpanded = selected?.id === s.id
                const t = TYPE_BADGE[s.suggestion_type || 'prompt']
                const isFollowUp = /^\[follow-up/i.test(s.title)
                const cleanTitle = isFollowUp ? s.title.replace(/^\[follow-up\s*#?[a-f0-9]*\]\s*/i, '') : s.title
                const parentMatch = isFollowUp ? /^\[follow-up\s*#?([a-f0-9]+)\]/i.exec(s.title) : null
                const parentId = parentMatch?.[1] || ''

                return (
                  <div
                    key={s.id}
                    className={`rounded-lg border transition
                      ${s.status === 'supplementing' || s.status === 'accepted'
                        ? 'opacity-70 cursor-not-allowed'
                        : 'cursor-pointer'}
                      ${isExpanded
                        ? 'border-blue-300 dark:border-blue-700 bg-blue-50/40 dark:bg-blue-950/20'
                        : 'border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 bg-white dark:bg-gray-900'}
                      ${isFollowUp ? 'border-l-4 !border-l-purple-400 dark:!border-l-purple-600' : ''}`}
                    onClick={() => {
                      if (s.status === 'supplementing' || s.status === 'accepted') return
                      setSelected(isExpanded ? null : s)
                      setComment('')
                      if (!isExpanded) loadEvents(s.id)
                    }}
                  >
                    {/* 카드 — 2줄 레이아웃 */}
                    <div className="px-3.5 py-2.5">
                      {/* 1행: 제목 */}
                      <div className="flex items-start gap-2">
                        {isFollowUp && (
                          <span className="shrink-0 mt-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded
                            bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
                            title={parentId ? `원 건의 #${parentId}의 후속` : '후속 조치'}>
                            FOLLOW-UP
                          </span>
                        )}
                        <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-200 break-words">
                          {cleanTitle}
                        </span>
                      </div>
                      {/* 2행: 메타 */}
                      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap text-[10px]">
                        <span className="text-gray-500 dark:text-gray-400 font-medium">
                          {profile?.character || s.agent_id}
                        </span>
                        {s.target_agent && s.target_agent !== s.agent_id && (
                          <span className="text-gray-400">→</span>
                        )}
                        {s.target_agent && s.target_agent !== s.agent_id && (
                          <span className="text-indigo-600 dark:text-indigo-400 font-medium"
                            title="이 건의가 적용될 에이전트">
                            {AGENT_PROFILE[s.target_agent]?.character || s.target_agent}
                          </span>
                        )}
                        <span className="text-gray-300 dark:text-gray-700">·</span>
                        <span className={`px-1.5 py-0.5 rounded-full inline-flex items-center gap-1 ${t.color}`}>
                          <t.Icon className="w-3 h-3" /> {t.label}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded-full ${statusInfo.color}`}>
                          {statusInfo.text}
                        </span>
                        {s.auto_applied === 1 && (
                          <span className="px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700
                            dark:bg-amber-900/30 dark:text-amber-400"
                            title="팀장이 자동 반영함 — 24h 내 되돌리기 가능">
                            🤖 자동
                          </span>
                        )}
                        <span className="px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
                          {catLabel}
                        </span>
                        {parentId && (
                          <span className="px-1.5 py-0.5 rounded-full bg-purple-50 dark:bg-purple-950/30
                            text-purple-600 dark:text-purple-400 font-mono"
                            title="원 건의 ID">
                            #{parentId}
                          </span>
                        )}
                        <span className="ml-auto text-gray-400">
                          {new Date(s.created_at).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' })}
                        </span>
                      </div>
                    </div>

                    {/* 상세 (펼침) */}
                    {isExpanded && (
                      <div className="px-4 pb-4 border-t border-gray-100 dark:border-gray-800 pt-3">
                        <p className="text-sm text-gray-600 dark:text-gray-400 mb-3 whitespace-pre-wrap">
                          {s.content}
                        </p>
                        {events[s.id] && events[s.id].length > 0 && (
                          <div className="mb-3 rounded-lg bg-gray-50 dark:bg-gray-800/40 px-3 py-2">
                            <p className="text-[10px] text-gray-500 dark:text-gray-400 mb-1">이력</p>
                            <div className="space-y-0.5">
                              {events[s.id].slice(0, 8).map((ev) => (
                                <div key={ev.id} className="flex items-center gap-2 text-[11px]">
                                  <span className="text-gray-400 font-mono">
                                    {new Date(ev.ts).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                                  </span>
                                  <span className="px-1.5 py-0.5 rounded bg-white dark:bg-gray-700
                                    text-gray-700 dark:text-gray-200 font-medium">
                                    {ev.kind}
                                  </span>
                                  {Object.keys(ev.payload || {}).length > 0 && (
                                    <span className="text-gray-500 dark:text-gray-400 truncate">
                                      {Object.entries(ev.payload).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ')}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {s.response && s.status !== 'pending' && (
                          <div className="mb-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 px-3 py-2">
                            <p className="text-[10px] text-gray-500 dark:text-gray-400 mb-1">
                              {s.status === 'rejected' ? '반려 이유' : '승인 코멘트'}
                            </p>
                            <p className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                              {s.response}
                            </p>
                          </div>
                        )}
                        {s.status === 'pending' && (
                          <textarea
                            value={comment}
                            onChange={(e) => setComment(e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                            placeholder="승인 코멘트 / 반려 이유 (선택) — 에이전트 프롬프트·메모리에 함께 반영됩니다"
                            className="w-full mb-3 px-3 py-2 text-xs rounded-lg border border-gray-200
                              dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700
                              dark:text-gray-200 placeholder-gray-400 resize-y min-h-[52px]
                              focus:outline-none focus:border-blue-400 dark:focus:border-blue-600"
                          />
                        )}
                        <div className="flex gap-2">
                          {s.status === 'pending' && (
                            <>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  const isCode = s.suggestion_type === 'code'
                                  if (isCode && !confirm(
                                    '이 건의는 코드 수정이 필요한 것으로 분류됐습니다.\n\n' +
                                    '1) Claude가 improvement 브랜치에서 코드 수정\n' +
                                    '2) 수정 완료되면 "검토 대기" 상태로 전환\n' +
                                    '3) 사용자가 변경사항 확인 → 병합/폐기 결정\n\n' +
                                    '계속할까요?'
                                  )) return
                                  handleStatusChange(s.id, 'accepted', comment)
                                }}
                                className="text-xs px-3 py-1 rounded-lg bg-green-500 text-white
                                  hover:bg-green-600 cursor-pointer transition-colors"
                                title={
                                  s.suggestion_type === 'code'
                                    ? 'Claude가 코드 수정 → 검토 대기 (병합은 별도 승인)'
                                    : '에이전트 프롬프트 + 팀 메모리에 즉시 반영'
                                }
                              >
                                승인
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleStatusChange(s.id, 'rejected', comment) }}
                                className="text-xs px-3 py-1 rounded-lg bg-red-500 text-white
                                  hover:bg-red-600 cursor-pointer transition-colors"
                              >
                                반려
                              </button>
                            </>
                          )}
                          {s.auto_applied === 1 && s.auto_applied_at && (() => {
                            const elapsed = (Date.now() - new Date(s.auto_applied_at).getTime()) / 36e5
                            const remaining = 24 - elapsed
                            if (remaining <= 0) return (
                              <span className="text-xs text-gray-400 px-2 py-1">롤백 유예 종료</span>
                            )
                            return (
                              <button
                                onClick={(e) => { e.stopPropagation(); rollbackAuto(s.id) }}
                                className="text-xs px-3 py-1 rounded-lg bg-amber-500 text-white
                                  hover:bg-amber-600 cursor-pointer transition-colors
                                  inline-flex items-center gap-1.5"
                                title={`자동 반영 되돌리기 — ${remaining.toFixed(1)}시간 남음`}
                              >
                                ↩️ 되돌리기 ({remaining.toFixed(0)}h)
                              </button>
                            )
                          })()}
                          {s.status === 'review_pending' && (
                            <>
                              <button
                                onClick={(e) => { e.stopPropagation(); loadBranchDiff(s.id) }}
                                className="text-xs px-3 py-1 rounded-lg bg-purple-500 text-white
                                  hover:bg-purple-600 cursor-pointer transition-colors
                                  inline-flex items-center gap-1.5"
                              >
                                <IconSearch className="w-3.5 h-3.5" /> 변경사항 보기
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); mergeBranch(s.id) }}
                                className="text-xs px-3 py-1 rounded-lg bg-green-500 text-white
                                  hover:bg-green-600 cursor-pointer transition-colors
                                  inline-flex items-center gap-1.5"
                                title="main 브랜치로 병합 (재시작 필요)"
                              >
                                <IconGitMerge className="w-3.5 h-3.5" /> 병합
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); supplementBranch(s.id) }}
                                className="text-xs px-3 py-1 rounded-lg bg-amber-500 text-white
                                  hover:bg-amber-600 cursor-pointer transition-colors
                                  inline-flex items-center gap-1.5"
                                title="AI 리뷰 위험사항 보완 — Claude 재실행"
                              >
                                🛠️ 보완
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); discardBranch(s.id) }}
                                className="text-xs px-3 py-1 rounded-lg bg-red-500 text-white
                                  hover:bg-red-600 cursor-pointer transition-colors
                                  inline-flex items-center gap-1.5"
                              >
                                <IconTrash className="w-3.5 h-3.5" /> 폐기
                              </button>
                            </>
                          )}
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDelete(s.id) }}
                            className="text-xs px-3 py-1 rounded-lg bg-gray-200 dark:bg-gray-700
                              text-gray-600 dark:text-gray-300 hover:bg-gray-300
                              dark:hover:bg-gray-600 cursor-pointer transition-colors ml-auto"
                          >
                            삭제
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            )
          })()}
        </div>
      </div>
      {branchDiff && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60"
          onClick={() => setBranchDiff(null)}
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-[92vw] max-w-4xl
              max-h-[85vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
              <div>
                <h3 className="text-base font-bold text-gray-900 dark:text-gray-100
                  inline-flex items-center gap-2">
                  <IconGitBranch className="w-4 h-4 text-emerald-500" />
                  improvement/{branchDiff.id}
                </h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  {branchDiff.files.length}개 파일 변경
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => mergeBranch(branchDiff.id)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-green-500 text-white hover:bg-green-600 cursor-pointer
                    inline-flex items-center gap-1.5"
                >
                  <IconGitMerge className="w-3.5 h-3.5" /> 병합
                </button>
                <button
                  onClick={() => supplementBranch(branchDiff.id)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-amber-500 text-white hover:bg-amber-600 cursor-pointer
                    inline-flex items-center gap-1.5"
                  title="AI 리뷰 위험사항 보완 — Claude 재실행"
                >
                  🛠️ 보완
                </button>
                <button
                  onClick={() => discardBranch(branchDiff.id)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-red-500 text-white hover:bg-red-600 cursor-pointer
                    inline-flex items-center gap-1.5"
                >
                  <IconTrash className="w-3.5 h-3.5" /> 폐기
                </button>
                <button
                  onClick={() => setBranchDiff(null)}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-xl cursor-pointer"
                >
                  &times;
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {/* AI 리뷰 — 의도/효과/위험 */}
              <div className="rounded-lg border border-indigo-200 dark:border-indigo-800
                bg-indigo-50/40 dark:bg-indigo-950/20 p-3">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-bold text-indigo-700 dark:text-indigo-300">
                    AI 리뷰 — 의도 · 효과 · 위험
                  </h4>
                  {explain?.verdict && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium
                      ${explain.verdict === 'merge_safe' ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' :
                        explain.verdict === 'risky' ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' :
                        'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400'}`}
                      title={explain.verdict_reason || ''}>
                      {explain.verdict === 'merge_safe' ? '안전' :
                       explain.verdict === 'risky' ? '위험' : '검토 필요'}
                    </span>
                  )}
                </div>
                {explainLoading && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">AI 분석 중... (10~30초)</p>
                )}
                {!explainLoading && explain?.error && (
                  <p className="text-xs text-red-500">{explain.error}</p>
                )}
                {!explainLoading && explain && !explain.error && (
                  <div className="space-y-2 text-xs">
                    {explain.recommendation && (() => {
                      const rec = explain.recommendation
                      const supCount = explain.supplement_count || 0
                      const needsFixLabel = supCount > 0
                        ? `${supCount}회 보완 후에도 추가 개선 여지 — 수동 검토 또는 폐기 권장 (추가 보완은 수렴 어려울 수 있음)`
                        : '보완 필요 (🛠️ 보완 버튼으로 Claude 재실행 가능)'
                      const cfg = rec === 'merge'
                        ? { label: '병합 권장', icon: '🔀', cls: 'bg-green-50 dark:bg-green-950/30 border-green-300 dark:border-green-700 text-green-800 dark:text-green-300' }
                        : rec === 'discard'
                          ? { label: '폐기 권장', icon: '🗑️', cls: 'bg-red-50 dark:bg-red-950/30 border-red-300 dark:border-red-700 text-red-800 dark:text-red-300' }
                          : { label: needsFixLabel, icon: '🛠️', cls: 'bg-amber-50 dark:bg-amber-950/30 border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-300' }
                      return (
                        <div className={`rounded-md border px-2.5 py-1.5 ${cfg.cls}`}>
                          <div className="flex items-center gap-1.5 font-bold text-[11px]">
                            <span>{cfg.icon}</span>
                            <span>판단: {cfg.label}</span>
                            {supCount > 0 && (
                              <span className="ml-auto text-[10px] font-normal opacity-75">
                                보완 이력 {supCount}회
                              </span>
                            )}
                          </div>
                          {explain.recommendation_reason && (
                            <p className="mt-1 text-[11px] opacity-90 leading-relaxed whitespace-pre-wrap">
                              {explain.recommendation_reason}
                            </p>
                          )}
                        </div>
                      )
                    })()}
                    {explain.intent && (
                      <div>
                        <div className="font-semibold text-gray-700 dark:text-gray-300 mb-0.5">의도</div>
                        <div className="text-gray-600 dark:text-gray-400 whitespace-pre-wrap">{explain.intent}</div>
                      </div>
                    )}
                    {explain.effects && explain.effects.length > 0 && (
                      <div>
                        <div className="font-semibold text-emerald-700 dark:text-emerald-400 mb-0.5">기대 효과</div>
                        <ul className="list-disc pl-4 text-gray-600 dark:text-gray-400 space-y-0.5">
                          {explain.effects.map((e, i) => <li key={i}>{e}</li>)}
                        </ul>
                      </div>
                    )}
                    {explain.risks && explain.risks.length > 0 && (
                      <div>
                        <div className="font-semibold text-amber-700 dark:text-amber-400 mb-0.5">위험 · 주의</div>
                        <ul className="list-disc pl-4 text-gray-600 dark:text-gray-400 space-y-0.5">
                          {explain.risks.map((e, i) => <li key={i}>{e}</li>)}
                        </ul>
                      </div>
                    )}
                    {explain.verdict_reason && (
                      <div className="text-[10px] text-gray-500 dark:text-gray-500 pt-1 border-t border-gray-200 dark:border-gray-800">
                        판정 근거: {explain.verdict_reason}
                      </div>
                    )}
                  </div>
                )}
              </div>
              <pre className="text-xs bg-gray-50 dark:bg-gray-800 p-3 rounded-lg
                text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{branchDiff.stat}</pre>
              <pre className="text-xs bg-gray-900 dark:bg-black text-gray-100 p-3 rounded-lg
                overflow-x-auto whitespace-pre leading-relaxed font-mono">
{branchDiff.diff.split('\n').map((line, i) => {
  const cls = line.startsWith('+') && !line.startsWith('+++')
    ? 'text-green-400'
    : line.startsWith('-') && !line.startsWith('---')
      ? 'text-red-400'
      : line.startsWith('@@')
        ? 'text-cyan-400'
        : line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('+++') || line.startsWith('---')
          ? 'text-gray-500'
          : 'text-gray-200'
  return <div key={i} className={cls}>{line || ' '}</div>
})}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
