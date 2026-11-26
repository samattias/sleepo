// The width of a page's list column (Inbox, Messages; Sam, 22 Oct 2026): drag its right edge between LIST_MIN and LIST_MAX
// (never more than half the window); double-click resets it; with focus on the handle, ← and → move it 20px (Shift: 60px),
// Home or Enter resets. Width 0 means the page's default. Place it inside the list (position: relative), as its first child;
// the page remembers the width per browser (usePersisted).
import { useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { cn } from '@/lib/util'

export const LIST_MIN = 260, LIST_MAX = 640
// side 'left': the handle sits on the left edge of a panel that opens from the right (the meeting panel), and dragging it
// left makes the panel wider. min, max and share (of the window) bound the width.
export function ListResizer({ width, onChange, label = 'Resize the list', side = 'right', min = LIST_MIN, max = LIST_MAX, share = 0.5 }: {
  width: number; onChange: (w: number) => void; label?: string; side?: 'right' | 'left'; min?: number; max?: number; share?: number }) {
  const [drag, setDrag] = useState(false)
  const dir = side === 'left' ? -1 : 1
  const clampW = (w: number) => Math.round(Math.max(min, Math.min(max, window.innerWidth * share, w)))
  const start = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    const aside = e.currentTarget.parentElement!
    const x0 = e.clientX, w0 = aside.getBoundingClientRect().width
    setDrag(true)
    document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none'
    const move = (ev: PointerEvent) => onChange(clampW(w0 + dir * (ev.clientX - x0)))
    const up = () => {
      setDrag(false)
      document.body.style.cursor = ''; document.body.style.userSelect = ''
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
  }
  const key = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 60 : 20
    const cur = width || e.currentTarget.parentElement!.getBoundingClientRect().width
    if (e.key === 'ArrowLeft') { e.preventDefault(); onChange(clampW(cur - dir * step)) }
    if (e.key === 'ArrowRight') { e.preventDefault(); onChange(clampW(cur + dir * step)) }
    if (e.key === 'Home' || e.key === 'Enter') { e.preventDefault(); onChange(0) }
  }
  return (
    <div role="separator" aria-orientation="vertical" aria-label={label} tabIndex={0}
      aria-valuemin={min} aria-valuemax={max} aria-valuenow={width || undefined}
      title="Drag to resize · double-click to reset" onPointerDown={start} onDoubleClick={() => onChange(0)} onKeyDown={key}
      className={cn('group/rz absolute top-0 z-[3] hidden h-full w-[10px] cursor-col-resize touch-none outline-none md:block', side === 'left' ? '-left-[5px]' : '-right-[5px]')}>
      <span aria-hidden className={cn('absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 rounded-full transition-colors duration-150',
        drag ? 'bg-accent' : 'bg-transparent group-hover/rz:bg-line group-focus-visible/rz:bg-accent')} />
    </div>
  )
}
