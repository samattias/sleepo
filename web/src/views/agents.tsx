// Agents: everything SleePO runs for Sam. What is running now (with its live log), every agent with a Run button and its
// last run, and the recent activity. Logs come from /api/agents/<key>/log: the full refresh's live log, or the latest
// run started from this page (assist/agent_runner.py). Nothing here sends anything.
import { useEffect, useMemo, useRef, useState } from 'react'
import { AgentTabs } from '@/components/AgentTabs'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowUpRight, Bot, CheckCircle2, ChevronDown, CircleAlert, CircleDot, ClipboardCopy, FileText, Link2, ListTodo, Loader2, Mail, MessagesSquare, NotebookPen, Play, RefreshCw, Reply, Sun, Target, TerminalSquare, TrendingUp, type LucideIcon, Lightbulb } from 'lucide-react'
import { api, type AgentInfo, type AgentRunning } from '@/lib/api'
import { useAgents } from '@/lib/agents'
import { cn } from '@/lib/util'
import { btnClass, Loading } from '@/components/ui'
import { TZ, LOCALE } from '@/lib/time'

const at = (s?: string | null) => (s ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s) ? s : s.replace(' ', 'T') + (s.includes('T') ? 'Z' : '')) : null)
const ago = (s?: string | null) => {
  const d = at(s); if (!d || isNaN(+d)) return '—'
  const m = Math.round((Date.now() - +d) / 60000)
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
}
const clock = (s?: string | null) => { const d = at(s); return d && !isNaN(+d) ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(d) : '—' }
const dayOf = (s?: string | null) => { const d = at(s); return d && !isNaN(+d) ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'short' }).format(d) : '' }
const dur = (secs?: number | null) => (secs == null ? '—' : secs < 60 ? `${secs}s` : secs < 3600 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${Math.floor(secs / 3600)}h ${Math.round((secs % 3600) / 60)}m`)

// A terminal-style log: follows the end while you are at the bottom, polls while open.
function LogPanel({ agentKey, live }: { agentKey: string; live: boolean }) {
  const q = useQuery({ queryKey: ['agentLog', agentKey], queryFn: () => api.agentLog(agentKey), refetchInterval: (s) => (live || s.state.data?.running ? 2000 : false) })
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  useEffect(() => { const el = box.current; if (el && stick.current) el.scrollTop = el.scrollHeight }, [q.data?.lines.length])
  const lines = q.data?.lines ?? []
  const copy = () => navigator.clipboard?.writeText(lines.join('\n'))
  return (
    <div className="mt-3 border border-ink bg-ink text-bg">
      <div className="flex items-center gap-2 border-b border-bg/15 px-3 py-1.5 text-[11.5px] opacity-80">
        <TerminalSquare size={13} aria-hidden />
        <span>{q.data?.source === 'refresh' ? 'Full refresh log' : q.data?.source === 'manual' ? `Last run started ${clock(q.data.started)}` : 'Log'}</span>
        {q.data?.running && <span className="inline-flex items-center gap-1"><Loader2 size={11} className="animate-spin" />live</span>}
        <span className="ml-auto">{lines.length} lines</span>
        <button onClick={copy} title="Copy the log" className="inline-flex items-center gap-1"><ClipboardCopy size={12} />Copy</button>
      </div>
      <div ref={box} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24 }}
        className="max-h-[380px] overflow-auto px-3 py-2 font-mono text-[11.5px] leading-[1.55]">
        {!q.data ? <div className="opacity-60">Loading…</div> : lines.length === 0 ? <div className="opacity-60">No log yet.</div>
          : lines.map((l, i) => {
            const t = l.replace(/^\d\d:\d\d:\d\d /, '')
            return <div key={i} className={cn('whitespace-pre-wrap [overflow-wrap:anywhere]',
              /^\$ /.test(t) ? 'font-semibold text-accent' : /\b(error|failed|Traceback)\b|^!!/i.test(t.trim()) || /\(exit [1-9]/.test(t) ? 'text-hot' : /^\s*→/.test(t) ? 'opacity-60' : /^\(exit 0\)|Finished OK/.test(t) ? 'opacity-50' : '')}>{l}</div> })}
      </div>
    </div>
  )
}

// One icon per agent, matching the sidebar page it feeds where there is one.
const ICON: Record<string, LucideIcon> = { refresh: RefreshCw, mail: Mail, chat: MessagesSquare, salesforce: TrendingUp, linking: Link2, loops: CircleDot,
  initiatives: Target, todo: ListTodo, prep: NotebookPen, brief: Sun, replies: Reply, docs: FileText, strategy: Lightbulb }
function AgentIcon({ k, size = 16 }: { k: string; size?: number }) {
  const I = ICON[k] ?? Bot
  return <span className="inline-flex shrink-0 items-center justify-center border border-line bg-panel2" style={{ width: size + 10, height: size + 10 }}><I size={size} aria-hidden /></span>
}
const avg = (a?: Pick<AgentInfo, 'avg_secs' | 'avg_n'>) => (a?.avg_secs == null ? null : a.avg_secs < 1 ? 'under a second' : a.avg_secs < 60 ? `${a.avg_secs}s` : dur(a.avg_secs))

function StatusDot({ a }: { a: Pick<AgentInfo, 'running' | 'ok'> }) {
  if (a.running) return <Loader2 size={15} className="shrink-0 animate-spin" aria-label="running" />
  return <span aria-label={a.ok === false ? 'failed' : a.ok ? 'ok' : 'not run yet'} className={cn('size-2.5 shrink-0 rounded-full', a.ok === false ? 'bg-hot' : a.ok ? 'bg-accent ring-1 ring-ink/25' : 'border border-ink3')} />
}

function RunningCard({ r, info }: { r: AgentRunning; info?: AgentInfo }) {
  const canLog = r.key === 'refresh' || !!r.manual || !!info?.has_log
  const [log, setLog] = useState(r.key === 'refresh' || !!r.manual)
  const phases = r.phases ?? []
  const doneN = phases.filter((p) => p.status === 'done' || p.status === 'skipped').length
  return (
    <section className="border border-ink bg-panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3">
        <AgentIcon k={r.key} size={15} />
        <Loader2 size={15} className="shrink-0 animate-spin" aria-hidden />
        <span className="text-[15px] font-semibold">{info?.name ?? 'Claude'}</span>
        <span className="text-[13.5px] text-ink2">{r.what}</span>
        <span className="ml-auto text-[12.5px] tabular-nums text-ink2">{dur(r.elapsed)}{r.eta_secs ? ` · about ${dur(r.eta_secs)} left` : avg(info) ? ` · usually ${avg(info)}` : ''}</span>
      </div>
      {r.progress != null && <div className="mx-4 mt-2.5 h-1 bg-panel2"><div className="h-full bg-accent transition-all" style={{ width: `${Math.round(r.progress * 100)}%` }} /></div>}
      {phases.length > 0 && (
        <ol className="mx-4 mt-2.5 flex flex-wrap items-center gap-x-1 gap-y-1 text-[11.5px]">
          {phases.map((p, i) => (
            <li key={p.name} className="inline-flex items-center gap-1">
              <span className={cn('inline-flex items-center gap-1', p.status === 'running' ? 'font-semibold text-ink' : p.status === 'done' ? 'text-ink2' : p.status === 'failed' ? 'text-hot' : 'text-ink3')}>
                {p.status === 'running' ? <Loader2 size={10} className="animate-spin" /> : p.status === 'done' ? <CheckCircle2 size={10} /> : p.status === 'failed' ? <CircleAlert size={10} /> : <span className="size-1.5 rounded-full border border-ink3" />}
                {p.name}</span>
              {i < phases.length - 1 && <span className="px-0.5 text-ink3">›</span>}
            </li>))}
          <li className="ml-1 text-ink2">· {doneN}/{phases.length}</li>
        </ol>)}
      <div className="flex items-center gap-3 px-4 py-2.5 text-[12.5px]">
        {canLog ? <button onClick={() => setLog(!log)} className="inline-flex items-center gap-1 font-medium"><ChevronDown size={13} className={cn('transition-transform', !log && '-rotate-90')} />{log ? 'Hide log' : 'Show log'}</button>
          : <span className="text-ink2">No log captured.</span>}
        {info?.page && <Link to={info.page} className="inline-flex items-center gap-0.5">Open {info.name.toLowerCase()} <ArrowUpRight size={12} /></Link>}
      </div>
      {log && canLog && <div className="px-4 pb-4"><LogPanel agentKey={r.key} live /></div>}
    </section>
  )
}

function AgentCard({ a, onRun, starting, error }: { a: AgentInfo; onRun: () => void; starting: boolean; error?: string }) {
  const [log, setLog] = useState(false)
  const disabled = a.running || starting || !a.runnable
  return (
    <section className={cn('flex flex-col border bg-panel', a.ok === false && !a.running ? 'border-hot' : 'border-line')}>
      <div className="flex-1 px-4 pt-3">
        <div className="flex items-center gap-2">
          <AgentIcon k={a.key} />
          <StatusDot a={a} />
          <Link to={a.page} className="text-[14.5px] font-semibold text-ink no-underline hover:underline">{a.name}</Link>
          <span className="ml-auto text-[12px] text-ink2">{a.runs_24h ? `${a.runs_24h} run${a.runs_24h > 1 ? 's' : ''} in 24 h` : ''}</span>
        </div>
        <p className="mt-1 text-[13px] leading-snug text-ink2">{a.what}</p>
        <dl className="mt-2 grid grid-cols-[52px_1fr] gap-x-2 gap-y-0.5 text-[12.5px]">
          <dt className="text-ink2">Runs</dt><dd>{a.trigger}</dd>
          <dt className="text-ink2">Takes</dt><dd>{avg(a) ? <>{a.avg_secs && a.avg_secs >= 1 ? 'about ' : ''}{avg(a)} on average <span className="text-ink2">· last {a.avg_n} run{a.avg_n === 1 ? '' : 's'}</span></> : <span className="text-ink2">not timed yet</span>}</dd>
          <dt className="text-ink2">Last</dt>
          <dd>{a.running ? <b>running now</b> : (a.last ?? a.manual?.finished) ? <>{ago(a.last ?? a.manual?.finished)} {a.ok === false ? <span className="font-medium text-hot">· failed</span> : a.ok ? <span className="text-ink2">· OK</span> : null}</> : <span className="text-ink2">not run yet</span>}</dd>
        </dl>
        {a.ok === false && !a.running && a.error && <p className="mt-1.5 line-clamp-2 text-[12px] text-hot">{a.error}</p>}
        {error && <p className="mt-1.5 text-[12px] text-hot">{error}</p>}
      </div>
      <div className="mt-3 flex items-center gap-3 border-t border-line2 px-4 py-2">
        <button onClick={onRun} disabled={disabled} title={!a.runnable ? (a.not_runnable ?? '') : a.running ? 'Already running' : `Run ${a.name.toLowerCase()} now`}
          className={btnClass('outline', 'sm', disabled && 'text-ink3 hover:border-line')}>
          {starting || a.running ? <Loader2 size={13} className="animate-spin" /> : <Play size={12} />}{a.running ? 'Running' : starting ? 'Starting…' : a.runnable ? 'Run now' : a.not_runnable}</button>
        {(a.has_log || a.running) && <button onClick={() => setLog(!log)} className="inline-flex items-center gap-1 text-[12.5px] font-medium"><TerminalSquare size={13} />{log ? 'Hide log' : 'Log'}</button>}
        <Link to={a.page} className="ml-auto inline-flex items-center gap-0.5 text-[12.5px]">Open <ArrowUpRight size={12} /></Link>
      </div>
      {log && <div className="px-4 pb-4"><LogPanel agentKey={a.key} live={a.running} /></div>}
    </section>
  )
}

// Model spend per purpose (from llm_calls): which agents cost what, on which model.
function Spend() {
  const q = useQuery({ queryKey: ['llm-costs'], queryFn: () => api.llmCosts(7), refetchInterval: 60000 })
  const rows = q.data?.by_purpose ?? []
  if (!rows.length) return null
  const total = rows.reduce((a, r) => a + (r.cost_usd ?? 0), 0)
  return <>
    <h2 className="mb-2 text-[16px] font-semibold">Model use, last 7 days <span className="text-[13px] font-normal text-ink2">· about ${total.toFixed(2)}</span></h2>
    <div className="mb-6 overflow-x-auto border border-line bg-panel px-3 py-1">
      <table className="w-full border-collapse text-[13px]">
        <thead><tr className="text-left text-[12px] text-ink2 [&>th]:border-b [&>th]:border-line [&>th]:px-2 [&>th]:py-2 [&>th]:font-semibold"><th>Purpose</th><th>Model</th><th className="text-right">Calls</th><th className="text-right">Avg time</th><th className="text-right">Tokens in / out</th><th className="text-right">Cost</th></tr></thead>
        <tbody className="[&>tr>td]:border-b [&>tr>td]:border-line2 [&>tr>td]:px-2 [&>tr>td]:py-2">
          {rows.map((r) => <tr key={`${r.purpose}-${r.model}`}><td className="font-medium">{r.purpose}</td><td className="text-ink2">{r.model ?? 'default'}</td>
            <td className="text-right tabular-nums">{r.calls}{r.ok < r.calls ? <span className="text-hot"> · {r.calls - r.ok} failed</span> : null}</td>
            <td className="text-right tabular-nums">{r.avg_secs != null ? `${r.avg_secs}s` : '—'}</td>
            <td className="text-right tabular-nums text-ink2">{Math.round((r.in_tokens ?? 0) / 1000)}k / {Math.round((r.out_tokens ?? 0) / 1000)}k</td>
            <td className="text-right tabular-nums">{r.cost_usd != null ? `$${r.cost_usd.toFixed(2)}` : '—'}</td></tr>)}
        </tbody>
      </table>
    </div>
  </>
}

export function Agents() {
  const q = useAgents()
  const qc = useQueryClient()
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [openRow, setOpenRow] = useState<number | null>(null)
  const run = useMutation({
    mutationFn: (key: string) => api.agentRun(key),
    onMutate: (key) => setErrs((e) => ({ ...e, [key]: '' })),
    onError: (e, key) => setErrs((x) => ({ ...x, [key]: String(e).replace(/^Error: /, '') })),
    onSettled: (_d, _e, key) => { qc.invalidateQueries({ queryKey: ['agents'] }); qc.invalidateQueries({ queryKey: ['agentLog', key] }) },
  })
  const sync = useMutation({ mutationFn: () => fetch('/refresh?mode=sync', { method: 'POST' }), onSettled: () => qc.invalidateQueries({ queryKey: ['agents'] }) })
  const log = q.data?.log
  const days = useMemo(() => {
    const g: { day: string; rows: NonNullable<typeof log> }[] = []
    for (const r of log?.slice(0, 50) ?? []) { const d = dayOf(r.started); if (g.at(-1)?.day !== d) g.push({ day: d, rows: [] }); g.at(-1)!.rows.push(r) }
    return g
  }, [log])
  if (!q.data) return <Loading />
  const { running, agents } = q.data
  const byKey = Object.fromEntries(agents.map((a) => [a.key, a]))
  const failed = agents.filter((a) => a.ok === false && !a.running)
  const refresh = byKey['refresh']
  const refreshing = running.some((r) => r.key === 'refresh')

  return (
    <div className="max-w-[1100px]">
      <AgentTabs active="agents" right={<>
          <button onClick={() => sync.mutate()} disabled={refreshing || sync.isPending} title="Granola, mail from Apple Mail, local files and documents; no Claude"
            className={btnClass('outline', 'md')}><RefreshCw size={13} />Quick sync</button>
          <button onClick={() => run.mutate('refresh')} disabled={refreshing || (run.isPending && run.variables === 'refresh')}
            className={btnClass('primary', 'md')}>
            {refreshing ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}{refreshing ? 'Refreshing…' : 'Run full refresh'}</button></>} />
      <p className="mb-5 text-[13.5px] text-ink2">
        <b className="text-ink">{running.length}</b> running · <b className={failed.length ? 'text-hot' : 'text-ink'}>{failed.length}</b> failed on the last run
        {refresh?.last && <> · last full refresh {ago(refresh.last)}{refresh.ok === false ? ' (failed)' : ''}{avg(refresh) ? ` · usually ${avg(refresh)}` : ''}</>}
      </p>
      {errs.refresh && <p className="-mt-3 mb-4 text-[12.5px] text-hot">{errs.refresh}</p>}

      <h2 className="mb-2 text-[16px] font-semibold">Running now</h2>
      {running.length === 0 ? <div className="mb-6 border border-dashed border-line px-4 py-3 text-[13.5px] text-ink2">Nothing running.</div>
        : <div className="mb-6 space-y-3">{running.map((r, i) => <RunningCard key={`${r.key}-${i}`} r={r} info={byKey[r.key]} />)}</div>}

      <h2 className="mb-2 text-[16px] font-semibold">All agents <span className="text-[13px] font-normal text-ink2">· {agents.length - 1}</span></h2>
      <div className="mb-6 grid gap-3 md:grid-cols-2">
        {agents.filter((a) => a.key !== 'refresh').map((a) => <AgentCard key={a.key} a={a} onRun={() => run.mutate(a.key)} starting={run.isPending && run.variables === a.key} error={errs[a.key]} />)}
      </div>

      <Spend />
      <h2 className="mb-2 text-[16px] font-semibold">Recent activity</h2>
      {days.length === 0 ? <p className="text-[13px] text-ink2">No runs recorded yet.</p> : (
        <div className="border border-line bg-panel">
          {days.map((g) => (
            <div key={g.day}>
              <div className="border-b border-line bg-panel2 px-4 py-1.5 text-[12.5px] font-semibold">{g.day}</div>
              {g.rows.map((r) => (
                <div key={r.id} className="border-b border-line2 last:border-b-0">
                  <button onClick={() => setOpenRow(openRow === r.id ? null : r.id)} className="flex w-full items-center gap-3 px-4 py-2 text-left text-[13px] hover:bg-panel2">
                    <span className="w-[42px] shrink-0 tabular-nums text-ink2">{clock(r.started)}</span>
                    {r.ok === false ? <CircleAlert size={14} className="shrink-0 text-hot" aria-label="failed" /> : r.ok ? <CheckCircle2 size={14} className="shrink-0 text-ink3" aria-label="ok" /> : <Loader2 size={14} className="shrink-0 animate-spin" aria-label="running" />}
                    <span className="w-[150px] shrink-0 truncate font-medium">{byKey[r.key]?.name ?? 'Other'}</span>
                    <span className={cn('min-w-0 flex-1 truncate', r.ok === false ? 'text-hot' : 'text-ink2')}>{r.error ?? r.agent}</span>
                    <span className="shrink-0 tabular-nums text-ink2">{dur(r.secs)}</span>
                    <ChevronDown size={13} className={cn('shrink-0 text-ink3 transition-transform', openRow !== r.id && '-rotate-90')} />
                  </button>
                  {openRow === r.id && (
                    <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1 bg-panel2 px-4 py-2.5 text-[12.5px]">
                      <dt className="text-ink2">Run</dt><dd className="font-mono text-[12px]">{r.agent} · #{r.id}</dd>
                      <dt className="text-ink2">Time</dt><dd>{clock(r.started)}{r.finished ? ` to ${clock(r.finished)}` : ', not finished'}{r.secs != null ? ` · ${dur(r.secs)}` : ''}</dd>
                      <dt className="text-ink2">Outcome</dt><dd className={r.ok === false ? 'text-hot' : ''}>{r.ok === false ? (r.error || 'failed') : r.ok ? 'OK' : 'running or unknown'}</dd>
                      {byKey[r.key]?.has_log && <><dt className="text-ink2">Log</dt><dd>On the {byKey[r.key].name} card above.</dd></>}
                    </dl>)}
                </div>))}
            </div>))}
        </div>)}
    </div>
  )
}
