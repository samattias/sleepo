// Tasks › History (Sam, 23 Oct 2026; assist/task_history.py): the tasks Sam would have had, rebuilt from what he actually
// did (sent mail, Teams and Slack messages, meetings, documents, promises), week by week, each with its steps and the
// actions that did them, all done. Sam renames, refiles, merges, splits, takes an action out or removes a task; his edits
// are kept when the history is rebuilt and are the reference for measuring task suggestions. Task suggestions read this
// history to propose work shaped like what he really does. Kept RETENTION_DAYS, like the mail it comes from.
import { useState, type ComponentType } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck, CalendarPlus, Check, ChevronDown, ChevronRight, FileText, Gavel, Handshake, Hash, Mail, MessageSquare, Merge, Pencil, RefreshCw, RotateCcw, Split, Trash2, Users, X } from 'lucide-react'
import { api, type HistoryAction, type HistoryStep, type HistoryTask, type TasksData } from '@/lib/api'
import { cn } from '@/lib/util'
import { day } from '@/lib/time'
import { btnClass, Empty, inputClass, Loading, Tag } from '@/components/ui'

const ICON: Record<string, ComponentType<{ size?: number; className?: string }>> = {
  email_new: Mail, email_reply: Mail, email_forward: Mail, teams_dm: MessageSquare, teams_group: MessageSquare, teams_channel: MessageSquare,
  slack_dm: Hash, slack_channel: Hash, meeting_hold: Users, meeting_schedule: CalendarPlus, doc_create: FileText, decide: Gavel, commit: Handshake,
}
const TYPE: Record<string, string> = {
  email_new: 'Email', email_reply: 'Reply', email_forward: 'Forward', teams_dm: 'Teams', teams_group: 'Teams group', teams_channel: 'Teams channel',
  slack_dm: 'Slack', slack_channel: 'Slack channel', meeting_hold: 'Meeting', meeting_schedule: 'Scheduled', doc_create: 'Document', decide: 'Decision', commit: 'Promise',
}
const weekLabel = (w: string) => `Week of ${day(w)}`
const span = (t: HistoryTask) => { const a = day(t.started_at), b = day(t.finished_at); return a === b ? a : `${a} – ${b}` }

export function TaskHistory({ data }: { data: TasksData }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['task-history'], queryFn: api.taskHistory, refetchInterval: (x) => (x.state.data?.job.running ? 15_000 : false) })
  const ev = useQuery({ queryKey: ['task-history-eval'], queryFn: api.taskHistoryEval, staleTime: 60_000 })
  const [err, setErr] = useState('')
  const [merging, setMerging] = useState<HistoryTask | null>(null)
  const [removed, setRemoved] = useState<HistoryTask | null>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['task-history'] }); qc.invalidateQueries({ queryKey: ['task-history-eval'] }) }
  const run = async (f: () => Promise<unknown>) => { setErr(''); try { await f(); refresh() } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } }
  if (q.isLoading) return <Loading label="Reading your history" />
  const h = q.data
  if (!h) return <Empty>The history could not be read.</Empty>
  const weeks = h.weeks.filter((w) => w.tasks.length || w.status === 'error')
  const total = weeks.reduce((n, w) => n + w.tasks.length, 0)
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <p className="max-w-[720px] text-[13px] text-ink2">
          The tasks you would have had, rebuilt from what you did: the mail you sent, your Teams and Slack messages, meetings, documents and promises,
          grouped into outcomes with their steps. SleePO suggests new tasks shaped like these. Fix any that are wrong (rename, merge, split, take an action out,
          remove): your corrections are kept and are what suggestions are measured against. Kept {h.retention_days} days, like the mail they come from.
        </p>
        <button onClick={() => run(() => api.taskHistoryBuild())} disabled={h.job.running || !h.pending.length} className={btnClass('outline', 'md', 'ml-auto')}
          title={h.pending.length ? `${h.pending.length} week${h.pending.length > 1 ? 's' : ''} not built yet; one run each, about 4 minutes` : 'Every complete week is built'}>
          <RefreshCw size={14} className={cn(h.job.running && 'animate-spin')} aria-hidden />
          {h.job.running ? 'Building…' : h.pending.length ? `Build ${h.pending.length} week${h.pending.length > 1 ? 's' : ''}` : 'Up to date'}
        </button>
      </div>
      <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink2">
        <span>{total} past tasks over {weeks.length} weeks</span>
        {ev.data && ev.data.suggestions_answered > 0 && <span title="Of the suggestions you accepted or dismissed in the last 30 days">
          Suggestions like your past work accepted {ev.data.accepted_when_like_history}, others {ev.data.accepted_otherwise}</span>}
        {ev.data && (ev.data.edited_by_sam > 0 || ev.data.removed_by_sam > 0) && <span>{ev.data.edited_by_sam} corrected · {ev.data.removed_by_sam} removed</span>}
        {h.job.running && <span className="text-ink">Building the weeks not done yet; new ones appear as they finish.</span>}
        {h.job.ok === false && !h.job.running && h.job.note && <span className="text-hot">The last build failed: {h.job.note}</span>}
      </div>
      {err && <div className="mb-3 border-l-2 border-hot bg-panel px-3 py-2 text-[13px]">{err}</div>}
      {removed && <div className="mb-3 flex items-center gap-2 border-l-2 border-line bg-panel px-3 py-2 text-[13px]">
        Removed “{removed.title}”. SleePO no longer learns from it.
        <button onClick={() => { const r = removed; setRemoved(null); run(() => api.taskHistoryEdit(r.id, { status: 'done' })) }} className={btnClass('outline', 'sm', 'ml-auto')}>
          <RotateCcw size={13} aria-hidden />Undo</button></div>}
      {merging && <div className="mb-3 flex items-center gap-2 border-l-2 border-accent bg-panel px-3 py-2 text-[13px]">
        Merge “{merging.title}” into another task: pick it below.
        <button onClick={() => setMerging(null)} className={btnClass('ghost', 'sm', 'ml-auto')}>Cancel</button></div>}
      {!weeks.length && <Empty>{h.job.running ? 'Building the first weeks…' : 'No history yet. Build it to rebuild your past tasks from what you did.'}</Empty>}
      <div className="flex flex-col gap-6">
        {weeks.map((w) => (
          <section key={w.week}>
            <h2 className="mb-2 text-[15px] font-semibold">{weekLabel(w.week)} <span className="font-normal text-ink2">· {w.tasks.length} task{w.tasks.length === 1 ? '' : 's'}
              {w.not_tasks ? ` · ${w.not_tasks} action${w.not_tasks === 1 ? '' : 's'} not part of a task` : ''}</span></h2>
            {w.status === 'error' && <div className="mb-2 text-[12.5px] text-hot">This week's build failed{w.error ? `: ${w.error}` : ''}. Build again to retry it.</div>}
            <div className="flex flex-col gap-2">
              {w.tasks.map((t) => <PastTask key={t.id} t={t} data={data} run={run} onRemove={() => { setRemoved(t); run(() => api.taskHistoryEdit(t.id, { status: 'removed' })) }}
                merging={merging} onMerge={() => setMerging(t)} onPick={() => { const m = merging; setMerging(null); if (m) run(() => api.taskHistoryMerge(m.id, t.id)) }} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

function PastTask({ t, data, run, merging, onMerge, onPick, onRemove }: { t: HistoryTask; data: TasksData; run: (f: () => Promise<unknown>) => void; onRemove: () => void
  merging: HistoryTask | null; onMerge: () => void; onPick: () => void }) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(t.title)
  const filed = t.initiative || data.areas.find((a) => a.key === t.area)?.name || t.area
  const n = t.steps.reduce((k, s) => k + s.actions.length, 0)
  const pickable = merging && merging.id !== t.id
  const refile = (v: string) => {
    const [kind, name] = v.split(':', 2)
    run(() => api.taskHistoryEdit(t.id, kind === 'i' ? { initiative: name, area: null } : { initiative: null, area: name }))
  }
  return (
    <article className={cn('border border-line bg-panel', pickable && 'cursor-pointer hover:border-ink')} onClick={pickable ? onPick : undefined}>
      <div className="flex items-start gap-3 px-4 py-2.5">
        <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-ink text-bg" title="Done"><Check size={12} aria-hidden /></span>
        <div className="min-w-0 flex-1">
          {editing
            ? <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setEditing(false); if (title.trim() && title !== t.title) run(() => api.taskHistoryEdit(t.id, { title: title.trim() })) }}>
                <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} className={cn(inputClass, 'min-w-0 flex-1 text-[14px]')} />
                <button className={btnClass('primary')}>Save</button><button type="button" onClick={() => { setEditing(false); setTitle(t.title) }} className={btnClass('ghost')}>Cancel</button>
              </form>
            : <button onClick={() => !pickable && setOpen(!open)} onDoubleClick={() => setEditing(true)} className="flex w-full items-start gap-1.5 text-left" aria-expanded={open}>
                <span className="flex-1 text-[14.5px] font-semibold leading-snug">{t.title}</span>
                {open ? <ChevronDown size={16} className="mt-0.5 shrink-0 text-ink3" aria-hidden /> : <ChevronRight size={16} className="mt-0.5 shrink-0 text-ink3" aria-hidden />}
              </button>}
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-ink2">
            {filed ? <Tag>{filed}</Tag> : <span className="text-ink3">Not filed</span>}
            <span>{span(t)}{t.days && t.days > 1 ? ` · ${t.days} days` : ''}</span>
            <span>· {t.steps.length} step{t.steps.length === 1 ? '' : 's'}, {n} action{n === 1 ? '' : 's'}</span>
            {t.people.length > 0 && <span>· with {t.people.slice(0, 3).join(', ')}{t.people.length > 3 ? ` +${t.people.length - 3}` : ''}</span>}
            {t.edited ? <span title="You changed this one; rebuilds keep it">· corrected</span> : null}
          </div>
          {t.done_when && open && <p className="mt-1 text-[13px] text-ink2">Done when: {t.done_when}</p>}
        </div>
      </div>
      {open && !pickable && (
        <div className="border-t border-line px-4 py-2.5">
          <ol className="flex flex-col gap-2">
            {t.steps.map((s) => <PastStep key={s.id} s={s} run={run} />)}
          </ol>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button onClick={() => setEditing(true)} className={btnClass('outline')}><Pencil size={13} aria-hidden />Rename</button>
            <select aria-label="File under" value="" onChange={(e) => e.target.value && refile(e.target.value)} className="rounded-full border border-line bg-bg px-3 py-1 text-[12.5px] text-ink">
              <option value="">File under…</option>
              <optgroup label="Initiatives">{data.initiatives.map((i) => <option key={i.id} value={`i:${i.name}`}>{i.name}</option>)}</optgroup>
              <optgroup label="Day-to-day">{data.areas.map((a) => <option key={a.key} value={`a:${a.name}`}>{a.name}</option>)}</optgroup>
            </select>
            <button onClick={onMerge} className={btnClass('outline')} title="Move its steps and actions into another past task"><Merge size={13} aria-hidden />Merge into…</button>
            <button onClick={onRemove} className={btnClass('ghost', 'sm', 'ml-auto text-ink2')}
              title="Not a task: SleePO stops learning from it"><Trash2 size={13} aria-hidden />Not a task</button>
          </div>
        </div>
      )}
    </article>
  )
}

function PastStep({ s, run }: { s: HistoryStep; run: (f: () => Promise<unknown>) => void }) {
  return (
    <li className="group">
      <div className="flex items-start gap-2 text-[13.5px]">
        <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-ink3" aria-hidden />
        <span className="flex-1">{s.title}{s.owner && <span className="text-ink2"> · {s.owner}</span>}</span>
        <button onClick={() => run(() => api.taskHistorySplit(s.id))} title="Make this step a task of its own"
          className="invisible shrink-0 text-ink3 hover:text-ink group-hover:visible"><Split size={13} aria-label="Split into its own task" /></button>
      </div>
      <div className="ml-3.5 mt-1 flex flex-wrap gap-1.5">
        {s.actions.map((a) => <ActionChip key={a.ref} a={a} onRemove={() => run(() => api.taskHistoryMove(a.ref, null))} />)}
      </div>
    </li>
  )
}

function ActionChip({ a, onRemove }: { a: HistoryAction; onRemove: () => void }) {
  const Icon = ICON[a.key] ?? CalendarCheck
  const body = <><Icon size={12} className="shrink-0" aria-hidden /><span className="truncate">{TYPE[a.key] ?? a.key} · {a.label}</span><span className="shrink-0 text-ink3">{day(a.ts)}</span></>
  return (
    <span className="inline-flex max-w-[420px] items-center gap-1 rounded-full border border-line bg-bg pl-2 pr-1 py-0.5 text-[12px] text-ink2">
      {a.url ? <a href={a.url} target={a.url.startsWith('#') ? undefined : '_blank'} rel="noreferrer" className="inline-flex min-w-0 items-center gap-1 text-ink2 no-underline hover:text-ink">{body}</a>
        : <span className="inline-flex min-w-0 items-center gap-1">{body}</span>}
      <button onClick={onRemove} title="Not part of this task" aria-label="Take out of this task" className="shrink-0 rounded-full p-0.5 text-ink3 hover:bg-panel2 hover:text-ink"><X size={11} /></button>
    </span>
  )
}
