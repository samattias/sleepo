// Steps on the Mac that Ask SleePO asks to do (assist/desktop.py; Sam, 23 Nov 2026: "I want the assistant to be able to do
// tasks like this on my desktop ... so it asked me for approval to take action"). The chat runs ask-do and waits; this card
// shows its steps in plain words, with what each touches and any warning, and nothing happens until Sam allows them (all, or
// the ones he leaves ticked) or declines. Then it shows each step's outcome as the waiting command carries it out, with Show
// in Finder for what was made. Requests belong to the answer that asked (saved turns keep their ids; the live one is found by
// its run) and are polled while one waits or runs.
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Download, ExternalLink, FolderInput, FolderOpen, FolderPlus, Laptop, Loader2, Minus, Pencil, Trash2, TriangleAlert, X, type LucideIcon } from 'lucide-react'
import { api, type DesktopReq, type DesktopStep } from '@/lib/api'
import { cn } from '@/lib/util'
import { btnClass } from './ui'

const ICON: Record<DesktopStep['do'], LucideIcon> = { folder: FolderPlus, copy: Copy, move: FolderInput, rename: Pencil, trash: Trash2,
  download: Download, open: ExternalLink, show: FolderOpen }
const active = (r: DesktopReq) => r.status === 'pending' || r.status === 'running'

export function DesktopRequests({ tid, ids, run, live }: { tid: string | null; ids?: string[]; run?: string; live: boolean }) {
  const q = useQuery({ queryKey: ['chatDesktop', tid], queryFn: () => api.chatDesktop(tid!), enabled: !!tid && (live || !!ids?.length),
    refetchInterval: (query) => live || (query.state.data?.requests ?? []).some(active) ? 1000 : false })
  const reqs = (q.data?.requests ?? []).filter((r) => ids?.includes(r.id) || (!!run && r.run === run))
  if (!reqs.length) return null
  return <div className="mt-3 flex flex-col gap-2" aria-label="Steps on your Mac">{reqs.map((r) => <DesktopCard key={r.id} r={r} />)}</div>
}

// A request still waiting or running whose answer is not on screen: the tab was reloaded, or the conversation reopened, while
// the chat waited for Sam. Shown at the end of the conversation so it can still be answered.
export function LooseRequests({ tid, known, runs = [] }: { tid: string | null; known: string[]; runs?: string[] }) {
  const q = useQuery({ queryKey: ['chatDesktop', tid], queryFn: () => api.chatDesktop(tid!), enabled: !!tid,
    refetchInterval: (query) => (query.state.data?.requests ?? []).some(active) ? 1000 : false })
  const reqs = (q.data?.requests ?? []).filter((r) => active(r) && !known.includes(r.id) && !runs.includes(r.run))
  if (!reqs.length) return null
  return <div className="mb-7 ml-9 flex flex-col gap-2" aria-label="Steps on your Mac">{reqs.map((r) => <DesktopCard key={r.id} r={r} />)}</div>
}

const HEAD: Record<DesktopReq['status'], string> = { pending: 'Allow SleePO to do this on your Mac?', running: 'Working on it…', done: 'Done',
  declined: 'You declined: nothing was done', expired: 'Not answered in time: nothing was done', stopped: 'Stopped' }

function DesktopCard({ r }: { r: DesktopReq }) {
  const qc = useQueryClient()
  const [ticked, setTicked] = useState<number[]>(() => r.steps.map((_, i) => i))
  const [busy, setBusy] = useState<'' | 'allow' | 'decline'>('')
  const [err, setErr] = useState('')
  const waiting = r.status === 'pending' && !r.answer
  const failed = r.steps.some((s) => s.state === 'failed')
  const answer = async (approve: boolean) => {
    setBusy(approve ? 'allow' : 'decline'); setErr('')
    try { await api.chatDesktopDecide(r.id, approve, approve ? ticked : undefined) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(''); qc.invalidateQueries({ queryKey: ['chatDesktop', r.thread] }) }
  }
  const show = (i: number) => api.chatDesktopShow(r.id, i).catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  const toggle = (i: number) => setTicked((t) => t.includes(i) ? t.filter((x) => x !== i) : [...t, i].sort((a, b) => a - b))
  const n = ticked.length
  return (
    <div className={cn('rounded-xl border bg-panel px-3 py-2.5', waiting ? 'border-ink' : r.status === 'done' && !failed ? 'border-accent' : 'border-line',
      ['declined', 'expired'].includes(r.status) && 'opacity-70')}>
      <div className="flex items-start gap-2.5">
        <span className={cn('grid size-7 shrink-0 place-items-center rounded-lg', r.status === 'done' && !failed ? 'bg-accent text-onaccent' : 'bg-panel2 text-ink')}>
          {r.status === 'running' ? <Loader2 size={14} className="animate-spin" aria-hidden /> : r.status === 'done' && !failed ? <Check size={14} aria-hidden /> : <Laptop size={14} aria-hidden />}</span>
        <div className="min-w-0 flex-1 text-[13px] leading-snug">
          <div className="font-semibold text-ink">{r.status === 'done' && failed ? 'Done, with a problem' : HEAD[r.status]}</div>
          {r.why && <div className="mt-0.5 text-[12px] text-ink2">{r.why}</div>}
        </div>
      </div>
      <ol className="mt-2 flex flex-col gap-1.5">
        {r.steps.map((s, i) => <Step key={i} s={s} i={i} waiting={waiting} on={ticked.includes(i)} toggle={() => toggle(i)} show={() => show(i)} />)}
      </ol>
      {err && <div className="mt-1.5 text-[12px] text-hot">{err}</div>}
      {waiting && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <button onClick={() => answer(true)} disabled={!!busy || !n} className={btnClass('primary', 'sm')}>
            {busy === 'allow' ? 'Allowing…' : n === r.steps.length ? (n === 1 ? 'Allow' : `Allow all ${n}`) : `Allow ${n} of ${r.steps.length}`}</button>
          <button onClick={() => answer(false)} disabled={!!busy} className={btnClass('ghost', 'sm')}>{busy === 'decline' ? 'Declining…' : "Don't allow"}</button>
          <span className="text-[11.5px] text-ink3">Nothing happens until you allow it{r.steps.length > 1 ? '; untick a step to leave it out' : ''}.</span>
        </div>)}
    </div>
  )
}

function Step({ s, i, waiting, on, toggle, show }: { s: DesktopStep; i: number; waiting: boolean; on: boolean; toggle: () => void; show: () => void }) {
  const Icon = ICON[s.do] ?? Laptop
  const mark = s.state === 'done' ? <Check size={13} className="text-ink" aria-label="done" />
    : s.state === 'failed' ? <X size={13} className="text-hot" aria-label="failed" />
    : s.state === 'running' ? <Loader2 size={13} className="animate-spin text-ink" aria-label="working" />
    : s.state === 'skipped' ? <Minus size={13} className="text-ink3" aria-label="not done" /> : null
  const [open, setOpen] = useState(false)
  const many = s.detail.length > 2
  return (
    <li className={cn('flex items-start gap-2 rounded-lg px-1.5 py-1', waiting && !on && 'opacity-50')}>
      {waiting
        ? <input type="checkbox" checked={on} onChange={toggle} aria-label={`Include step ${i + 1}: ${s.label}`} className="mt-[3px] size-3.5 shrink-0 accent-[var(--ink)]" />
        : <span className="mt-[2px] grid size-3.5 shrink-0 place-items-center">{mark}</span>}
      <Icon size={14} className="mt-[2px] shrink-0 text-ink2" aria-hidden />
      <div className="min-w-0 flex-1 text-[12.5px] leading-snug">
        <div className="text-ink">{s.label}</div>
        {s.detail.length > 0 && <div className="mt-0.5 flex flex-col text-[11.5px] text-ink3">
          {(many && !open ? s.detail.slice(0, 2) : s.detail).map((d, j) => <span key={j} className="truncate" title={d}>{d}</span>)}
          {many && <button onClick={() => setOpen(!open)} className="self-start text-ink2 hover:text-ink">{open ? 'Fewer' : `and ${s.detail.length - 2} more`}</button>}
        </div>}
        {s.warn && <div className="mt-0.5 flex items-start gap-1 text-[11.5px] text-hot"><TriangleAlert size={12} className="mt-px shrink-0" aria-hidden />{s.warn}</div>}
        {s.progress && s.state === 'running' && <div className="mt-0.5 text-[11.5px] text-ink2">{s.progress}</div>}
        {s.state === 'done' && s.result && <div className="mt-0.5 text-[11.5px] text-ink2">{s.result[0].toUpperCase() + s.result.slice(1)}</div>}
        {s.state === 'failed' && s.error && <div className="mt-0.5 text-[11.5px] text-hot">{s.error[0].toUpperCase() + s.error.slice(1)}</div>}
      </div>
      {s.state === 'done' && !!s.out?.length && s.do !== 'show' && s.do !== 'open' &&
        <button onClick={show} title="Show in Finder" aria-label={`Show the result of step ${i + 1} in Finder`} className={btnClass('ghost', 'icon', 'text-ink2')}><FolderOpen size={14} /></button>}
    </li>
  )
}
