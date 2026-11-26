// Screenshots of the shared screen in a recorded meeting (Granola, through its MCP: assist/granola_shots.py).
// A filmstrip for the meeting panel, a row for the transcript, and a full-size viewer with previous / next.
// Images are kept RETENTION_DAYS (assist/retention.py) after capture; after that only Granola's description remains.
import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight, Monitor, X } from 'lucide-react'
import { api, shotUrl, type Shot } from '@/lib/api'
import { cn } from '@/lib/util'
import { RetentionDays } from './ui'
import { TZ, LOCALE } from '@/lib/time'

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
const clock = (iso: string) => new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(new Date(iso))
export const shotTime = (s: Shot) => (s.t != null ? mmss(Math.max(0, s.t)) : clock(s.captured_at))

export function ShotViewer({ shots, index, onClose, onJump }: { shots: Shot[]; index: number; onClose: () => void; onJump?: (t: number) => void }) {
  const [i, setI] = useState(index)
  useEffect(() => setI(index), [index])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft') setI((x) => Math.max(0, x - 1))
      else if (e.key === 'ArrowRight') setI((x) => Math.min(shots.length - 1, x + 1))
    }
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key)
  }, [shots.length, onClose])
  const s = shots[i]
  if (!s) return null
  return (
    <div role="dialog" aria-label="Screenshot" className="fixed inset-0 z-[60] flex flex-col bg-black/90 text-white" onClick={onClose}>
      <div className="flex items-center gap-3 px-4 py-2 text-[13px]" onClick={(e) => e.stopPropagation()}>
        <span className="tabular-nums">{i + 1} / {shots.length}</span>
        <span className="text-white/70">at {shotTime(s)}{s.sensitive && ' · people/HR'}</span>
        {onJump && s.t != null && <button onClick={() => { onJump(s.t!); onClose() }} className="rounded-full border border-white/40 px-3 py-0.5 hover:border-white">Show in transcript</button>}
        <button onClick={onClose} aria-label="Close (Esc)" className="ml-auto grid size-7 place-items-center rounded-full hover:bg-white/10"><X size={18} /></button>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center px-12" onClick={(e) => e.stopPropagation()}>
        <button aria-label="Previous" disabled={i === 0} onClick={() => setI(i - 1)} className="absolute left-2 p-2 hover:bg-white/10 disabled:opacity-30"><ChevronLeft size={24} /></button>
        {s.available
          ? <img src={shotUrl(s.id)} alt={s.description} className="max-h-full max-w-full object-contain" />
          : <p className="max-w-[640px] text-center text-[14px] text-white/80">The image was deleted <RetentionDays /> days after the meeting. Granola's description is below.</p>}
        <button aria-label="Next" disabled={i === shots.length - 1} onClick={() => setI(i + 1)} className="absolute right-2 p-2 hover:bg-white/10 disabled:opacity-30"><ChevronRight size={24} /></button>
      </div>
      <p className="mx-auto max-w-[900px] px-4 py-3 text-[13px] leading-snug text-white/80" onClick={(e) => e.stopPropagation()}>{s.description}</p>
    </div>
  )
}

function Thumb({ s, onClick, className }: { s: Shot; onClick: () => void; className?: string }) {
  return (
    <button onClick={onClick} title={s.description} className={cn('group relative shrink-0 overflow-hidden border border-line bg-panel2 hover:border-ink', className)}>
      {s.available
        ? <img src={shotUrl(s.id, true)} alt={s.description} loading="lazy" className="h-full w-full object-cover" />
        : <span className="flex h-full w-full items-center justify-center p-1.5 text-left text-[11px] leading-tight text-ink2 [overflow-wrap:anywhere]">{s.description.slice(0, 90)}</span>}
      <span className="absolute bottom-0 left-0 bg-ink px-1 text-[10.5px] tabular-nums text-bg">{shotTime(s)}</span>
    </button>
  )
}

// meeting panel: a filmstrip of the meeting's screenshots
export function MeetingShots({ meetingId, Section }: { meetingId: string; Section: ComponentType<{ title: string; meta?: string; defaultOpen?: boolean; children: ReactNode }> }) {
  const q = useQuery({ queryKey: ['meeting-shots', meetingId], queryFn: () => api.meetingShots(meetingId) })
  const [open, setOpen] = useState<number | null>(null)
  const shots = q.data?.shots ?? []
  if (!shots.length) return null
  const kept = shots.filter((s) => s.available).length
  return (
    <Section title="On screen" meta={`${shots.length} screenshot${shots.length === 1 ? '' : 's'}${kept < shots.length ? ` · ${kept} images kept` : ''}`}>
      <div className="flex gap-1.5 overflow-x-auto pb-2">
        {shots.map((s, i) => <Thumb key={s.id} s={s} onClick={() => setOpen(i)} className="h-[72px] w-[128px]" />)}
      </div>
      <Link to="/meetings/$id" params={{ id: meetingId }} className="text-[12.5px]">See them in the transcript</Link>
      {open != null && <ShotViewer shots={shots} index={open} onClose={() => setOpen(null)} />}
    </Section>
  )
}

// transcript: screenshots captured between two turns, as one row
export function ShotRow({ shots, all, onOpen }: { shots: Shot[]; all: Shot[]; onOpen: (index: number) => void }) {
  return (
    <div className="grid grid-cols-[52px_minmax(0,1fr)] gap-3 py-1.5 pl-3">
      <div className="flex justify-end pt-1 text-ink2" title="On the shared screen"><Monitor size={14} aria-label="On the shared screen" /></div>
      <div className="flex flex-wrap gap-1.5">
        {shots.map((s) => <Thumb key={s.id} s={s} onClick={() => onOpen(all.indexOf(s))} className="h-[90px] w-[160px]" />)}
      </div>
    </div>
  )
}
