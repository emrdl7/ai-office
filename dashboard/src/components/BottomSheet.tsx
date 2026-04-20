// 모바일 바텀시트 — 드래그 아래로 닫기 + 백드롭 클릭 닫기.
// 데스크톱에선 중앙 모달로 동작.
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  /** 모바일에서만 바텀시트 모드 (기본 true). false면 항상 중앙 모달 */
  bottomOnMobile?: boolean
}

export function BottomSheet({ open, onClose, title, children, bottomOnMobile = true }: Props) {
  const [dragY, setDragY] = useState(0)
  const startY = useRef(0)
  const sheetRef = useRef<HTMLDivElement>(null)

  // ESC 닫기
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  const onTouchStart = (e: React.TouchEvent) => { startY.current = e.touches[0].clientY; setDragY(0) }
  const onTouchMove  = (e: React.TouchEvent) => {
    const dy = e.touches[0].clientY - startY.current
    if (dy > 0) setDragY(dy)
  }
  const onTouchEnd = () => {
    if (dragY > 120) onClose()
    setDragY(0)
  }

  const mobileSheetCls = bottomOnMobile
    ? 'md:items-center md:justify-center items-end'
    : 'items-center justify-center'
  const sheetShapeCls = bottomOnMobile
    ? 'w-full md:max-w-md md:rounded-2xl md:my-6 rounded-t-2xl rounded-b-none'
    : 'w-full max-w-md rounded-2xl'

  return (
    <div
      className={`fixed inset-0 flex ${mobileSheetCls} bg-black/40 animate-[fadeIn_120ms_ease-out]`}
      style={{ zIndex: 'var(--z-modal, 50)' as React.CSSProperties['zIndex'] }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={sheetRef}
        className={`${sheetShapeCls} bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700
          shadow-2xl max-h-[85dvh] flex flex-col`}
        style={{ transform: `translateY(${dragY}px)`, transition: dragY === 0 ? 'transform 160ms ease-out' : 'none' }}
      >
        {/* 핸들 (모바일만) */}
        {bottomOnMobile && (
          <div
            className="md:hidden flex justify-center pt-2 pb-1 cursor-grab active:cursor-grabbing"
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
          >
            <div className="w-10 h-1 rounded-full bg-gray-300 dark:bg-gray-700" />
          </div>
        )}
        {title && (
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h2>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">
          {children}
        </div>
      </div>
    </div>
  )
}
