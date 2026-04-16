// Gate Inbox — 승인 대기 중인 Gate 전체 목록
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MatIcon } from './icons'

interface PendingGate {
  job_id: string
  job_title: string
  job_spec_id: string
  gate_id: string
  gate_prompt: string
  opened_at: string
}

async function fetchPendingGates(): Promise<PendingGate[]> {
  const res = await fetch('/api/jobs/gates/pending')
  if (!res.ok) throw new Error('Gate 목록 로드 실패')
  return res.json()
}

const SPEC_ICONS: Record<string, string> = {
  research: 'search',
  planning: 'account_tree',
  design_direction: 'palette',
  review: 'rate_review',
  publishing: 'code',
}

function timeAgo(ts: string): string {
  if (!ts) return ''
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60) return `${Math.round(diff)}초 전`
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`
  return `${Math.floor(diff / 86400)}일 전`
}

function GateItem({ gate }: { gate: PendingGate }) {
  const qc = useQueryClient()
  const [feedback, setFeedback] = useState('')
  const [expanded, setExpanded] = useState(false)

  const decide = useMutation({
    mutationFn: async (decision: 'approved' | 'rejected' | 'revised') => {
      const res = await fetch(`/api/jobs/${gate.job_id}/gates/${gate.gate_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, feedback }),
      })
      if (!res.ok) throw new Error('결정 실패')
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-gates'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['job', gate.job_id] })
    },
  })

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-yellow-200 dark:border-yellow-700/40 overflow-hidden">
      {/* 상단 정보 */}
      <div className="px-4 py-3 bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-100 dark:border-yellow-700/30">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-yellow-100 dark:bg-yellow-800/30 flex items-center justify-center">
            <MatIcon name={SPEC_ICONS[gate.job_spec_id] || 'work'} className="text-[16px] text-yellow-600 dark:text-yellow-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{gate.job_title}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] text-yellow-600 dark:text-yellow-500 font-medium">{gate.gate_id}</span>
              <span className="text-[10px] text-gray-400">·</span>
              <span className="text-[10px] text-gray-400">{timeAgo(gate.opened_at)}</span>
            </div>
          </div>
          <MatIcon name="pending" className="text-[20px] text-yellow-500" />
        </div>
      </div>

      {/* Gate 프롬프트 */}
      <div className="px-4 py-3">
        <p className="text-sm text-gray-700 dark:text-gray-300">{gate.gate_prompt}</p>

        {/* 피드백 입력 */}
        {expanded && (
          <textarea
            rows={3}
            value={feedback}
            onChange={e => setFeedback(e.target.value)}
            placeholder="피드백 내용 (수정 요청 또는 거절 이유)"
            className="w-full mt-3 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
              bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none
              focus:outline-none focus:ring-2 focus:ring-yellow-500/50"
          />
        )}

        {/* 버튼 */}
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => decide.mutate('approved')}
            disabled={decide.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white
              bg-green-600 hover:bg-green-700 rounded-xl transition-colors cursor-pointer
              disabled:opacity-50"
          >
            <MatIcon name="check" className="text-[16px]" />
            승인
          </button>

          <button
            onClick={() => {
              if (!expanded) { setExpanded(true); return }
              if (feedback.trim()) decide.mutate('revised')
            }}
            disabled={decide.isPending}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-xl transition-colors cursor-pointer disabled:opacity-50
              ${expanded && feedback.trim()
                ? 'text-white bg-blue-600 hover:bg-blue-700'
                : 'text-yellow-700 dark:text-yellow-400 bg-yellow-100 dark:bg-yellow-900/30 hover:bg-yellow-200 dark:hover:bg-yellow-900/50'
              }`}
          >
            <MatIcon name="edit" className="text-[16px]" />
            {expanded && feedback.trim() ? '수정 요청' : '피드백 작성'}
          </button>

          <button
            onClick={() => decide.mutate('rejected')}
            disabled={decide.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
              text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20
              hover:bg-red-100 dark:hover:bg-red-900/30 rounded-xl transition-colors
              cursor-pointer disabled:opacity-50"
          >
            <MatIcon name="close" className="text-[16px]" />
            거절
          </button>
        </div>

        {decide.isError && (
          <p className="text-xs text-red-500 mt-2">
            {decide.error instanceof Error ? decide.error.message : '오류 발생'}
          </p>
        )}
        {decide.isSuccess && (
          <p className="text-xs text-green-500 mt-2">처리 완료</p>
        )}
      </div>
    </div>
  )
}

export function GateInbox() {
  const { data: gates = [], isLoading, error } = useQuery({
    queryKey: ['pending-gates'],
    queryFn: fetchPendingGates,
    refetchInterval: 5000,
  })

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50 dark:bg-gray-950">
      {/* 헤더 */}
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center">
            <MatIcon name="pending_actions" className="text-[18px] text-yellow-600 dark:text-yellow-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Gate Inbox</h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {isLoading ? '로딩 중...' : `${gates.length}개 승인 대기 중`}
            </p>
          </div>
        </div>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-y-auto p-5">
        {isLoading && (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <MatIcon name="hourglass_empty" className="text-[40px]" />
          </div>
        )}

        {!isLoading && gates.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-2xl bg-green-100 dark:bg-green-900/20 flex items-center justify-center mb-4">
              <MatIcon name="check_circle" className="text-[32px] text-green-500" />
            </div>
            <p className="text-base font-semibold text-gray-700 dark:text-gray-300">승인 대기 없음</p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">모든 Gate가 처리되었습니다</p>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 p-4 bg-red-50 dark:bg-red-900/20 rounded-xl text-red-600 dark:text-red-400">
            <MatIcon name="error" className="text-[18px]" />
            <p className="text-sm">Gate 목록을 불러오지 못했습니다</p>
          </div>
        )}

        <div className="space-y-4 max-w-2xl">
          {gates.map(gate => (
            <GateItem key={`${gate.job_id}-${gate.gate_id}`} gate={gate} />
          ))}
        </div>
      </div>
    </div>
  )
}
