// Gate Inbox — 승인 대기 중인 Gate 전체 목록
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { MatIcon } from './icons'

interface PendingGate {
  job_id: string
  job_title: string
  job_spec_id: string
  gate_id: string
  gate_prompt: string
  after_step: string
  step_output: string
  step_model: string
  step_revised: number
  step_revision_feedback: string
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

function MarkdownViewer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none
      prose-headings:font-semibold prose-headings:text-gray-900 dark:prose-headings:text-gray-100
      prose-p:text-gray-700 dark:prose-p:text-gray-300
      prose-code:text-pink-600 dark:prose-code:text-pink-400
      prose-pre:bg-gray-100 dark:prose-pre:bg-gray-800
      prose-table:text-xs prose-th:bg-gray-100 dark:prose-th:bg-gray-800
      prose-a:text-blue-500">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}

function GateItem({ gate }: { gate: PendingGate }) {
  const qc = useQueryClient()
  const [feedback, setFeedback] = useState('')
  const [outputOpen, setOutputOpen] = useState(true) // 기본 펼침

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
      setFeedback('')
    },
  })

  const isCode = gate.step_output?.includes('```html') || gate.step_output?.includes('```css')

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">

      {/* 헤더 */}
      <div className="px-4 py-3 bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-100 dark:border-yellow-700/30">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-yellow-100 dark:bg-yellow-800/30 flex items-center justify-center shrink-0">
            <MatIcon name={SPEC_ICONS[gate.job_spec_id] || 'work'} className="text-[16px] text-yellow-600 dark:text-yellow-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{gate.job_title}</p>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <span className="text-[10px] text-yellow-600 dark:text-yellow-500 font-medium">{gate.gate_id}</span>
              {gate.after_step && (
                <>
                  <span className="text-[10px] text-gray-400">·</span>
                  <span className="text-[10px] text-gray-500 dark:text-gray-400">{gate.after_step} 검토</span>
                </>
              )}
              <span className="text-[10px] text-gray-400">·</span>
              <span className="text-[10px] text-gray-400">{timeAgo(gate.opened_at)}</span>
              {gate.step_revised > 0 && (
                <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full
                  bg-orange-100 dark:bg-orange-900/40 text-orange-600 dark:text-orange-400">
                  수정됨 ×{gate.step_revised}
                </span>
              )}
            </div>
          </div>
          <MatIcon name="pending" className="text-[20px] text-yellow-500 shrink-0" />
        </div>
      </div>

      {/* 검토 질문 */}
      <div className="px-4 pt-3">
        <div className="flex items-start gap-2 mb-3">
          <MatIcon name="help_outline" className="text-[15px] text-gray-400 mt-0.5 shrink-0" />
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">{gate.gate_prompt}</p>
        </div>

        {/* 수정 피드백 표시 */}
        {gate.step_revised > 0 && gate.step_revision_feedback && (
          <div className="mb-3 px-3 py-2 bg-orange-50 dark:bg-orange-900/20 rounded-lg border border-orange-200 dark:border-orange-700/30">
            <p className="text-[10px] font-medium text-orange-600 dark:text-orange-400 mb-0.5">이전 수정 요청</p>
            <p className="text-xs text-orange-700 dark:text-orange-300 italic">"{gate.step_revision_feedback}"</p>
          </div>
        )}
      </div>

      {/* 검토할 산출물 */}
      {gate.step_output ? (
        <div className="mx-4 mb-3 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <button
            onClick={() => setOutputOpen(!outputOpen)}
            className="w-full flex items-center justify-between px-3 py-2
              bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-750
              transition-colors cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <MatIcon name="article" className="text-[14px] text-gray-500" />
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                산출물 — {gate.after_step}
              </span>
              {gate.step_model && (
                <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full
                  ${gate.step_model.includes('gemini') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                    : gate.step_model.includes('opus') ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-500'
                  }`}>
                  {gate.step_model.replace('claude-', '').replace('-4-5-20251001', '').replace('-4-6', '')}
                </span>
              )}
              <span className="text-[10px] text-gray-400">
                {(gate.step_output.length / 1000).toFixed(1)}k자
              </span>
            </div>
            <MatIcon
              name={outputOpen ? 'expand_less' : 'expand_more'}
              className="text-[16px] text-gray-400"
            />
          </button>

          {outputOpen && (
            <div className="px-3 py-3 max-h-[50vh] overflow-y-auto border-t border-gray-200 dark:border-gray-700">
              {isCode ? (
                <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
                  {gate.step_output}
                </pre>
              ) : (
                <MarkdownViewer content={gate.step_output} />
              )}
            </div>
          )}
        </div>
      ) : gate.after_step ? (
        <div className="mx-4 mb-3 px-3 py-2.5 bg-gray-50 dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <p className="text-xs text-gray-400 text-center">산출물 로딩 중...</p>
        </div>
      ) : null}

      {/* 피드백 + 액션 */}
      <div className="px-4 pb-4 space-y-2.5">
        <textarea
          rows={2}
          value={feedback}
          onChange={e => setFeedback(e.target.value)}
          placeholder="수정 요청 시 피드백을 입력하세요 (없으면 비워두고 승인/거절)"
          className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
            bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none
            focus:outline-none focus:ring-2 focus:ring-yellow-400/50"
        />

        <div className="flex gap-2">
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
            onClick={() => decide.mutate('revised')}
            disabled={decide.isPending || !feedback.trim()}
            title={!feedback.trim() ? '피드백을 먼저 입력하세요' : ''}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
              text-blue-700 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30
              hover:bg-blue-200 dark:hover:bg-blue-900/50 rounded-xl transition-colors
              cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <MatIcon name="refresh" className="text-[16px]" />
            수정 후 재검토
          </button>

          <button
            onClick={() => decide.mutate('rejected')}
            disabled={decide.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
              text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20
              hover:bg-red-100 dark:hover:bg-red-900/30 rounded-xl transition-colors
              cursor-pointer disabled:opacity-50"
          >
            <MatIcon name="cancel" className="text-[16px]" />
            거절
          </button>
        </div>

        {decide.isError && (
          <p className="text-xs text-red-500">
            {decide.error instanceof Error ? decide.error.message : '오류 발생'}
          </p>
        )}
        {decide.isSuccess && (
          <p className="text-xs text-blue-500">수정 요청 완료 — 에이전트가 재작업 중입니다</p>
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
      <div className="px-4 md:px-5 h-[60px] shrink-0 flex items-center border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
            <MatIcon name="rule" className="text-[18px] text-amber-600 dark:text-amber-400" />
          </div>
          <div className="leading-tight">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">검토 수신함</h2>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              {isLoading ? '로딩 중...' : `${gates.length}개 검토 대기 중`}
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
            <p className="text-base font-semibold text-gray-700 dark:text-gray-300">검토 대기 없음</p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">모든 게이트가 처리되었습니다</p>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 p-4 bg-red-50 dark:bg-red-900/20 rounded-xl text-red-600 dark:text-red-400">
            <MatIcon name="error" className="text-[18px]" />
            <p className="text-sm">검토 목록을 불러오지 못했습니다</p>
          </div>
        )}

        <div className="space-y-5 max-w-2xl">
          {gates.map(gate => (
            <GateItem key={`${gate.job_id}-${gate.gate_id}`} gate={gate} />
          ))}
        </div>
      </div>
    </div>
  )
}
