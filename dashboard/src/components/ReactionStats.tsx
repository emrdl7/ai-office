// 리액션 통계 패널 — 에이전트별 받은 이모지 집계
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { displayName, AGENT_IDS } from '../config/team'
import { MatIcon } from './icons'

interface ReactionStats {
  per_agent: Record<string, Record<string, number>>
  totals: Record<string, number>
}

export function ReactionStatsPanel({ onClose }: { onClose: () => void }) {
  const { data, isLoading } = useQuery<ReactionStats>({
    queryKey: ['reaction-stats'],
    queryFn: async () => (await fetch('/api/reactions/stats')).json(),
    refetchInterval: 10_000,
  })

  const perAgent = data?.per_agent ?? {}
  const totals = data?.totals ?? {}

  // Portal로 document.body에 렌더링 — 부모의 transform context 회피
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-10">
      <div className="absolute inset-0 bg-black/60 dark:bg-black/70" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white dark:bg-gray-800
        border border-gray-200 dark:border-gray-700
        rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4
          border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            리액션 통계 (최근 30일)
          </h2>
          <button onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600
              dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
              cursor-pointer transition-colors"
            aria-label="닫기">
            <MatIcon name="close" className="text-[20px]" />
          </button>
        </div>

        <div className="p-5 max-h-[70vh] overflow-y-auto">
          {isLoading && <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">로딩 중...</p>}

          {!isLoading && Object.keys(totals).length === 0 && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-8">아직 리액션이 없습니다</p>
          )}

          {!isLoading && Object.keys(totals).length > 0 && (
            <>
              {/* 전체 합계 */}
              <div className="mb-5">
                <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  전체 합계
                </h3>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(totals)
                    .sort((a, b) => b[1] - a[1])
                    .map(([emoji, count]) => (
                      <span key={emoji}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg
                          bg-gray-100 dark:bg-gray-700 text-sm text-gray-800 dark:text-gray-100">
                        <span>{emoji}</span>
                        <span className="font-medium">{count}</span>
                      </span>
                    ))}
                </div>
              </div>

              {/* 에이전트별 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  에이전트별
                </h3>
                <div className="space-y-2">
                  {AGENT_IDS.map((agentId) => {
                    const bucket = perAgent[agentId] ?? {}
                    const sum = Object.values(bucket).reduce((a, b) => a + b, 0)
                    return (
                      <div key={agentId}
                        className="flex items-center justify-between px-3 py-2.5 rounded-xl
                          bg-gray-50 dark:bg-gray-900/60
                          border border-transparent dark:border-gray-700/50">
                        <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                          {displayName(agentId)}
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {sum === 0 ? (
                            <span className="text-xs text-gray-400 dark:text-gray-500">없음</span>
                          ) : (
                            Object.entries(bucket)
                              .sort((a, b) => b[1] - a[1])
                              .map(([emoji, count]) => (
                                <span key={emoji} className="text-xs px-1.5 py-0.5 rounded
                                  bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100">
                                  {emoji} {count}
                                </span>
                              ))
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
