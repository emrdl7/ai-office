// 페르소나 드리프트 패널 — /api/team/persona-drift 점수 표시 (P5-3)
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { MatIcon } from './icons'

interface AgentDrift {
  agent: string
  score: number | null
  reason: string
  sample_count: number
}

interface PersonaDriftData {
  computed_at: string
  period_hours: number
  agents: AgentDrift[]
  drift_count: number
}

const AGENT_LABEL: Record<string, string> = {
  teamlead: '잡스',
  planner: '드러커',
  designer: '아이브',
  developer: '튜링',
  qa: '데밍',
}

function scoreColor(score: number | null): string {
  if (score === null) return 'text-gray-400'
  if (score >= 8) return 'text-green-500'
  if (score >= 6) return 'text-blue-500'
  if (score >= 4) return 'text-yellow-500'
  return 'text-red-500'
}

function scoreBg(score: number | null): string {
  if (score === null) return 'bg-gray-100 dark:bg-gray-800'
  if (score >= 8) return 'bg-green-50 dark:bg-green-900/20'
  if (score >= 6) return 'bg-blue-50 dark:bg-blue-900/20'
  if (score >= 4) return 'bg-yellow-50 dark:bg-yellow-900/20'
  return 'bg-red-50 dark:bg-red-900/20'
}

export function PersonaDriftPanel({ onClose }: { onClose: () => void }) {
  const [hours, setHours] = useState(48)

  const { data, isLoading } = useQuery<PersonaDriftData>({
    queryKey: ['persona-drift', hours],
    queryFn: async () => (await fetch(`/api/team/persona-drift?hours=${hours}`)).json(),
    refetchInterval: 60_000,
  })

  const panel = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-sm
        border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-4 py-3
          border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <span className="text-base">🎭</span>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">페르소나 드리프트</h2>
            {data && data.drift_count > 0 && (
              <span className="px-1.5 py-0.5 text-[10px] font-bold bg-red-100 dark:bg-red-900/40
                text-red-600 dark:text-red-300 rounded-full">
                {data.drift_count}건 이탈
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <select
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              className="text-xs px-2 py-1 rounded border border-gray-200 dark:border-gray-600
                bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 cursor-pointer"
            >
              <option value={24}>24시간</option>
              <option value={48}>48시간</option>
              <option value={168}>7일</option>
            </select>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 cursor-pointer"
              aria-label="닫기"
            >
              <MatIcon name="close" className="text-[16px]" />
            </button>
          </div>
        </div>

        {/* 본문 */}
        <div className="p-4 space-y-2">
          {isLoading ? (
            <p className="text-center text-sm text-gray-400 py-6">분석 중...</p>
          ) : !data ? (
            <p className="text-center text-sm text-gray-400 py-6">데이터 없음</p>
          ) : (
            <>
              {data.agents.map((a) => (
                <div
                  key={a.agent}
                  className={`rounded-xl px-3 py-2.5 ${scoreBg(a.score)}`}
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
                      {AGENT_LABEL[a.agent] ?? a.agent}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-gray-400">{a.sample_count}건 샘플</span>
                      <span className={`text-base font-bold ${scoreColor(a.score)}`}>
                        {a.score !== null ? `${a.score}/10` : '—'}
                      </span>
                    </div>
                  </div>
                  <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-relaxed">
                    {a.reason}
                  </p>
                  {a.score !== null && a.score < 6 && (
                    <ScoreBar score={a.score} />
                  )}
                </div>
              ))}

              <p className="text-[10px] text-gray-400 text-right pt-1">
                마지막 분석 {data.computed_at ? new Date(data.computed_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '—'}
                &nbsp;· {hours}시간 기준
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )

  return createPortal(panel, document.body)
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round((score / 10) * 100)
  const barColor = score >= 6 ? 'bg-blue-400' : score >= 4 ? 'bg-yellow-400' : 'bg-red-400'
  return (
    <div className="mt-1.5 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
    </div>
  )
}
