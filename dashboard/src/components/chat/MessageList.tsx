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
          <div className="flex-shrink-0 mt-0.5 relative self-start w-8 h-8 md:w-9 md:h-9">
            <div className={`w-full h-full rounded-full bg-gradient-to-br ${profile.color}
              flex items-center justify-center shadow-sm overflow-hidden`}>
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
                {profile.character || profile.name}</span>
              <span className="text-[10px] text-gray-400">{profile.role}</span>
              <span className="text-[10px] text-gray-400">{time}</span>
            </div>
            <MessageBubble log={log} isResponse={isResponse} onImageClick={onImageClick} />
          </div>
        </div>
      )
    } else {
      elements.push(
        <div key={log.id ?? i} id={log.id ? `log-${log.id}` : undefined}
          className={`flex gap-3 py-0.5 pl-10 md:pl-12 transition-shadow rounded ${threadClasses}`}
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
    <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-md
      text-sm leading-relaxed">
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
  const isLong = content.length > COLLAPSE_THRESHOLD
  const displayContent = isLong && !expanded
    ? content.slice(0, COLLAPSED_PREVIEW).replace(/\s+\S*$/, '') + '…'
    : content

  return (
    <div className="group relative">
      <div className={`px-3 md:px-4 py-2.5 rounded-2xl rounded-tl-md text-sm leading-relaxed
        ${needsInput
          ? 'bg-amber-50 dark:bg-amber-900/20 border-2 border-amber-300 dark:border-amber-600 shadow-sm'
          : isAutonomous
            ? 'bg-indigo-50/60 dark:bg-indigo-900/15 border border-indigo-200/50 dark:border-indigo-700/30 shadow-sm'
            : isColleagueQ
              ? 'bg-teal-50/60 dark:bg-teal-900/15 border border-teal-200/50 dark:border-teal-700/30 shadow-sm'
              : isResponse
                ? 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-sm'
                : 'bg-gray-100 dark:bg-gray-800/60'
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
    </div>
  )
}
