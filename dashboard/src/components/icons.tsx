// UI용 SVG 아이콘 — 채팅 메시지 본문에는 사용하지 않음
// Heroicons (MIT) 스타일 24x24 outline, stroke=currentColor
type P = { className?: string }
const base = 'inline-block shrink-0'

export const IconBrain = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M9.5 2a3 3 0 0 0-3 3v.5A3 3 0 0 0 4 8.5v1A3 3 0 0 0 4 15v1a3 3 0 0 0 3 3h.5a3 3 0 0 0 3 3H12V2H9.5zm5 0H12v20h2.5a3 3 0 0 0 3-3H18a3 3 0 0 0 3-3v-1a3 3 0 0 0 0-5.5v-1A3 3 0 0 0 17.5 5.5V5a3 3 0 0 0-3-3z" />
  </svg>
)

export const IconWrench = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M14.7 6.3a4 4 0 0 0 5 5l-9 9a2.83 2.83 0 0 1-4-4l9-9z M18 2l4 4-3 3-4-4 3-3z" />
  </svg>
)

export const IconSearch = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
  </svg>
)

export const IconGitMerge = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" />
    <path d="M6 21V9a9 9 0 0 0 9 9" />
  </svg>
)

export const IconTrash = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M3 6h18 M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2 M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6 M10 11v6 M14 11v6" />
  </svg>
)

export const IconGitBranch = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <line x1="6" y1="3" x2="6" y2="15" /><circle cx="18" cy="6" r="3" />
    <circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" />
  </svg>
)

export const IconClipboard = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <rect x="8" y="2" width="8" height="4" rx="1" />
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
  </svg>
)

export const IconFolder = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7z" />
  </svg>
)

export const IconPaperclip = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
)

export const IconRefresh = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M23 4v6h-6 M1 20v-6h6 M3.51 9a9 9 0 0 1 14.85-3.36L23 10 M20.49 15a9 9 0 0 1-14.85 3.36L1 14" />
  </svg>
)

export const IconChart = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <line x1="4" y1="20" x2="20" y2="20" />
    <rect x="6" y="12" width="3" height="8" />
    <rect x="11" y="7" width="3" height="13" />
    <rect x="16" y="3" width="3" height="17" />
  </svg>
)

export const IconChatBubble = ({ className = 'w-4 h-4' }: P) => (
  <svg className={`${base} ${className}`} fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10z" />
  </svg>
)
