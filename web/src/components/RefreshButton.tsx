// The header's Refresh (top right) and its menu (Sam, 27 Oct 2026). The menu says how fresh SleePO is (live updates, when
// data was last pulled, when the agents last ran, the last refresh), which used to sit at the bottom of the sidebar, then
// offers Quick sync and Full refresh. While a refresh runs it shows the progress and its phases instead. The button is the
// one filled lime pill in the header, with a hot dot when live updates are off or the last refresh failed.
import { useEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, ChevronRight, Circle, Loader2, RefreshCw, X, Zap, type LucideIcon } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/util'
import { TZ, LOCALE } from '@/lib/time'
import { ConnectionIssues, alertLabel, useConnections } from './ConnectionAlert'

const mins = (secs: number) => (secs < 60 ? `${secs}s` : `${Math.round(secs / 60)} min`)
const MODE: Record<string, string> = { sync: 'Quick sync', full: 'Full refresh' }

// "today 18:04", "yesterday 09:12", "Mon 5 Oct 09:12" in Europe/London.
function when(iso: string) {
  const d = new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
  const day = (x: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(x)
  const t = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(d)
  const now = new Date(), y = new Date(now.getTime() - 86_400_000)
  if (day(d) === day(now)) return `today ${t}`
  if (day(d) === day(y)) return `yesterday ${t}`
  return new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' }).format(d) + ` ${t}`
}
// how long the last run took, from the server's local "2026-10-27 11:00:44" times
const took = (a: string | null, b: string | null) => {
  const s = a && b ? (Date.parse(b.replace(' ', 'T')) - Date.parse(a.replace(' ', 'T'))) / 1000 : NaN
  return Number.isFinite(s) && s >= 0 ? mins(Math.round(s)) : ''
}

function Row({ label, title, children }: { label: string; title?: string; children: React.ReactNode }) {
  return <div className="flex items-baseline gap-3" title={title}><span className="w-[92px] shrink-0 text-ink2">{label}</span><span className="min-w-0 flex-1 text-ink">{children}</span></div>
}

function Option({ icon: I, title, sub, time, onClick }: { icon: LucideIcon; title: string; sub: string; time: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="group flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-panel2 focus-visible:bg-panel2 focus-visible:outline-none">
      <span className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-panel2 text-ink transition-colors group-hover:bg-accent group-hover:text-onaccent"><I size={15} aria-hidden /></span>
      <span className="min-w-0 flex-1"><span className="flex items-baseline gap-2"><span className="text-[13.5px] font-semibold text-ink">{title}</span>
        <span className="ml-auto shrink-0 text-[11.5px] tabular-nums text-ink2">{time}</span></span>
        <span className="block text-[12px] leading-snug text-ink2">{sub}</span></span>
    </button>
  )
}

export function RefreshButton({ live }: { live: 'live' | 'reconnecting' }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [log, setLog] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const st = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: (q) => (q.state.data?.running ? 2000 : false) })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const d = st.data
  const running = !!d?.running
  const pct = Math.round((d?.progress ?? 0) * 100)
  const cur = d?.phases?.find((p) => p.status === 'running')
  const failed = !running && d?.ok === false
  const conn = useConnections()
  const urgent = (conn.data?.issues ?? []).filter((i) => i.urgent)   // a connector to sign in to again (assist/connections.py)
  const warn = live !== 'live' || failed || urgent.length > 0
  const start = async (mode: 'sync' | 'full') => { setOpen(false); await api.refresh(mode); qc.invalidateQueries({ queryKey: ['status'] }) }
  useEffect(() => {   // closes on a click outside it or Escape
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  useEffect(() => { if (!open) setLog(false) }, [open])
  const freshness = [meta.data?.last_data && `Data pulled ${when(meta.data.last_data)}`, meta.data?.last_agents && `Agents ran ${when(meta.data.last_agents)}`].filter(Boolean).join(' · ')
  const label = <><RefreshCw size={14} aria-hidden className={cn('shrink-0', running && 'animate-spin')} />
    <span className="hidden sm:inline">{running ? `${pct}%${d?.eta_secs != null ? ` · ~${mins(d.eta_secs)} left` : ''}` : 'Refresh'}</span></>
  return (
    <div ref={box} className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog"
        aria-label={running ? `Refreshing, ${pct}% done` : `Refresh${warn ? (live !== 'live' ? ', live updates off' : urgent.length ? `, ${alertLabel(urgent)}` : ', last refresh failed') : ''}`}
        title={running ? `${cur?.name ?? 'Working'} · ${pct}%${d?.eta_secs != null ? ` · about ${mins(d.eta_secs)} left` : ''}` : [urgent.length ? alertLabel(urgent) : '', freshness].filter(Boolean).join(' · ') || undefined}
        className={cn('relative inline-flex items-center justify-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-[filter,background-color]',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink',
          running ? 'min-w-[150px] bg-panel2 text-ink ring-1 ring-inset ring-line' : 'bg-accent text-onaccent hover:brightness-95 active:brightness-90')}>
        {running ? <>
          <span className="relative inline-flex items-center gap-1.5">{label}</span>
          {/* an accent-filled copy of the label clipped to the progress, so the text stays readable in both themes */}
          <span aria-hidden className="absolute inset-0 inline-flex items-center justify-center gap-1.5 bg-accent text-onaccent transition-[clip-path] duration-1000 ease-linear" style={{ clipPath: `inset(0 ${100 - Math.max(pct, 3)}% 0 0)` }}>{label}</span>
        </> : label}
        {warn && !running && <span aria-hidden className="absolute right-1.5 top-1 size-2 rounded-full bg-hot ring-2 ring-accent" />}
      </button>
      {open && (
        <div role="dialog" aria-label="Refresh" className="absolute right-0 top-[calc(100%+8px)] z-50 w-[360px] max-w-[calc(100vw-24px)] overflow-hidden rounded-xl border border-line bg-panel text-[12.5px] text-ink shadow-lg">
          {/* what SleePO cannot reach comes first: the refresh cannot fix it (17 Nov 2026) */}
          <ConnectionIssues className="border-b border-line bg-hot/[0.04] px-4 pb-2.5 pt-3.5" />
          {running && d ? <div className="px-4 pb-3 pt-3.5">
            <div className="flex items-baseline gap-2"><b className="text-[13.5px]">{MODE[d.mode ?? ''] ?? 'Refreshing'}</b>
              <span className="ml-auto tabular-nums text-ink2">{d.elapsed_secs != null && `${mins(d.elapsed_secs)} in`}{d.eta_secs != null && ` · ~${mins(d.eta_secs)} left`}</span></div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-panel2"><div className="h-full rounded-full bg-accent transition-[width] duration-1000 ease-linear" style={{ width: `${Math.max(pct, 3)}%` }} /></div>
            {d.phases && <ol className="mt-3 space-y-1">
              {d.phases.map((p) => <li key={p.name} className={cn('flex items-center gap-2', p.status === 'pending' || p.status === 'skipped' ? 'text-ink3' : 'text-ink', p.status === 'running' && 'font-semibold')}>
                {p.status === 'done' ? <Check size={13} aria-label="done" className="shrink-0" />
                  : p.status === 'running' ? <Loader2 size={13} aria-label="running" className="shrink-0 animate-spin" />
                  : p.status === 'failed' ? <X size={13} aria-label="failed" className="shrink-0 text-hot" />
                  : <Circle size={9} aria-label={p.status} className="mx-[2px] shrink-0" />}
                <span className="flex-1">{p.name}{p.status === 'skipped' && ' · skipped'}</span>
                <span className="font-normal tabular-nums text-ink2">{p.secs != null ? mins(p.secs) : p.status === 'running' && p.started ? 'now' : ''}</span></li>)}
            </ol>}
            {d.tools ? <div className="mt-2 text-[12px] text-ink2">{d.tools} connector and tool calls so far</div> : null}
          </div> : <>
            <div className="space-y-1 border-b border-line px-4 pb-3 pt-3.5">
              <div className={cn('mb-1.5 flex items-center gap-2 text-[13.5px] font-semibold', live !== 'live' && 'text-hot')}>
                <span aria-hidden className={cn('size-2 rounded-full', live === 'live' ? 'bg-accent ring-1 ring-ink/30' : 'animate-pulse bg-hot')} />
                {live === 'live' ? 'Live updates on' : 'Reconnecting to SleePO…'}
              </div>
              {meta.data?.last_data && <Row label="Data pulled" title="Last time any source (Granola, mail, calendar, Salesforce, files…) was pulled into the database">{when(meta.data.last_data)}</Row>}
              {meta.data?.last_agents && <Row label="Agents ran" title="Last time the Claude agents ran (full refresh, brief, prep, mail, Salesforce)">{when(meta.data.last_agents)}</Row>}
              {d?.finished && <Row label="Last refresh">{MODE[d.mode ?? ''] ?? 'Refresh'} · {d.finished.slice(11, 16)}{took(d.started, d.finished) && ` · ${took(d.started, d.finished)}`}
                {' · '}<span className={d.ok ? '' : 'font-semibold text-hot'}>{d.ok ? 'ok' : 'failed'}</span></Row>}
            </div>
            <div className="p-1.5">
              <Option icon={Zap} title="Quick sync" time="about 1 min" onClick={() => start('sync')}
                sub="Calendar, Granola meetings, Apple Mail, local files and documents. No Teams or Slack." />
              <Option icon={Bot} title="Full refresh with Claude" time="about 25 min" onClick={() => start('full')}
                sub="Also Teams and Slack, then open items, initiatives, task suggestions, meeting briefs and follow-ups." />
            </div>
          </>}
          {d?.pulls && <div className="border-t border-line px-4 py-2.5">
            <div className="mb-1 font-semibold">Sources pulled in this run</div>
            <ul className="space-y-0.5">{Object.entries(d.pulls).map(([k, p]) => (
              <li key={k} className="flex items-start gap-2" title={p.note}>
                <span aria-hidden className={cn('mt-[5px] inline-block size-2 shrink-0 rounded-full', p.ok ? 'bg-accent ring-1 ring-ink/30' : 'bg-hot')} />
                <span className="flex-1">{p.name}{!p.ok && <span className="block text-[11.5px] text-hot">not pulled: {p.note}</span>}</span>
                <span className="shrink-0 tabular-nums text-ink2">{p.ok ? `${p.pulled ?? 0} new` : ''}{p.newest ? ` · latest ${new Date(p.newest).toLocaleString(LOCALE, { timeZone: TZ, weekday: 'short', hour: '2-digit', minute: '2-digit' })}` : ''}</span>
              </li>))}</ul>
          </div>}
          <div className="flex items-center gap-1 border-t border-line bg-panel2/40 px-2.5 py-1.5 text-[12px]">
            <Link to="/sources" onClick={() => setOpen(false)} className="inline-flex items-center gap-0.5 rounded-full px-2 py-1 text-ink no-underline hover:bg-panel2">Sources<ChevronRight size={13} aria-hidden /></Link>
            <Link to="/agents" onClick={() => setOpen(false)} className="inline-flex items-center gap-0.5 rounded-full px-2 py-1 text-ink no-underline hover:bg-panel2">Agents<ChevronRight size={13} aria-hidden /></Link>
            {d?.log && <button onClick={() => setLog(!log)} aria-expanded={log} className="ml-auto rounded-full px-2 py-1 text-ink2 hover:bg-panel2 hover:text-ink">{log ? 'Hide log' : running ? 'Show log' : 'Last run’s log'}</button>}
          </div>
          {log && d?.log && <pre className="max-h-56 overflow-auto whitespace-pre-wrap border-t border-line bg-bg px-3 py-2 text-[11px] leading-snug text-ink2">{d.log.slice(-3000)}</pre>}
        </div>
      )}
    </div>
  )
}
