import { useState } from 'react'
import Markdown from 'react-markdown'
import { AGENT_PROFILE } from '../../config/team'
import { MatIcon } from '../icons'
import type { LogEntry } from '../../types'
import type { FileInfo } from './chatUtils'
import {
  AVATAR_IMG, formatTime, isSystemEvent, fileIcon, formatSize,
  linkify,
} from './chatUtils'
import { useStore } from '../../store'

const STEP_EVENT_TYPES = new Set([
  'job_step_started', 'job_step_done', 'job_step_failed', 'job_step_revised',
])

function isStepEvent(log: LogEntry): boolean {
  return STEP_EVENT_TYPES.has(log.event_type)
}

function StepGroupCard({ logs }: { logs: LogEntry[] }) {
  const [expanded, setExpanded] = useState(false)
  const jobTitle = (logs[0].data?.job_title as string) ?? '작업'
  const jobId = (logs[0].data?.job_id as string) ?? ''
  const doneCount = logs.filter((l) => l.event_type === 'job_step_done').length
  const failedCount = logs.filter((l) => l.event_type === 'job_step_failed').length
  const allDone = logs.at(-1)?.event_type === 'job_step_done' || logs.at(-1)?.event_type === 'job_step_failed'

  return (
    <div className="py-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-xl
          bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700
          hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors cursor-pointer touch-manipulation"
      >
        <MatIcon
          name={failedCount > 0 ? 'error' : allDone ? 'check_circle' : 'pending'}
          className={`text-[16px] shrink-0
            ${failedCount > 0 ? 'text-red-400' : allDone ? 'text-green-400' : 'text-blue-400'}`}
        />
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate block">{jobTitle}</span>
          <span className="text-[10px] text-gray-400">
            {doneCount}완료{failedCount > 0 ? ` · ${failedCount}실패` : ''} · {logs.length}스텝
            {jobId && <span className="font-mono ml-1">#{jobId.slice(0, 6)}</span>}
          </span>
        </div>
        <MatIcon
          name="expand_more"
          className={`text-[16px] text-gray-400 shrink-0 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && (
        <div className="mt-1 ml-3 space-y-0.5">
          {logs.map((log, i) => {
            const icon = log.event_type === 'job_step_done'
              ? 'check' : log.event_type === 'job_step_failed'
              ? 'close' : log.event_type === 'job_step_revised'
              ? 'refresh' : 'play_arrow'
            const color = log.event_type === 'job_step_done'
              ? 'text-green-500' : log.event_type === 'job_step_failed'
              ? 'text-red-400' : log.event_type === 'job_step_revised'
              ? 'text-orange-400' : 'text-blue-400'
            return (
              <div key={log.id ?? i} className="flex items-center gap-1.5 px-2 py-0.5">
                <MatIcon name={icon} className={`text-[12px] shrink-0 ${color}`} />
                <span className="text-[11px] text-gray-500 dark:text-gray-400">{log.message}</span>
                <span className="text-[10px] text-gray-400 ml-auto shrink-0">{formatTime(log.timestamp)}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

interface MessageListProps {
  logs: LogEntry[]
  onImageClick: (url: string) => void
}

function threadColorClass(threadId: string): string {
  if (!threadId) return ''
  const palette = [
    'border-l-pink-400', 'border-l-purple-400', 'border-l-indigo-400',
    'border-l-cyan-400', 'border-l-emerald-400', 'border-l-amber-400',
    'border-l-rose-400', 'border-l-violet-400',
  ]
  let h = 0
  for (let i = 0; i < threadId.length; i++) h = (h * 31 + threadId.charCodeAt(i)) | 0
  return palette[Math.abs(h) % palette.length]
}

export function MessageList({ logs, onImageClick }: MessageListProps) {
  const elements: React.ReactNode[] = []
  let prevAgent = ''
  let prevTime = ''
  let prevDate = ''
  let prevThread = ''

  for (let i = 0; i < logs.length; i++) {
    const log = logs[i]
    if (isSystemEvent(log)) continue

    // Step 이벤트는 같은 job_id로 묶어 카드로 렌더링
    if (isStepEvent(log)) {
      const jobId = log.data?.job_id as string | undefined
      const group: LogEntry[] = [log]
      while (i + 1 < logs.length) {
        const next = logs[i + 1]
        if (isStepEvent(next) && next.data?.job_id === jobId) {
          group.push(next)
          i++
        } else {
          break
        }
      }
      elements.push(<StepGroupCard key={`step-group-${log.id ?? i}`} logs={group} />)
      prevAgent = ''
      prevTime = ''
      continue
    }

    const threadId = (log.data as Record<string, unknown>)?.thread_id as string ?? ''
    const threadColor = threadColorClass(threadId)
    const sameThread = threadId && threadId === prevThread
    const threadClasses = threadId ? `border-l-2 ${threadColor} pl-2` : ''
    const profile = AGENT_PROFILE[log.agent_id] ?? {
      name: log.agent_id, character: log.agent_id, color: 'from-gray-500 to-gray-600', role: '',
    }
    const time = formatTime(log.timestamp)
    const isNewGroup = log.agent_id !== prevAgent || time !== prevTime

    const currentDate = new Date(log.timestamp).toLocaleDateString('ko-KR', {
      year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
    })
    if (currentDate !== prevDate) {
      elements.push(
        <div key={`date-${currentDate}`} className="flex items-center gap-3 py-4">
          <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          <span className="text-xs text-gray-400 whitespace-nowrap">{currentDate}</span>
          <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
        </div>
      )
      prevDate = currentDate
    }

    if (log.agent_id === 'user') {
      elements.push(<UserMessage key={log.id ?? i} log={log} time={time} onImageClick={onImageClick} />)
      prevAgent = log.agent_id
      prevTime = time
      continue
    }

    const isResponse = log.event_type === 'response' || log.event_type === 'autonomous' || log.event_type === 'colleague_question'
    const isAutonomousMsg = log.event_type === 'autonomous'

    if (isNewGroup) {
      elements.push(
        <div key={log.id ?? i} id={log.id ? `log-${log.id}` : undefined}
          className={`flex gap-2 md:gap-3 py-1.5 transition-shadow rounded ${threadClasses}`}
          title={threadId ? `토론 스레드 ${threadId}` : undefined}>
          {sameThread && <div className="hidden" />}
          <div className="flex-shrink-0 mt-0.5 relative self-start w-9 h-9 md:w-10 md:h-10">
            <div className={`w-full h-full rounded-full bg-gradient-to-br ${profile.color}
              flex items-center justify-center overflow-hidden
              ring-2 ring-white dark:ring-slate-900 shadow-md
              transition-transform hover:scale-105`}>
              {AVATAR_IMG[log.agent_id]
                ? <img src={AVATAR_IMG[log.agent_id]} alt={profile.character}
                    className="w-full h-full object-cover" loading="lazy" />
                : <span className="text-white text-xs font-bold">{profile.name[0]}</span>}
            </div>
            {isAutonomousMsg && (
              <span title="자발적 발언"
                className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full
                  bg-white dark:bg-gray-900 border border-indigo-300
                  dark:border-indigo-600 flex items-center justify-center
                  text-[10px] leading-none shadow-sm select-none">
                <span className="scale-75">💭</span>
              </span>
            )}
          </div>
          <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[80%]">
            <div className="flex items-baseline gap-2 mb-0.5">
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                {profile.name}</span>
              <span className="text-[10px] text-gray-400">{profile.character}</span>
              <span className="text-[10px] text-gray-400">{time}</span>
            </div>
            <MessageBubble log={log} isResponse={isResponse} onImageClick={onImageClick} />
          </div>
        </div>
      )
    } else {
      elements.push(
        <div key={log.id ?? i} id={log.id ? `log-${log.id}` : undefined}
          className={`flex gap-3 py-0.5 pl-11 md:pl-[52px] transition-shadow rounded ${threadClasses}`}
          title={threadId ? `토론 스레드 ${threadId}` : undefined}>
          <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[80%]">
            <MessageBubble log={log} isResponse={isResponse} onImageClick={onImageClick} />
          </div>
        </div>
      )
    }
    prevAgent = log.agent_id
    prevTime = time
    prevThread = threadId
  }
  return <>{elements}</>
}

function UserMessage({ log, time, onImageClick }: { log: LogEntry; time: string; onImageClick: (url: string) => void }) {
  const fileInfos = (log.data?.files as FileInfo[]) ?? []
  const fileNames = (log.data?.attachments as string[]) ?? []
  const baseTaskId = (log.data?.base_task_id as string) ?? ''
  const baseTaskInstruction = (log.data?.base_task_instruction as string) ?? ''

  return (
    <div className="flex justify-end py-1">
      <div className="max-w-[85%] md:max-w-[70%]">
        <div className="flex items-baseline gap-2 justify-end mb-0.5">
          <span className="text-[10px] text-gray-400">{time}</span>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">나</span>
        </div>

        {baseTaskId && (
          <div className="flex justify-end mb-1.5">
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg
              bg-purple-500/80 text-white text-xs">
              <MatIcon name="link" className="text-[14px]" />
              {baseTaskInstruction ? baseTaskInstruction.slice(0, 30) + '...' : '이전 작업 참조'}
            </span>
          </div>
        )}

        {fileInfos.filter((f) => f.isImage).map((f, i) => {
          const isGif = f.name.toLowerCase().endsWith('.gif')
          return (
            <div key={`img-${i}`} className="mb-1.5 flex justify-end">
              <button onClick={() => onImageClick(f.url)}
                className="block max-w-[280px] rounded-xl overflow-hidden
                  border border-gray-200 dark:border-gray-700 cursor-zoom-in
                  hover:opacity-90 transition-opacity">
                <img src={f.url} alt={f.name}
                  className={`w-full max-h-[300px] ${isGif ? 'object-contain' : 'object-cover'}`}
                  loading="lazy" />
              </button>
            </div>
          )
        })}

        {fileInfos.filter((f) => !f.isImage).length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
            {fileInfos.filter((f) => !f.isImage).map((f, i) => (
              <a key={`file-${i}`} href={f.url} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg
                  bg-blue-500/80 text-white text-xs hover:bg-blue-500 transition-colors">
                <MatIcon name={fileIcon(f.name)} className="text-[14px]" />
                <span className="truncate max-w-[120px]">{f.name}</span>
                <span className="text-blue-200 text-[10px]">{formatSize(f.size)}</span>
              </a>
            ))}
          </div>
        )}

        {fileInfos.length === 0 && fileNames.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
            {fileNames.map((name, i) => (
              <div key={`fn-${i}`} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg
                bg-blue-500/80 text-white text-xs">
                <MatIcon name={fileIcon(name)} className="text-[14px]" />
                <span className="truncate max-w-[120px]">{name}</span>
              </div>
            ))}
          </div>
        )}

        {log.message && <UserMessageText text={log.message} />}
      </div>
    </div>
  )
}

function UserMessageText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const THRESHOLD = 400
  const PREVIEW = 280
  const isLong = text.length > THRESHOLD
  const display = isLong && !expanded
    ? text.slice(0, PREVIEW).replace(/\s+\S*$/, '') + '…'
    : text

  return (
    <div className="bg-gradient-to-br from-indigo-500 to-violet-600 text-white
      px-4 py-3 rounded-[20px] rounded-tr-[6px]
      text-sm leading-relaxed shadow-lg shadow-indigo-500/20
      ring-1 ring-inset ring-white/10">
      {linkify(display)}
      {isLong && (
        <div className="flex justify-center mt-3 pt-2 border-t border-white/15">
          <button onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 px-3 py-1 rounded-full
              bg-blue-500/40 hover:bg-blue-400/60 backdrop-blur-sm
              text-[11px] font-medium text-blue-50 hover:text-white
              cursor-pointer transition-all duration-150">
            <span>{expanded ? '접기' : `${text.length - PREVIEW}자 더 보기`}</span>
            <MatIcon name="expand_more"
              className={`text-[14px] transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
          </button>
        </div>
      )}
    </div>
  )
}

const COLLAPSE_THRESHOLD = 400
const COLLAPSED_PREVIEW = 280

function MessageBubble({ log, isResponse, onImageClick: _onImageClick }: {
  log: LogEntry; isResponse: boolean; onImageClick: (url: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const isAutonomous = log.event_type === 'autonomous'
  const isColleagueQ = log.event_type === 'colleague_question'
  const content = log.message.replace(/^\[.*?\]\s*/, '')
  const needsInput = !!log.data?.needs_input
  const jobId = log.data?.job_id as string | undefined
  const jobTitle = log.data?.job_title as string | undefined
  const isLong = content.length > COLLAPSE_THRESHOLD
  const displayContent = isLong && !expanded
    ? content.slice(0, COLLAPSED_PREVIEW).replace(/\s+\S*$/, '') + '…'
    : content

  return (
    <div className="group relative">
      <div className={`px-3.5 md:px-4 py-3 rounded-[20px] rounded-tl-[6px] text-sm leading-relaxed
        transition-all duration-150
        ${needsInput
          ? 'bg-amber-50 dark:bg-amber-900/25 border-2 border-amber-300 dark:border-amber-600/70 shadow-md shadow-amber-500/10'
          : isAutonomous
            ? 'bg-indigo-50/70 dark:bg-indigo-900/20 border border-indigo-200/60 dark:border-indigo-700/40 shadow-sm'
            : isColleagueQ
              ? 'bg-teal-50/70 dark:bg-teal-900/20 border border-teal-200/60 dark:border-teal-700/40 shadow-sm'
              : isResponse
                ? 'bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700/70 shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-600'
                : 'bg-slate-100 dark:bg-slate-800/60 border border-transparent'
        }`}>
        {needsInput && (
          <div className="flex items-center gap-1.5 mb-2 text-amber-600 dark:text-amber-400">
            <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-amber-200 dark:bg-amber-800/50">
              답변 필요
            </span>
          </div>
        )}
        {isColleagueQ && (
          <div className="flex items-center gap-1 mb-1.5 text-teal-500 dark:text-teal-400">
            <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-teal-100 dark:bg-teal-800/40">
              <MatIcon name="record_voice_over" className="text-[12px]" /> 동료 질문
            </span>
          </div>
        )}
        {isResponse ? (
          <div className="prose dark:prose-invert prose-sm max-w-none">
            <Markdown>{displayContent}</Markdown>
          </div>
        ) : (
          <span className="text-gray-700 dark:text-gray-300">{linkify(displayContent)}</span>
        )}
        {isLong && (
          <div className="flex justify-center mt-3 pt-2 border-t border-gray-200 dark:border-gray-700">
            <button onClick={() => setExpanded(!expanded)}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-full
                bg-gray-100 hover:bg-gray-200 dark:bg-gray-700/60 dark:hover:bg-gray-700
                text-[11px] font-medium text-gray-600 hover:text-gray-800
                dark:text-gray-300 dark:hover:text-gray-100
                cursor-pointer transition-all duration-150">
              <span>{expanded ? '접기' : `${content.length - COLLAPSED_PREVIEW}자 더 보기`}</span>
              <MatIcon name="expand_more"
                className={`text-[14px] transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
            </button>
          </div>
        )}
      </div>
      {jobId && (
        <JobBadge jobId={jobId} jobTitle={jobTitle} />
      )}
    </div>
  )
}

function JobBadge({ jobId, jobTitle }: { jobId: string; jobTitle?: string }) {
  const setActiveChannel = useStore((s) => s.setActiveChannel)
  return (
    <button
      onClick={() => setActiveChannel('jobs')}
      className="mt-1.5 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg
        bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/20 dark:hover:bg-blue-900/40
        border border-blue-200 dark:border-blue-700/40
        text-xs font-medium text-blue-700 dark:text-blue-300
        cursor-pointer transition-colors touch-manipulation"
    >
      <MatIcon name="assignment" className="text-[13px]" />
      <span className="truncate max-w-[180px]">{jobTitle || '작업'}</span>
      <span className="text-blue-400 dark:text-blue-500 font-mono text-[10px]">#{jobId.slice(0, 6)}</span>
      <MatIcon name="open_in_new" className="text-[11px] opacity-60" />
    </button>
  )
}
