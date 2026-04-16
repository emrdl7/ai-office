// 새 Job 제출 다이얼로그
import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { JobSpec } from '../types'
import { MatIcon } from './icons'

async function fetchSpecs(): Promise<JobSpec[]> {
  const res = await fetch('/api/jobs/specs')
  if (!res.ok) throw new Error('스펙 로드 실패')
  return res.json()
}

const SPEC_ICONS: Record<string, string> = {
  research: 'search',
  planning: 'account_tree',
  design_direction: 'palette',
  review: 'rate_review',
  publishing: 'code',
}

const FIELD_PLACEHOLDERS: Record<string, string> = {
  topic: '예: SaaS 온보딩 UX 트렌드',
  scope: 'competitor | trend | usability',
  depth: 'light | standard | deep',
  product: '예: B2B SaaS 대시보드 서비스',
  goals: '예: 신규 사용자 온보딩 완료율 +20%',
  user_segments: '예: 비개발자 팀장, 20-40대',
  constraints: '예: 모바일 우선, 다국어 지원',
  project: '예: 메인 랜딩 페이지 리디자인',
  artifact: '리뷰할 URL, 파일 경로, 또는 내용 직접 입력',
  review_type: 'design | planning | code | accessibility',
  screen: '예: 상품 상세 페이지',
  spec: '디자인 브리프 내용 또는 Figma 링크',
  notes: '선택 사항',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

interface SourceJob {
  id: string
  title: string
  specId: string
  artifacts: Record<string, string>
}

interface InitialValues {
  specId: string
  title: string
  fields: Record<string, string>
  sourceJob?: SourceJob   // 이전 Job 체이닝
}

export function NewJobDialog({
  onClose,
  initialValues,
}: {
  onClose: () => void
  initialValues?: InitialValues
}) {
  const qc = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedSpec, setSelectedSpec] = useState<JobSpec | null>(null)
  const [title, setTitle] = useState(initialValues?.title ?? '')
  const [fields, setFields] = useState<Record<string, string>>(initialValues?.fields ?? {})
  const [attachedFiles, setAttachedFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)

  const { data: specs = [] } = useQuery({
    queryKey: ['job-specs'],
    queryFn: fetchSpecs,
  })

  // specs 로드 완료 후 initialValues.specId 매칭
  useEffect(() => {
    if (initialValues?.specId && specs.length > 0 && !selectedSpec) {
      const matched = specs.find(s => s.id === initialValues.specId)
      if (matched) setSelectedSpec(matched)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specs])

  const submit = useMutation({
    mutationFn: async () => {
      if (!selectedSpec) return
      const fd = new FormData()
      fd.append('spec_id', selectedSpec.id)
      fd.append('title', title)
      fd.append('input', JSON.stringify(fields))
      if (initialValues?.sourceJob?.id) {
        fd.append('source_job_id', initialValues.sourceJob.id)
      }
      for (const f of attachedFiles) {
        fd.append('files', f)
      }
      const res = await fetch('/api/jobs', { method: 'POST', body: fd })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '제출 실패')
      }
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      onClose()
    },
  })

  const requiredFields = selectedSpec?.input_fields.filter(f => f !== 'notes') ?? []
  const allFields = selectedSpec?.input_fields ?? []
  const canSubmit = selectedSpec && requiredFields.every(f => fields[f]?.trim())

  function addFiles(newFiles: FileList | null) {
    if (!newFiles) return
    setAttachedFiles(prev => {
      const existing = new Set(prev.map(f => f.name))
      const toAdd = Array.from(newFiles).filter(f => !existing.has(f.name))
      return [...prev, ...toAdd]
    })
  }

  function removeFile(name: string) {
    setAttachedFiles(prev => prev.filter(f => f.name !== name))
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            {initialValues ? '기존 Job 기반으로 새 Job 시작' : '새 Job 시작'}
          </h2>
          <button onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
            <MatIcon name="close" className="text-[18px]" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Step 1: Job 유형 선택 */}
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Job 유형
            </p>
            <div className="grid grid-cols-1 gap-2">
              {specs.map(spec => (
                <button
                  key={spec.id}
                  onClick={() => { setSelectedSpec(spec); setFields({}) }}
                  className={`text-left px-3 py-2.5 rounded-xl border transition-all cursor-pointer
                    ${selectedSpec?.id === spec.id
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-blue-400 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                >
                  <div className="flex items-center gap-2.5">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center
                      ${selectedSpec?.id === spec.id ? 'bg-blue-500 text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'}`}>
                      <MatIcon name={SPEC_ICONS[spec.id] || 'work'} className="text-[16px]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium ${selectedSpec?.id === spec.id ? 'text-blue-600 dark:text-blue-400' : 'text-gray-900 dark:text-gray-100'}`}>
                        {spec.title}
                      </p>
                      <p className="text-[11px] text-gray-500 dark:text-gray-400 truncate">{spec.description}</p>
                    </div>
                    <span className="text-[10px] text-gray-400 shrink-0">{spec.step_count}단계</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Step 2: 입력 폼 */}
          {selectedSpec && (
            <div className="space-y-3">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                입력값
              </p>

              <div>
                <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                  제목 <span className="text-gray-400">(선택)</span>
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder={`예: ${selectedSpec.title} — 프로젝트명`}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                    focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500"
                />
              </div>

              {allFields.map(field => (
                <div key={field}>
                  <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                    {field}
                    {!requiredFields.includes(field) && (
                      <span className="text-gray-400 ml-1">(선택)</span>
                    )}
                    {requiredFields.includes(field) && (
                      <span className="text-red-400 ml-1">*</span>
                    )}
                  </label>
                  <textarea
                    rows={field === 'spec' || field === 'artifact' ? 4 : 2}
                    value={fields[field] || ''}
                    onChange={e => setFields(prev => ({ ...prev, [field]: e.target.value }))}
                    placeholder={FIELD_PLACEHOLDERS[field] || ''}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                      bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                      focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500
                      resize-none"
                  />
                </div>
              ))}
            </div>
          )}

          {/* 이전 Job 산출물 참조 (체이닝) */}
          {selectedSpec && initialValues?.sourceJob && (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                이전 Job 산출물 <span className="font-normal normal-case text-gray-400">(자동 참조)</span>
              </p>
              <div className="px-3 py-2.5 bg-purple-50 dark:bg-purple-900/20 rounded-xl border border-purple-200 dark:border-purple-700/40">
                <div className="flex items-center gap-2">
                  <MatIcon name="link" className="text-[16px] text-purple-500 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-purple-700 dark:text-purple-300 truncate">
                      {initialValues.sourceJob.title}
                    </p>
                    <p className="text-[10px] text-purple-500 dark:text-purple-400">
                      {initialValues.sourceJob.specId} ·{' '}
                      {Object.keys(initialValues.sourceJob.artifacts).filter(k => initialValues.sourceJob!.artifacts[k]?.length > 10).length}개 산출물 포함
                    </p>
                  </div>
                  <MatIcon name="check_circle" className="text-[14px] text-purple-400 shrink-0" />
                </div>
              </div>
            </div>
          )}

          {/* 파일 첨부 */}
          {selectedSpec && (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                참조 자료 첨부 <span className="font-normal normal-case text-gray-400">(선택)</span>
              </p>

              {/* 드롭존 */}
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`flex flex-col items-center justify-center gap-1.5 px-4 py-5 rounded-xl border-2 border-dashed
                  cursor-pointer transition-all
                  ${dragOver
                    ? 'border-blue-400 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:border-blue-400 hover:bg-gray-50 dark:hover:bg-gray-800/50'
                  }`}
              >
                <MatIcon name="upload_file" className="text-[24px] text-gray-400" />
                <p className="text-xs text-gray-500 dark:text-gray-400 text-center">
                  파일을 드래그하거나 클릭해 첨부
                </p>
                <p className="text-[10px] text-gray-400">
                  PDF, Word, Excel, 이미지, 텍스트 등 · 최대 50MB
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={e => addFiles(e.target.files)}
              />

              {/* 첨부된 파일 목록 */}
              {attachedFiles.length > 0 && (
                <div className="mt-2 space-y-1.5">
                  {attachedFiles.map(f => (
                    <div key={f.name}
                      className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800 rounded-lg">
                      <MatIcon name="attach_file" className="text-[14px] text-gray-400 shrink-0" />
                      <span className="flex-1 text-xs text-gray-700 dark:text-gray-300 truncate min-w-0">
                        {f.name}
                      </span>
                      <span className="text-[10px] text-gray-400 shrink-0">{formatBytes(f.size)}</span>
                      <button
                        onClick={e => { e.stopPropagation(); removeFile(f.name) }}
                        className="p-0.5 rounded text-gray-400 hover:text-red-500 transition-colors cursor-pointer">
                        <MatIcon name="close" className="text-[13px]" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {submit.isError && (
            <p className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
              {submit.error instanceof Error ? submit.error.message : '오류 발생'}
            </p>
          )}
        </div>

        {/* 하단 버튼 */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-200 dark:border-gray-800">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors cursor-pointer">
            취소
          </button>
          <button
            onClick={() => submit.mutate()}
            disabled={!canSubmit || submit.isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700
              rounded-lg transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submit.isPending ? '제출 중...' : attachedFiles.length > 0
              ? `Job 시작 (파일 ${attachedFiles.length}개)`
              : 'Job 시작'}
          </button>
        </div>
      </div>
    </div>
  )
}
