// 건의게시판 모달 — 팀원 건의 목록 + 상태 관리
import { useState, useEffect } from 'react'
import { useStore } from '../store'
import { AGENT_PROFILE } from './Sidebar'

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
}

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  pending: { text: '대기', color: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
  accepted: { text: '반영 중...', color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse' },
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

  const fetchSuggestions = () =>
    fetch('/api/suggestions')
      .then((r) => r.json())
      .then(setSuggestions)

  useEffect(() => {
    if (!show) return
    setLoading(true)
    fetchSuggestions().finally(() => setLoading(false))
  }, [show])

  // accepted 상태(반영 중) 항목이 있으면 3초마다 자동 갱신
  useEffect(() => {
    const hasPending = suggestions.some((s) => s.status === 'accepted')
    if (!hasPending) return
    const timer = setInterval(() => fetchSuggestions(), 3000)
    return () => clearInterval(timer)
  }, [suggestions])

  async function handleStatusChange(id: string, status: string) {
    await fetch(`/api/suggestions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    setSuggestions((prev) => prev.map((s) => (s.id === id ? { ...s, status } : s)))
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
        className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-[90vw] max-w-2xl
          max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
            건의게시판
          </h2>
          <button
            onClick={() => setShow(false)}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-xl cursor-pointer"
          >
            &times;
          </button>
        </div>

        {/* 본문 */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <p className="text-center text-gray-400 py-8">로딩 중...</p>
          ) : suggestions.length === 0 ? (
            <p className="text-center text-gray-400 py-8">건의 사항이 없습니다</p>
          ) : (
            <div className="space-y-3">
              {suggestions.map((s) => {
                const profile = AGENT_PROFILE[s.agent_id]
                const statusInfo = STATUS_LABEL[s.status] || STATUS_LABEL.pending
                const catLabel = CATEGORY_LABEL[s.category] || s.category
                const isExpanded = selected?.id === s.id

                return (
                  <div
                    key={s.id}
                    className={`rounded-xl border transition-colors cursor-pointer
                      ${isExpanded
                        ? 'border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-950/20'
                        : 'border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700'
                      }`}
                    onClick={() => setSelected(isExpanded ? null : s)}
                  >
                    {/* 요약 행 */}
                    <div className="flex items-center gap-3 px-4 py-3">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300 min-w-[60px]">
                        {profile?.character || s.agent_id}
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${statusInfo.color}`}>
                        {statusInfo.text}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500">
                        {catLabel}
                      </span>
                      <span className="flex-1 text-sm text-gray-600 dark:text-gray-400 truncate">
                        {s.title}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        {new Date(s.created_at).toLocaleDateString('ko-KR')}
                      </span>
                    </div>

                    {/* 상세 (펼침) */}
                    {isExpanded && (
                      <div className="px-4 pb-4 border-t border-gray-100 dark:border-gray-800 pt-3">
                        <p className="text-sm text-gray-600 dark:text-gray-400 mb-3 whitespace-pre-wrap">
                          {s.content}
                        </p>
                        <div className="flex gap-2">
                          {s.status === 'pending' && (
                            <>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleStatusChange(s.id, 'accepted') }}
                                className="text-xs px-3 py-1 rounded-lg bg-green-500 text-white
                                  hover:bg-green-600 cursor-pointer transition-colors"
                              >
                                수용
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleStatusChange(s.id, 'rejected') }}
                                className="text-xs px-3 py-1 rounded-lg bg-red-500 text-white
                                  hover:bg-red-600 cursor-pointer transition-colors"
                              >
                                반려
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
          )}
        </div>
      </div>
    </div>
  )
}
