// Playbook 런처 다이얼로그 — Playbook 선택 + 입력값 → 실행
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MatIcon } from './icons'

interface PlaybookStep {
  spec_id: string
  title: string
}

interface Playbook {
  id: string
  title: string
  description: string
  input_fields: string[]
  step_count: number
  steps: PlaybookStep[]
}

async function fetchPlaybooks(): Promise<Playbook[]> {
  const res = await fetch('/api/playbooks')
  if (!res.ok) throw new Error('Playbook 목록 로드 실패')
  return res.json()
}

const SPEC_ICONS: Record<string, string> = {
  research: 'search',
  planning: 'account_tree',
  design_direction: 'palette',
  review: 'rate_review',
  publishing: 'code',
}

export function PlaybookDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Playbook | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})

  const { data: playbooks = [], isLoading } = useQuery({
    queryKey: ['playbooks'],
    queryFn: fetchPlaybooks,
  })

  const run = useMutation({
    mutationFn: async () => {
      if (!selected) return
      const res = await fetch(`/api/playbooks/${selected.id}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: fields }),
      })
      if (!res.ok) throw new Error('Playbook 시작 실패')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      onClose()
    },
  })

  const canSubmit = selected && selected.input_fields.every(f => fields[f]?.trim())

  return (
    <div
      className="fixed inset-0 z-50 flex items-end md:items-center justify-center md:p-4 bg-black/50"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white dark:bg-gray-900
        w-full md:max-w-lg
        rounded-t-2xl md:rounded-2xl shadow-2xl
        border border-gray-200 dark:border-gray-700
        flex flex-col max-h-[90dvh]
        pb-[env(safe-area-inset-bottom)]">

        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <MatIcon name="play_circle" className="text-[20px] text-purple-500" />
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Playbook 실행</h2>
          </div>
          <button onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white
              hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
            <MatIcon name="close" className="text-[18px]" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {isLoading && (
            <p className="text-sm text-gray-400 text-center py-6">로딩 중...</p>
          )}

          {/* Playbook 선택 */}
          {!isLoading && (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                Playbook 선택
              </p>
              <div className="space-y-2">
                {playbooks.map(pb => (
                  <button
                    key={pb.id}
                    onClick={() => { setSelected(pb); setFields({}) }}
                    className={`w-full text-left p-3 rounded-xl border transition-all cursor-pointer
                      ${selected?.id === pb.id
                        ? 'border-purple-400 bg-purple-50 dark:bg-purple-900/20'
                        : 'border-gray-200 dark:border-gray-700 hover:border-purple-300 dark:hover:border-purple-700'
                      }`}
                  >
                    <div className="flex items-start gap-2.5">
                      <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5
                        ${selected?.id === pb.id
                          ? 'bg-purple-500 text-white'
                          : 'bg-gray-100 dark:bg-gray-800 text-gray-500'}`}>
                        <MatIcon name="play_circle" className="text-[14px]" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium
                          ${selected?.id === pb.id ? 'text-purple-700 dark:text-purple-300' : 'text-gray-900 dark:text-gray-100'}`}>
                          {pb.title}
                        </p>
                        <p className="text-[11px] text-gray-500 mt-0.5">{pb.description}</p>
                        {/* Step 체인 표시 */}
                        <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                          {pb.steps.map((step, idx) => (
                            <span key={idx} className="flex items-center gap-1">
                              <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full
                                bg-gray-100 dark:bg-gray-800 text-[9px] text-gray-600 dark:text-gray-400">
                                <MatIcon name={SPEC_ICONS[step.spec_id] || 'work'} className="text-[10px]" />
                                {step.spec_id}
                              </span>
                              {idx < pb.steps.length - 1 && (
                                <MatIcon name="arrow_forward" className="text-[10px] text-gray-400" />
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}

                {playbooks.length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-4">
                    등록된 Playbook이 없습니다
                  </p>
                )}
              </div>
            </div>
          )}

          {/* 입력 필드 */}
          {selected && selected.input_fields.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                입력값
              </p>
              <div className="space-y-3">
                {selected.input_fields.map(f => (
                  <div key={f}>
                    <label className="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">
                      {f}
                      <span className="text-red-400 ml-0.5">*</span>
                    </label>
                    <input
                      type="text"
                      value={fields[f] ?? ''}
                      onChange={e => setFields(prev => ({ ...prev, [f]: e.target.value }))}
                      placeholder={`${f} 입력`}
                      className="w-full px-3 py-2 text-base md:text-sm rounded-lg border border-gray-200 dark:border-gray-700
                        bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                        focus:outline-none focus:ring-2 focus:ring-purple-400/50 focus:border-purple-400"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 푸터 */}
        <div className="px-5 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-2">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900
              dark:hover:text-white transition-colors cursor-pointer">
            취소
          </button>
          <button
            onClick={() => run.mutate()}
            disabled={!canSubmit || run.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white
              bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed
              rounded-lg transition-colors cursor-pointer"
          >
            <MatIcon name="play_arrow" className="text-[16px]" />
            {run.isPending ? '시작 중...' : 'Playbook 실행'}
          </button>
        </div>

        {run.isError && (
          <p className="px-5 pb-3 text-xs text-red-500">
            {run.error instanceof Error ? run.error.message : '오류가 발생했습니다'}
          </p>
        )}
      </div>
    </div>
  )
}
