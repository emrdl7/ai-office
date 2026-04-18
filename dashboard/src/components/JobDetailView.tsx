// Job 상세 뷰 — 스텝 타임라인 + 출력물 뷰어 + Gate 컨트롤 + 아티팩트
import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Job, JobStep } from '../types'
import { MatIcon } from './icons'

// SVG 인라인 렌더러
function SvgArtifact({ content }: { content: string }) {
  // SVG 태그 추출 (LLM이 마크다운 코드블록으로 감쌌을 수 있음)
  const svgMatch = content.match(/<svg[\s\S]*?<\/svg>/i)
  const svgContent = svgMatch ? svgMatch[0] : content
  return (
    <div
      className="overflow-x-auto"
      dangerouslySetInnerHTML={{ __html: svgContent }}
    />
  )
}

// 이미지 갤러리 (mobile/tablet/desktop 3장 등)
function ImageGalleryArtifact({ content }: { content: string }) {
  // content는 JSON 배열 or 개행 구분 경로 목록
  let paths: string[] = []
  try {
    const parsed = JSON.parse(content)
    if (Array.isArray(parsed)) paths = parsed.map(String)
  } catch {
    paths = content.split('\n').map(s => s.trim()).filter(Boolean)
  }

  if (!paths.length) {
    return <p className="text-xs text-gray-400">이미지 없음</p>
  }

  const labels = ['모바일', '태블릿', '데스크톱']
  return (
    <div className="flex gap-3 overflow-x-auto pb-1">
      {paths.map((p, i) => (
        <div key={i} className="flex-shrink-0">
          <p className="text-[10px] text-gray-400 mb-1">{labels[i] ?? `#${i + 1}`}</p>
          <img
            src={p.startsWith('/') ? p : `/api/files/${encodeURIComponent(p)}`}
            alt={labels[i] ?? `screenshot-${i}`}
            className="rounded-lg border border-gray-200 dark:border-gray-700 max-h-48 object-contain"
          />
        </div>
      ))}
    </div>
  )
}

// Mermaid 다이어그램 렌더러 (lazy load)
function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let cancelled = false
    import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'loose' })
      const id = `mermaid-${Math.random().toString(36).slice(2)}`
      mermaid.render(id, code).then(({ svg }) => {
        if (!cancelled && ref.current) ref.current.innerHTML = svg
      }).catch(() => { if (!cancelled) setError(true) })
    })
    return () => { cancelled = true }
  }, [code])
  if (error) return <pre className="text-xs text-red-400">{code}</pre>
  return <div ref={ref} className="overflow-x-auto py-2" />
}

// Vega-Lite 차트 렌더러 (lazy load)
function VegaChart({ spec }: { spec: object }) {
  const ref = useRef<HTMLDivElement>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (!ref.current) return
    import('vega-embed').then(({ default: embed }) => {
      if (!cancelled && ref.current)
        embed(ref.current, spec as never, { actions: false, theme: 'latimes' }).catch(() => {
          if (!cancelled) setError(true)
        })
    }).catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [spec])

  if (error) return (
    <div className="text-xs text-red-400 p-3">차트를 렌더링할 수 없습니다</div>
  )
  return (
    <div ref={ref} className="overflow-x-auto py-2" />
  )
}

// 품질 점수 배지 (Job done 시 상단 표시)
interface ArtifactQualityItem {
  artifact_key: string
  overall: number
  length_chars: number
  heading_count: number
  table_count: number
  list_count: number
  citation_count: number
  code_block_count: number
  readability_score: number
  measured_at: string
}


// HTML iframe 미리보기
const VIEWPORTS = [
  { label: '모바일', width: 375, icon: 'smartphone' },
  { label: '태블릿', width: 768, icon: 'tablet' },
  { label: '데스크톱', width: 1280, icon: 'desktop_windows' },
] as const

function HtmlPreview({ html }: { html: string }) {
  const [vp, setVp] = useState(0)
  const blob = new Blob([html], { type: 'text/html' })
  const src = URL.createObjectURL(blob)
  const { width } = VIEWPORTS[vp]
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        {VIEWPORTS.map((v, i) => (
          <button key={v.label} onClick={() => setVp(i)}
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs transition-colors cursor-pointer
              ${vp === i ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}`}>
            <MatIcon name={v.icon} className="text-[13px]" />
            {v.label}
          </button>
        ))}
        <a href={src} target="_blank" rel="noreferrer"
          className="ml-auto flex items-center gap-1 px-2 py-1 rounded-lg text-xs
            text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
          <MatIcon name="open_in_new" className="text-[13px]" />
          새 탭
        </a>
      </div>
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700 bg-white">
        <iframe src={src} title="HTML 미리보기" sandbox="allow-scripts"
          style={{ width, height: 500, display: 'block', border: 'none' }} />
      </div>
    </div>
  )
}

async function fetchJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`)
  if (!res.ok) throw new Error('Job 로드 실패')
  return res.json()
}

const STATUS_LABEL: Record<string, { text: string; cls: string; icon: string }> = {
  queued:       { text: '대기',      cls: 'bg-gray-500/20 text-gray-400',   icon: 'schedule' },
  running:      { text: '실행 중',   cls: 'bg-blue-500/20 text-blue-400',   icon: 'play_circle' },
  waiting_gate: { text: '게이트 대기', cls: 'bg-yellow-500/20 text-yellow-500', icon: 'pending' },
  done:         { text: '완료',      cls: 'bg-green-500/20 text-green-500', icon: 'check_circle' },
  failed:       { text: '실패',      cls: 'bg-red-500/20 text-red-500',     icon: 'error' },
  cancelled:    { text: '취소됨',    cls: 'bg-gray-500/20 text-gray-500',   icon: 'cancel' },
}

const STEP_STATUS_ICON: Record<string, { icon: string; cls: string }> = {
  queued:  { icon: 'radio_button_unchecked', cls: 'text-gray-400' },
  running: { icon: 'pending',                cls: 'text-blue-400 animate-pulse' },
  done:    { icon: 'check_circle',           cls: 'text-green-500' },
  failed:  { icon: 'cancel',                 cls: 'text-red-500' },
}

function elapsed(start: string, end?: string): string {
  if (!start) return ''
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const sec = Math.round((e - s) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}

// 마크다운 출력 패널 — prose 스타일
function MarkdownViewer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none
      prose-headings:font-semibold prose-headings:text-gray-900 dark:prose-headings:text-gray-100
      prose-p:text-gray-700 dark:prose-p:text-gray-300
      prose-code:text-pink-600 dark:prose-code:text-pink-400
      prose-pre:bg-gray-100 dark:prose-pre:bg-gray-800 prose-pre:overflow-x-auto
      prose-table:text-xs prose-table:mt-5 prose-th:bg-gray-100 dark:prose-th:bg-gray-800 prose-th:pt-2
      prose-a:text-blue-500 [&_table]:block [&_table]:overflow-x-auto">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
}

// 스텝 카드 — 클릭하면 출력 내용 열림
function StepCard({
  step,
  isActive,
  isLast,
}: {
  step: JobStep
  isActive: boolean
  isLast: boolean
}) {
  const isRevised = (step.revised ?? 0) > 0
  // 수정된 step은 기본 펼침
  const [open, setOpen] = useState(isRevised)
  const s = STEP_STATUS_ICON[step.status] ?? STEP_STATUS_ICON.queued
  const hasOutput = step.status === 'done' && step.output
  const hasMermaid = step.output?.includes('```mermaid')
  const hasVega = step.output?.includes('```vega')
  const isHtmlPreview = step.step_id === 'preview_html' && step.output?.includes('```html')
  const isCode = !hasMermaid && !hasVega && !isHtmlPreview && (step.output?.includes('```html') || step.output?.includes('```css'))

  // 다운로드 — step 출력물을 .md 파일로
  const download = useCallback(() => {
    const blob = new Blob([step.output], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${step.step_id}.md`
    a.click()
    URL.revokeObjectURL(url)
  }, [step])

  return (
    <div className={`rounded-xl border transition-all
      ${isRevised
        ? 'border-orange-300 dark:border-orange-700/60 bg-orange-50/30 dark:bg-orange-900/10'
        : isActive
          ? 'border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-900/10'
          : 'border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900'
      }`}>

      {/* 수정 이력 배너 */}
      {isRevised && (
        <div className="flex items-start gap-2 px-3 pt-2.5 pb-0">
          <MatIcon name="history" className="text-[13px] text-orange-500 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <span className="text-[10px] font-semibold text-orange-600 dark:text-orange-400">
              수정 {step.revised}회 — 아래가 최신 결과물입니다
            </span>
            {step.revision_feedback && (
              <p className="text-[10px] text-orange-500 dark:text-orange-500 mt-0.5 italic truncate">
                "{step.revision_feedback}"
              </p>
            )}
          </div>
        </div>
      )}

      {/* 헤더 행 */}
      <button
        onClick={() => hasOutput && setOpen(!open)}
        className={`w-full flex items-center gap-3 px-3 py-2.5
          ${hasOutput ? 'cursor-pointer' : 'cursor-default'}`}
      >
        <div className="flex flex-col items-center self-stretch">
          <MatIcon name={s.icon} className={`text-[20px] ${s.cls} shrink-0`} />
          {!isLast && <div className="w-px flex-1 mt-1 bg-gray-200 dark:bg-gray-700 min-h-[12px]" />}
        </div>

        <div className="flex-1 min-w-0 text-left">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-900 dark:text-gray-100 truncate">
              {step.step_id}
            </span>
            {isRevised && (
              <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full shrink-0
                bg-orange-100 dark:bg-orange-900/40 text-orange-600 dark:text-orange-400">
                수정됨 ×{step.revised}
              </span>
            )}
            {step.model_used && (
              <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full shrink-0
                ${step.model_used.includes('gemini') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                  : step.model_used.includes('opus') ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                  : step.model_used.includes('sonnet') ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                }`}>
                {step.model_used.replace('claude-', '').replace('-4-5-20251001', '').replace('-4-6', '')}
              </span>
            )}
            {step.started_at && (
              <span className="text-[10px] text-gray-400 shrink-0">
                {elapsed(step.started_at, step.finished_at || undefined)}
              </span>
            )}
            {hasOutput && (
              <span className="text-[9px] text-gray-400 shrink-0">
                {(step.output.length / 1000).toFixed(1)}k자
              </span>
            )}
          </div>
          {/* Haiku 결정: 페르소나 · 스킬 · 툴 */}
          {(step.persona || (step.skills && step.skills.length > 0) || (step.tools && step.tools.length > 0)) && (
            <div className="flex flex-wrap items-center gap-1 mt-1">
              {step.persona && (
                <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full
                  bg-violet-100 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400 font-medium">
                  <span className="opacity-60">👤</span>{step.persona}
                </span>
              )}
              {step.skills?.map(s => (
                <span key={s} className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full
                  bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 font-medium">
                  <span className="opacity-60">⚡</span>{s}
                </span>
              ))}
              {step.tools?.map(t => (
                <span key={t} className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full
                  bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 font-medium">
                  <span className="opacity-60">🔧</span>{t}
                </span>
              ))}
            </div>
          )}
          {step.status === 'failed' && step.error && (
            <p className="text-[11px] text-red-500 mt-0.5">{step.error}</p>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {hasOutput && (
            <span
              onClick={e => { e.stopPropagation(); download() }}
              className="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer"
              title="다운로드"
            >
              <MatIcon name="download" className="text-[14px]" />
            </span>
          )}
          {hasOutput && (
            <MatIcon
              name={open ? 'expand_less' : 'expand_more'}
              className="text-[18px] text-gray-400"
            />
          )}
        </div>
      </button>

      {/* 출력 내용 */}
      {open && hasOutput && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-3 pb-3 pt-2">
          {isHtmlPreview ? (
            <HtmlPreview html={step.output.match(/```html\s*([\s\S]*?)```/)?.[1] ?? step.output} />
          ) : hasMermaid ? (
            <div className="space-y-3">
              {step.output.split(/(```mermaid[\s\S]*?```)/g).map((part, i) => {
                const match = part.match(/```mermaid\s*([\s\S]*?)```/)
                return match
                  ? <MermaidBlock key={i} code={match[1].trim()} />
                  : part.trim() ? <MarkdownViewer key={i} content={part} /> : null
              })}
            </div>
          ) : hasVega ? (
            <div className="space-y-3">
              {step.output.split(/(```vega(?:-lite)?\s[\s\S]*?```)/g).map((part, i) => {
                const match = part.match(/```vega(?:-lite)?\s([\s\S]*?)```/)
                if (match) {
                  try {
                    const vegaSpec = JSON.parse(match[1].trim())
                    return <VegaChart key={i} spec={vegaSpec} />
                  } catch {
                    return <pre key={i} className="text-xs text-red-400">{match[1]}</pre>
                  }
                }
                return part.trim() ? <MarkdownViewer key={i} content={part} /> : null
              })}
            </div>
          ) : isCode ? (
            <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
              {step.output}
            </pre>
          ) : (
            <div>
              <MarkdownViewer content={step.output} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function GateControl({ job, gate }: { job: Job; gate: NonNullable<Job['gates']>[number] }) {
  const qc = useQueryClient()
  const [feedback, setFeedback] = useState('')

  const decide = useMutation({
    mutationFn: async (decision: 'approved' | 'rejected' | 'revised') => {
      const res = await fetch(`/api/jobs/${job.id}/gates/${gate.gate_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, feedback }),
      })
      if (!res.ok) throw new Error('결정 실패')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job', job.id] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['pending-gates'] })
      setFeedback('')
    },
  })

  // 수정 재실행 중
  if (gate.status === 'revising') {
    return (
      <div className="mt-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-200 dark:border-blue-700/40">
        <div className="flex items-center gap-2">
          <MatIcon name="autorenew" className="text-blue-500 text-[18px] animate-spin" />
          <div>
            <p className="text-xs font-semibold text-blue-700 dark:text-blue-400">피드백 반영 중 — 단계 재실행</p>
            {gate.feedback && (
              <p className="text-[11px] text-blue-500 dark:text-blue-500 mt-0.5 italic">"{gate.feedback}"</p>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (gate.status !== 'pending') return null

  return (
    <div className="mt-3 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-xl border border-yellow-200 dark:border-yellow-700/40 space-y-2.5">
      {/* 헤더 */}
      <div className="flex items-start gap-2">
        <MatIcon name="pending" className="text-yellow-500 text-[18px] mt-0.5 shrink-0" />
        <div className="flex-1">
          <p className="text-xs font-semibold text-yellow-700 dark:text-yellow-400">게이트 — 검토 필요</p>
          <p className="text-xs text-yellow-600 dark:text-yellow-500 mt-0.5">{gate.prompt}</p>
        </div>
      </div>

      {/* 피드백 입력 — 항상 표시 */}
      <textarea
        rows={2}
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        placeholder="수정 요청 시 피드백을 입력하세요 (예: 경쟁사 분석 섹션을 더 구체적으로)"
        className="w-full px-3 py-2 text-xs rounded-lg border border-yellow-200 dark:border-yellow-700
          bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none
          focus:outline-none focus:ring-2 focus:ring-yellow-400/50"
      />

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <button
          onClick={() => decide.mutate('approved')}
          disabled={decide.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white
            bg-green-600 hover:bg-green-700 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="check" className="text-[14px]" />
          승인
        </button>
        <button
          onClick={() => decide.mutate('revised')}
          disabled={decide.isPending || !feedback.trim()}
          title={!feedback.trim() ? '피드백을 먼저 입력하세요' : ''}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
            text-blue-700 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30
            hover:bg-blue-200 dark:hover:bg-blue-900/50 rounded-lg transition-colors
            cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <MatIcon name="refresh" className="text-[14px]" />
          수정 후 재검토
        </button>
        <button
          onClick={() => decide.mutate('rejected')}
          disabled={decide.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
            text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20
            hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors
            cursor-pointer disabled:opacity-50"
        >
          <MatIcon name="cancel" className="text-[14px]" />
          거절
        </button>
      </div>
      {decide.isError && (
        <p className="text-xs text-red-500">
          {decide.error instanceof Error ? decide.error.message : '오류'}
        </p>
      )}
    </div>
  )
}

// 교차 리뷰 카드 — cross_review artifact를 특별 카드로 렌더링
function CrossReviewCard({ content }: { content: string }) {
  const [open, setOpen] = useState(false)

  // reviewer 판별: 마크다운 헤더에서 추출
  const isOpus = content.includes('Opus') || content.includes('🟣')
  const reviewer = isOpus ? 'opus' : 'gemini'

  // 점수 추출
  const scoreMatch = content.match(/점수[:\s]*(\d+)\s*\/\s*100/)
  const score = scoreMatch ? parseInt(scoreMatch[1]) : null

  return (
    <div className={`rounded-xl overflow-hidden border
      ${reviewer === 'opus'
        ? 'border-purple-200 dark:border-purple-700/50'
        : 'border-blue-200 dark:border-blue-700/50'
      }`}>
      {/* 그라데이션 헤더 */}
      <div className={`px-4 py-3
        ${reviewer === 'opus'
          ? 'bg-gradient-to-r from-purple-600 to-purple-800 dark:from-purple-700 dark:to-purple-900'
          : 'bg-gradient-to-r from-blue-500 to-blue-700 dark:from-blue-600 dark:to-blue-900'
        }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">{reviewer === 'opus' ? '🟣' : '🔵'}</span>
            <div>
              <p className="text-xs font-bold text-white">
                {reviewer === 'opus' ? 'Claude Opus 4.7' : 'Gemini 2.5 Pro'} 교차 리뷰
              </p>
              <p className="text-[10px] text-white/70">
                {reviewer === 'opus' ? 'Gemini 산출물 검토' : 'Claude 산출물 검토'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {score !== null && (
              <span className={`text-xl font-black ${
                score >= 80 ? 'text-green-300' : score >= 60 ? 'text-yellow-300' : 'text-red-300'
              }`}>
                {score}
                <span className="text-xs font-medium text-white/60">/100</span>
              </span>
            )}
            <button
              onClick={() => setOpen(!open)}
              className="p-1 rounded-lg bg-white/20 hover:bg-white/30 transition-colors cursor-pointer"
            >
              <MatIcon
                name={open ? 'expand_less' : 'expand_more'}
                className="text-[16px] text-white"
              />
            </button>
          </div>
        </div>
      </div>

      {/* 펼쳐진 내용 */}
      {open && (
        <div className={`px-4 py-3
          ${reviewer === 'opus'
            ? 'bg-purple-50/50 dark:bg-purple-950/30'
            : 'bg-blue-50/50 dark:bg-blue-950/30'
          }`}>
          <MarkdownViewer content={content} />
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// 산출물 허브 서브 컴포넌트
// ─────────────────────────────────────────────────────────────────────────────

// 마크다운 프리뷰 카드
function ArtifactMarkdownCard({
  title,
  content,
  icon,
  accentCls = 'border-gray-200 dark:border-gray-700',
  headerCls = 'bg-gray-50 dark:bg-gray-800/60',
}: {
  title: string
  content: string
  icon: string
  accentCls?: string
  headerCls?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const preview = content.replace(/#{1,6}\s/g, '').replace(/[*_`]/g, '').slice(0, 150)

  const copy = () => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const download = () => {
    const blob = new Blob([content], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={`rounded-xl border overflow-hidden ${accentCls}`}>
      <div className={`flex items-center justify-between px-3 py-2 ${headerCls}`}>
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-sm">{icon}</span>
          <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 truncate">{title}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={copy}
            className="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors cursor-pointer"
            title="복사"
          >
            <MatIcon name={copied ? 'check' : 'content_copy'} className="text-[13px]" />
          </button>
          <button
            onClick={download}
            className="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors cursor-pointer"
            title="다운로드"
          >
            <MatIcon name="download" className="text-[13px]" />
          </button>
        </div>
      </div>

      <div className="px-3 py-2.5 bg-white dark:bg-gray-900">
        {expanded ? (
          <div className="max-h-96 overflow-y-auto">
            <MarkdownViewer content={content} />
          </div>
        ) : (
          <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed line-clamp-3">
            {preview}{content.length > 150 ? '…' : ''}
          </p>
        )}
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 text-[11px] font-medium text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
        >
          {expanded ? '접기' : '더 보기'}
        </button>
      </div>
    </div>
  )
}

// HTML 미리보기 카드 (썸네일 iframe + 모달)
function ArtifactHtmlCard({ content }: { content: string }) {
  const [showModal, setShowModal] = useState(false)
  const htmlContent = content.match(/```html\s*([\s\S]*?)```/)?.[1] ?? content
  const blob = new Blob([htmlContent], { type: 'text/html' })
  const src = URL.createObjectURL(blob)

  return (
    <>
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-800/60">
          <div className="flex items-center gap-1.5">
            <span className="text-sm">🖥️</span>
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">HTML 미리보기</span>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors cursor-pointer"
          >
            <MatIcon name="open_in_full" className="text-[12px]" />
            전체 화면
          </button>
        </div>

        {/* 썸네일 — scale 축소 iframe */}
        <div
          className="relative bg-white overflow-hidden cursor-pointer"
          style={{ height: 100 }}
          onClick={() => setShowModal(true)}
        >
          <iframe
            src={src}
            title="HTML 썸네일"
            sandbox="allow-scripts"
            style={{
              width: 375,
              height: 333,
              border: 'none',
              transform: 'scale(0.3)',
              transformOrigin: 'top left',
              pointerEvents: 'none',
            }}
          />
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/10 transition-colors">
            <div className="opacity-0 hover:opacity-100 transition-opacity bg-black/60 text-white text-xs px-3 py-1.5 rounded-lg">
              미리보기
            </div>
          </div>
        </div>
      </div>

      {/* 전체 화면 모달 */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
          <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
              <span className="text-sm font-semibold text-gray-900 dark:text-white">HTML 미리보기</span>
              <button
                onClick={() => setShowModal(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer"
              >
                <MatIcon name="close" className="text-[18px]" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <HtmlPreview html={htmlContent} />
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// 산출물 허브 — Job done 시 step 타임라인 위에 표시
// ─────────────────────────────────────────────────────────────────────────────
function DeliverableHub({ job }: { job: Job }) {
  const artifacts = job.artifacts ?? {}
  const kinds = job.artifact_kinds ?? {}

  // artifact 분류
  const summary = artifacts.summary ?? null
  const markdownCards: Array<{ key: string; content: string; icon: string; label: string }> = []
  const htmlEntries: Array<{ key: string; content: string }> = []
  const svgEntries: Array<{ key: string; content: string }> = []
  const imageEntries: Array<{ key: string; content: string }> = []
  const zipEntries: Array<{ key: string }> = []

  for (const [key, value] of Object.entries(artifacts)) {
    if (key === 'summary') continue
    if (key === 'cross_review') continue
    const kind = kinds[key] ?? 'markdown'

    if (kind === 'html') {
      htmlEntries.push({ key, content: value })
    } else if (kind === 'svg') {
      svgEntries.push({ key, content: value })
    } else if (kind === 'image') {
      imageEntries.push({ key, content: value })
    } else if (kind === 'zip') {
      zipEntries.push({ key })
    } else {
      // markdown 종류 — key에 따라 아이콘/레이블 결정
      const labelMap: Record<string, { icon: string; label: string }> = {
        report:   { icon: '📄', label: '최종 리포트' },
        brief:    { icon: '📝', label: '브리프' },
        final_markup: { icon: '📄', label: '최종 마크업' },
        insights: { icon: '💡', label: '인사이트' },
        analysis: { icon: '🔍', label: '분석' },
        plan:     { icon: '🗂️', label: '기획안' },
      }
      const meta = labelMap[key] ?? { icon: '📄', label: key }
      markdownCards.push({ key, content: value, ...meta })
    }
  }

  const totalCount = Object.keys(artifacts).length

  return (
    <div className="mx-4 mt-4 mb-1">
      {/* 헤더 — 제목 + QualityBadge 인라인 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <MatIcon name="inventory_2" className="text-[16px] text-indigo-500" />
          <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
            산출물 <span className="font-normal text-gray-400">({totalCount}개)</span>
          </h3>
        </div>
        {/* QualityBadge 인라인 — 소형 버전 */}
        <QualityBadgeInline jobId={job.id} />
      </div>

      {/* 핵심 요약 카드 — 항상 최상단, 파란 배경 */}
      {summary && (
        <div className="mb-3 rounded-xl border border-blue-200 dark:border-blue-700/50 overflow-hidden">
          <div className="px-3 py-2 bg-blue-600 dark:bg-blue-700">
            <div className="flex items-center gap-1.5">
              <MatIcon name="summarize" className="text-[14px] text-white" />
              <span className="text-xs font-bold text-white">핵심 요약</span>
            </div>
          </div>
          <div className="px-3 py-2.5 bg-blue-50 dark:bg-blue-950/40">
            <p className="text-xs text-blue-900 dark:text-blue-200 leading-relaxed whitespace-pre-wrap break-words">{summary}</p>
          </div>
        </div>
      )}

      {/* 그리드 — 2열 (모바일 1열) */}
      {(markdownCards.length > 0 || htmlEntries.length > 0 || svgEntries.length > 0 || imageEntries.length > 0 || zipEntries.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* 마크다운 카드들 */}
          {markdownCards.map(({ key, content, icon, label }) => (
            <ArtifactMarkdownCard key={key} title={label} content={content} icon={icon} />
          ))}

          {/* HTML 미리보기 카드 */}
          {htmlEntries.map(({ key, content }) => (
            <ArtifactHtmlCard key={key} content={content} />
          ))}

          {/* SVG 팔레트 카드 */}
          {svgEntries.map(({ key, content }) => (
            <div key={key} className="rounded-xl border border-blue-200 dark:border-blue-700/50 overflow-hidden">
              <div className="flex items-center gap-1.5 px-3 py-2 bg-blue-50 dark:bg-blue-900/30">
                <span className="text-sm">🎨</span>
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">{key}</span>
              </div>
              <div className="p-3 bg-white dark:bg-gray-900">
                <SvgArtifact content={content} />
              </div>
            </div>
          ))}

          {/* 이미지 갤러리 카드 */}
          {imageEntries.map(({ key, content }) => (
            <div key={key} className="rounded-xl border border-green-200 dark:border-green-700/50 overflow-hidden">
              <div className="flex items-center gap-1.5 px-3 py-2 bg-green-50 dark:bg-green-900/30">
                <span className="text-sm">📸</span>
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">{key}</span>
              </div>
              <div className="p-3 bg-white dark:bg-gray-900">
                <ImageGalleryArtifact content={content} />
              </div>
            </div>
          ))}

          {/* ZIP 다운로드 카드 */}
          {zipEntries.map(({ key }) => (
            <div key={key} className="rounded-xl border border-amber-200 dark:border-amber-700/50 overflow-hidden">
              <div className="flex items-center gap-1.5 px-3 py-2 bg-amber-50 dark:bg-amber-900/30">
                <span className="text-sm">📦</span>
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">코드 번들</span>
              </div>
              <div className="p-3 bg-white dark:bg-gray-900 flex items-center gap-3">
                <a
                  href={`/api/jobs/${job.id}/bundle`}
                  download={`${job.id}-bundle.zip`}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-white bg-amber-600 hover:bg-amber-700 rounded-lg transition-colors"
                >
                  <MatIcon name="download" className="text-[14px]" />
                  코드 번들 다운로드
                </a>
                <span className="text-[11px] text-gray-400">{key}.zip</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 교차 리뷰 — 별도 구역 */}
      {artifacts.cross_review && (
        <div className="mt-3">
          <div className="flex items-center gap-1.5 mb-2">
            <span className="text-sm">⭐</span>
            <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">교차 리뷰</span>
          </div>
          <CrossReviewCard content={artifacts.cross_review} />
        </div>
      )}
    </div>
  )
}

// QualityBadge 인라인 소형 버전 (DeliverableHub 헤더용)
function QualityBadgeInline({ jobId }: { jobId: string }) {
  const [open, setOpen] = useState(false)

  const { data: qualities } = useQuery<ArtifactQualityItem[]>({
    queryKey: ['job-quality', jobId],
    queryFn: async () => {
      const res = await fetch(`/api/jobs/${jobId}/quality`)
      if (!res.ok) return []
      return res.json()
    },
    staleTime: 60_000,
  })

  if (!qualities || qualities.length === 0) return null

  const avg = Math.round(qualities.reduce((s, q) => s + q.overall, 0) / qualities.length)
  const colorCls = avg >= 70
    ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 border-green-200 dark:border-green-700/50'
    : avg >= 50
      ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 border-yellow-200 dark:border-yellow-700/50'
      : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 border-red-200 dark:border-red-700/50'

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-semibold transition-colors cursor-pointer ${colorCls}`}
      >
        <span className="text-[10px]">●</span>
        <span>품질</span>
        <span>{avg}점</span>
        <MatIcon name={open ? 'expand_less' : 'expand_more'} className="text-[13px]" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-20 w-64 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg divide-y divide-gray-100 dark:divide-gray-800">
          {qualities.map(q => {
            const score = Math.round(q.overall)
            const sc = score >= 70 ? 'text-green-600 dark:text-green-400'
              : score >= 50 ? 'text-yellow-600 dark:text-yellow-400'
              : 'text-red-600 dark:text-red-400'
            return (
              <div key={q.artifact_key} className="px-3 py-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11px] font-semibold text-gray-700 dark:text-gray-300 uppercase">{q.artifact_key}</span>
                  <span className={`text-sm font-bold ${sc}`}>{score}점</span>
                </div>
                <div className="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${score >= 70 ? 'bg-green-500' : score >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`}
                    style={{ width: `${score}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

// 교차 리뷰 트리거 버튼 — done 상태이고 cross_review가 없을 때 표시
function CrossReviewTrigger({ jobId }: { jobId: string }) {
  const qc = useQueryClient()

  const trigger = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/jobs/${jobId}/cross-review`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '교차 리뷰 요청 실패')
      }
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job', jobId] })
    },
  })

  return (
    <button
      onClick={() => trigger.mutate()}
      disabled={trigger.isPending}
      className="h-8 w-8 flex items-center justify-center
        text-purple-700 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/30
        hover:bg-purple-200 dark:hover:bg-purple-900/50 rounded-lg transition-colors
        cursor-pointer disabled:opacity-50 shrink-0"
      title={trigger.isError
        ? (trigger.error instanceof Error ? trigger.error.message : '오류')
        : '교차 리뷰 — Opus/Gemini가 산출물을 검토합니다'}
    >
      {trigger.isPending
        ? <MatIcon name="hourglass_empty" className="text-[15px] animate-spin" />
        : <MatIcon name="rate_review" className="text-[15px]" />}
    </button>
  )
}

// ── 퍼블리시 모달 ─────────────────────────────────────────────────────────────

function GmailModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const [to, setTo] = useState('')
  const [subject, setSubject] = useState('')
  const [result, setResult] = useState<{ ok?: boolean; error?: string; to?: string } | null>(null)
  const [loading, setLoading] = useState(false)

  const send = async () => {
    if (!to.trim()) return
    setLoading(true)
    try {
      const res = await fetch(`/api/jobs/${jobId}/publish/gmail`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to: to.trim(), subject: subject.trim() }),
      })
      const data = await res.json()
      if (!res.ok) setResult({ error: data.detail || '발송 실패' })
      else if (data.error) setResult({ error: `${data.error}: ${(data.required as string[]).join(', ')} 환경변수 설정 필요` })
      else setResult({ ok: true, to: data.to })
    } catch {
      setResult({ error: '네트워크 오류' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-800">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">이메일 발송</h3>
          <button onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
            <MatIcon name="close" className="text-[18px]" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          {result?.ok ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <MatIcon name="check_circle" className="text-[40px] text-green-500" />
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">발송 완료!</p>
              <p className="text-xs text-gray-500">{result.to} 로 전송되었습니다</p>
              <button onClick={onClose}
                className="px-4 py-2 text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors cursor-pointer">
                닫기
              </button>
            </div>
          ) : (
            <>
              <div>
                <label className="text-[11px] font-medium text-gray-500 uppercase mb-1 block">받는 사람</label>
                <input
                  type="email"
                  value={to}
                  onChange={e => setTo(e.target.value)}
                  placeholder="email@example.com"
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                    focus:outline-none focus:ring-2 focus:ring-blue-400/50"
                />
              </div>
              <div>
                <label className="text-[11px] font-medium text-gray-500 uppercase mb-1 block">제목 (선택)</label>
                <input
                  type="text"
                  value={subject}
                  onChange={e => setSubject(e.target.value)}
                  placeholder="비워두면 자동 생성"
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                    focus:outline-none focus:ring-2 focus:ring-blue-400/50"
                />
              </div>
              {result?.error && (
                <p className="text-xs text-red-500">{result.error}</p>
              )}
              <div className="flex gap-2 pt-1">
                <button onClick={onClose}
                  className="flex-1 px-3 py-2 text-xs font-medium text-gray-600 dark:text-gray-400
                    bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700
                    rounded-lg transition-colors cursor-pointer">
                  취소
                </button>
                <button
                  onClick={send}
                  disabled={loading || !to.trim()}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium
                    text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors
                    cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
                  {loading ? <MatIcon name="hourglass_empty" className="text-[13px] animate-spin" /> : <MatIcon name="send" className="text-[13px]" />}
                  {loading ? '발송 중...' : '발송'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function FigmaModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const [data, setData] = useState<{ mermaid_code?: string; figma_url?: string; instructions?: string; message?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    fetch(`/api/jobs/${jobId}/publish/figma`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData({ message: '오류가 발생했습니다' }))
      .finally(() => setLoading(false))
  }, [jobId])

  const copy = () => {
    if (!data?.mermaid_code) return
    navigator.clipboard.writeText(data.mermaid_code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Figma 내보내기</h3>
          <button onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
            <MatIcon name="close" className="text-[18px]" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <MatIcon name="hourglass_empty" className="text-[32px] text-gray-400 animate-spin" />
            </div>
          ) : data?.message && !data.mermaid_code ? (
            <div className="text-center py-6">
              <MatIcon name="info" className="text-[32px] text-gray-400 mb-2" />
              <p className="text-sm text-gray-600 dark:text-gray-400">{data.message}</p>
            </div>
          ) : (
            <>
              {data?.instructions && (
                <div className="bg-blue-50 dark:bg-blue-900/20 rounded-xl p-4">
                  <p className="text-xs font-semibold text-blue-700 dark:text-blue-400 mb-2">사용 방법</p>
                  <pre className="text-xs text-blue-600 dark:text-blue-300 whitespace-pre-wrap">{data.instructions}</pre>
                </div>
              )}
              {data?.mermaid_code && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-semibold text-gray-500 uppercase">다이어그램 코드</span>
                    <button onClick={copy}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 dark:text-gray-400
                        bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700
                        rounded-lg transition-colors cursor-pointer">
                      <MatIcon name={copied ? 'check' : 'content_copy'} className="text-[13px]" />
                      {copied ? '복사됨' : '복사'}
                    </button>
                  </div>
                  <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800
                    rounded-xl p-3 overflow-x-auto whitespace-pre-wrap max-h-48">
                    {data.mermaid_code}
                  </pre>
                </div>
              )}
              {data?.figma_url && (
                <a
                  href={data.figma_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-center gap-2 w-full px-4 py-2.5 text-sm font-medium
                    text-white bg-gray-800 hover:bg-gray-900 dark:bg-gray-700 dark:hover:bg-gray-600
                    rounded-xl transition-colors">
                  <MatIcon name="open_in_new" className="text-[16px]" />
                  FigJam 열기
                </a>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function NotionPublishButton({ jobId }: { jobId: string }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ url?: string; error?: string } | null>(null)

  const publish = async () => {
    setLoading(true)
    setResult(null)
    try {
      const res = await fetch(`/api/jobs/${jobId}/publish/notion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      const data = await res.json()
      if (!res.ok) setResult({ error: data.detail || 'Notion 게시 실패' })
      else setResult({ url: data.notion_url })
    } catch {
      setResult({ error: '네트워크 오류' })
    } finally {
      setLoading(false)
    }
  }

  if (result?.url) {
    return (
      <a href={result.url} target="_blank" rel="noreferrer"
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
          text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-900/30
          hover:bg-green-200 dark:hover:bg-green-900/50 rounded-lg transition-colors">
        <MatIcon name="open_in_new" className="text-[13px]" />
        Notion에서 열기
      </a>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={publish}
        disabled={loading}
        className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium text-left
          text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
          rounded-lg transition-colors cursor-pointer disabled:opacity-50">
        {loading
          ? <MatIcon name="hourglass_empty" className="text-[13px] animate-spin" />
          : <span className="text-[13px] font-bold">N</span>}
        Notion에 게시
      </button>
      {result?.error && <p className="text-[10px] text-red-500 px-3">{result.error}</p>}
    </div>
  )
}

// 퍼블리시 드롭다운
function PublishDropdown({ jobId }: { jobId: string }) {
  const [open, setOpen] = useState(false)
  const [gmailOpen, setGmailOpen] = useState(false)
  const [figmaOpen, setFigmaOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 외부 클릭 시 닫기
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <>
      <div ref={ref} className="relative">
        <button
          onClick={() => setOpen(o => !o)}
          className="h-8 w-8 flex items-center justify-center
            text-gray-700 dark:text-gray-200 bg-gray-100 dark:bg-gray-800
            hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors cursor-pointer"
          title="퍼블리시"
        >
          <MatIcon name="upload" className="text-[16px]" />
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 z-40 w-44 bg-white dark:bg-gray-900
            border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden">
            {/* Notion */}
            <div className="p-1">
              <NotionPublishButton jobId={jobId} />
            </div>
            <div className="border-t border-gray-100 dark:border-gray-800 p-1">
              {/* Gmail */}
              <button
                onClick={() => { setOpen(false); setGmailOpen(true) }}
                className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium text-left
                  text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
                  rounded-lg transition-colors cursor-pointer">
                <MatIcon name="email" className="text-[13px]" />
                이메일 발송
              </button>
            </div>
            <div className="border-t border-gray-100 dark:border-gray-800 p-1">
              {/* Figma */}
              <button
                onClick={() => { setOpen(false); setFigmaOpen(true) }}
                className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium text-left
                  text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800
                  rounded-lg transition-colors cursor-pointer">
                <MatIcon name="dashboard" className="text-[13px]" />
                Figma 내보내기
              </button>
            </div>
          </div>
        )}
      </div>

      {gmailOpen && <GmailModal jobId={jobId} onClose={() => setGmailOpen(false)} />}
      {figmaOpen && <FigmaModal jobId={jobId} onClose={() => setFigmaOpen(false)} />}
    </>
  )
}

// 최종 리포트 전체 뷰 (모달)
function ReportModal({ title, content, onClose }: { title: string; content: string; onClose: () => void }) {
  const download = () => {
    const blob = new Blob([content], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-800">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate">{title}</h3>
          <div className="flex gap-2 shrink-0">
            <button onClick={download}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white
                bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700
                rounded-lg transition-colors cursor-pointer">
              <MatIcon name="download" className="text-[14px]" />
              다운로드
            </button>
            <button onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white
                hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer">
              <MatIcon name="close" className="text-[18px]" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <MarkdownViewer content={content} />
        </div>
      </div>
    </div>
  )
}

export function JobDetailView({
  jobId,
  onClose,
  onDuplicate,
  onChain,
}: {
  jobId: string
  onClose: () => void
  onDuplicate?: (job: Job) => void
  onChain?: (job: Job) => void    // 산출물 기반 다음 Job 시작
}) {
  const qc = useQueryClient()
  const [reportKey, setReportKey] = useState<string | null>(null)

  const { data: job, isLoading } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'running' || status === 'waiting_gate' || status === 'queued') return 2000
      return false
    },
  })

  const cancel = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('취소 실패')
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['job', jobId] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        <MatIcon name="hourglass_empty" className="text-[32px] animate-spin" />
      </div>
    )
  }

  if (!job) return null

  const status = STATUS_LABEL[job.status] ?? STATUS_LABEL.queued
  const pendingGate = job.gates?.find(g => g.status === 'pending')
  // 최종 리포트 키 찾기 (output_key='report'인 스텝)
  const reportKeys = ['report', 'brief', 'final_markup', 'insights']
  const finalKey = reportKeys.find(k => job.artifacts?.[k])

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0 overflow-x-hidden bg-white dark:bg-gray-950">
      {/* 헤더 */}
      <div className="flex items-center gap-2 px-3 py-3 border-b border-gray-200 dark:border-gray-800">
        <button onClick={onClose}
          className="shrink-0 p-1.5 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white
            hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer
            min-w-[36px] min-h-[36px] flex items-center justify-center">
          <MatIcon name="arrow_back" className="text-[18px]" />
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white line-clamp-2 leading-snug">{job.title}</h2>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-0.5">
            <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${status.cls}`}>
              <MatIcon name={status.icon} className="text-[11px]" />
              {status.text}
            </span>
            <span className="text-[10px] text-gray-400 truncate max-w-[80px]">{job.spec_id}</span>
            {job.created_at && (
              <span className="text-[10px] text-gray-400 hidden sm:inline">
                {new Date(job.created_at).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
            {job.status === 'done' && (job.total_cost_usd ?? 0) > 0 && (
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-mono">
                ${job.total_cost_usd.toFixed(4)}
              </span>
            )}
            {/* Haiku 실행 계획 */}
            {job.planned_steps && job.planned_steps.length > 0 && (
              <div className="flex flex-wrap items-center gap-1 mt-1 w-full">
                <span className="text-[9px] text-gray-400 shrink-0">실행계획:</span>
                {job.planned_steps.map((sid, i) => (
                  <span key={sid} className="flex items-center gap-0.5">
                    {i > 0 && <span className="text-[8px] text-gray-300 dark:text-gray-600">›</span>}
                    <span className={`text-[9px] px-1 py-0.5 rounded font-medium
                      ${job.current_step === sid
                        ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400'
                        : job.steps?.find(s => s.step_id === sid)?.status === 'done'
                          ? 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'
                          : 'text-gray-400 dark:text-gray-500'}`}>
                      {sid}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {finalKey && job.status === 'done' && (
            <button
              onClick={() => setReportKey(finalKey)}
              className="h-8 w-8 flex items-center justify-center rounded-lg
                text-white bg-blue-600 hover:bg-blue-700 transition-colors cursor-pointer"
              title="리포트 보기"
            >
              <MatIcon name="article" className="text-[16px]" />
            </button>
          )}
          {job.status === 'done' && !job.artifacts?.cross_review && (
            <CrossReviewTrigger jobId={job.id} />
          )}
          {onChain && job.status === 'done' && (
            <button
              onClick={() => onChain(job)}
              className="h-8 w-8 flex items-center justify-center rounded-lg
                text-purple-700 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/30
                hover:bg-purple-200 dark:hover:bg-purple-900/50 transition-colors cursor-pointer"
              title="산출물 기반 다음 단계 시작"
            >
              <MatIcon name="arrow_forward" className="text-[16px]" />
            </button>
          )}
          {job.status === 'done' && <PublishDropdown jobId={job.id} />}
          {onDuplicate && (
            <button
              onClick={() => onDuplicate(job)}
              className="h-8 w-8 flex items-center justify-center rounded-lg
                text-gray-400 hover:text-gray-700 dark:hover:text-gray-200
                hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer"
              title="입력값 복제로 새 작업 시작"
            >
              <MatIcon name="content_copy" className="text-[16px]" />
            </button>
          )}
          {(job.status === 'running' || job.status === 'queued' || job.status === 'waiting_gate') && (
            <button
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
              className="h-8 w-8 flex items-center justify-center rounded-lg
                text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20
                transition-colors cursor-pointer disabled:opacity-50"
              title="작업 취소"
            >
              <MatIcon name="stop_circle" className="text-[18px]" />
            </button>
          )}
        </div>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {/* Gate 알림 (최상단) */}
        {pendingGate && (
          <div className="m-4">
            <GateControl job={job} gate={pendingGate} />
          </div>
        )}

        {/* 산출물 허브 — done 상태이고 artifact 있을 때 step 타임라인 위에 표시 */}
        {job.status === 'done' && job.artifacts && Object.keys(job.artifacts).length > 0 && (
          <DeliverableHub job={job} />
        )}

        <div className="p-4 space-y-5">
          {/* Steps 타임라인 */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                실행 단계
              </h3>
              <span className="text-[10px] text-gray-400">
                클릭하면 출력 내용 확인
              </span>
            </div>
            <div className="space-y-1.5">
              {job.steps?.map((step, idx) => (
                <StepCard
                  key={step.step_id}
                  step={step}
                  isActive={job.current_step === step.step_id && step.status === 'running'}
                  isLast={idx === (job.steps?.length ?? 0) - 1}
                />
              ))}
            </div>
          </div>

          {/* Gate 상태 목록 (pending 제외 — 위에서 처리) */}
          {job.gates && job.gates.some(g => g.status !== 'pending') && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                게이트 이력
              </h3>
              <div className="space-y-1.5">
                {job.gates.filter(g => g.status !== 'pending').map(gate => {
                  const gIcon = gate.status === 'approved' ? 'check_circle'
                    : gate.status === 'rejected' ? 'cancel'
                    : gate.status === 'not_reached' ? 'radio_button_unchecked'
                    : 'pending'
                  const gCls = gate.status === 'approved' ? 'text-green-500'
                    : gate.status === 'rejected' ? 'text-red-500'
                    : 'text-gray-400'
                  return (
                    <div key={gate.gate_id}
                      className="flex items-start gap-2 p-2.5 bg-gray-50 dark:bg-gray-800/50 rounded-xl">
                      <MatIcon name={gIcon} className={`text-[17px] mt-0.5 ${gCls}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-gray-700 dark:text-gray-300">{gate.gate_id}</p>
                        {gate.feedback && (
                          <p className="text-[11px] text-blue-500 mt-0.5 italic">"{gate.feedback}"</p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 입력값 */}
          {job.input && Object.keys(job.input).length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                입력값
              </h3>
              <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-3 space-y-2">
                {Object.entries(job.input).map(([k, v]) => (
                  <div key={k}>
                    <span className="text-[10px] font-semibold text-gray-400 uppercase">{k}</span>
                    <p className="text-xs text-gray-700 dark:text-gray-300 mt-0.5 whitespace-pre-wrap">{v}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 오류 */}
          {job.status === 'failed' && job.error && (
            <div className="bg-red-50 dark:bg-red-900/20 rounded-xl p-3">
              <p className="text-xs font-semibold text-red-600 dark:text-red-400 mb-1">오류</p>
              <p className="text-xs text-red-500 font-mono">{job.error}</p>
            </div>
          )}
        </div>
      </div>

      {/* 리포트 모달 */}
      {reportKey && job.artifacts?.[reportKey] && (
        <ReportModal
          title={`${job.title} — ${reportKey}`}
          content={job.artifacts[reportKey]}
          onClose={() => setReportKey(null)}
        />
      )}
    </div>
  )
}
