// A task from an email (the Inbox's Create task tab) or a meeting (the follow-up panel's Make a task): SleePO proposes a task
// with steps and first actions from everything it knows around it (a tool-free run, assist/tasks.py propose), or adds steps to
// a task Sam already has. Sam edits it and saves; nothing is stored until he does. "Write it myself" skips the proposal. In the
// Inbox (pill) what SleePO should know is typed in the assistant pill at the bottom of the tab (Sam, 17 Nov 2026); the meeting
// panel keeps the box.
import { useEffect, useRef, useState, type RefObject } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, ListChecks, Plus, RefreshCw, Sparkles, X } from 'lucide-react'
import { api, type TaskArea, type TaskProposal, type TaskStepSpec, type TasksData } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { useJob } from '@/lib/useJob'
import { DictateButton } from './Dictate'
import { AssistPill } from './AssistPill'

const field = 'w-full rounded-lg border border-line bg-bg px-2.5 py-1.5 text-[13.5px] text-ink outline-none focus:border-ink'
const link = 'inline-flex items-center gap-1 text-[12px] text-ink2 underline decoration-line underline-offset-2 hover:text-ink hover:decoration-ink'

// Where a task is filed: one of Sam's initiatives (the bets) or a day-to-day area (work that keeps the business running but
// moves no bet: admin, team, one-off customer asks). Never both (assist/tasks.py).
export type Filing = { initiative_id: number | null; area: string | null }
export const filingLabel = (t: { initiative?: string | null; area_name?: string | null }) => t.initiative ?? (t.area_name ? `Day-to-day · ${t.area_name}` : 'Not filed')
export function FiledUnder({ value, onChange, initiatives, areas, className }: { value: Filing; onChange: (f: Filing) => void
  initiatives: TasksData['initiatives']; areas: TaskArea[]; className?: string }) {
  const v = value.initiative_id ? `i:${value.initiative_id}` : value.area ? `a:${value.area}` : ''
  return (
    <select aria-label="Filed under" title="An initiative (one of your bets), or a day-to-day area for work that moves no bet" value={v}
      onChange={(e) => { const x = e.target.value; onChange(x.startsWith('i:') ? { initiative_id: Number(x.slice(2)), area: null } : x.startsWith('a:') ? { initiative_id: null, area: x.slice(2) } : { initiative_id: null, area: null }) }}
      className={className}>
      <option value="">Not filed</option>
      <optgroup label="Initiatives">{initiatives.map((i) => <option key={i.id} value={`i:${i.id}`}>{i.name}</option>)}</optgroup>
      <optgroup label="Day-to-day">{areas.map((a) => <option key={a.key} value={`a:${a.key}`} title={a.hint}>{a.name}</option>)}</optgroup>
    </select>
  )
}

export function TaskCreator({ mailId, meetingId, title, askRef, pill }: { mailId?: number; meetingId?: string; title?: string; askRef?: RefObject<HTMLTextAreaElement | null>; pill?: boolean }) {
  const qc = useQueryClient()
  const data = useQuery({ queryKey: ['tasks'], queryFn: api.tasks, staleTime: 30_000 })
  const key = mailId ? `mail-${mailId}` : `meeting-${meetingId}`
  const [last, setLast] = usePersisted<string>(`assist-taskplan-last-${key}`, '')   // the last proposal's job (its file is kept a day)
  const [ask, setAsk] = useState('')
  const [starting, setStarting] = useState(false)
  const [err, setErr] = useState('')
  const [p, setP] = useState<TaskProposal | null>(null)
  const [saved, setSaved] = useState<number | null>(null)
  const origin = mailId ? 'mail' : 'meeting'
  const source = mailId ? [{ ref: `E${mailId}`, label: `Email: ${title ?? ''}`.slice(0, 90), url: `#/inbox?open=${mailId}`, item_id: mailId, closes: true }]
    : [{ ref: `G${meetingId}`, label: `Meeting: ${title ?? ''}`.slice(0, 90), url: `#/meetings/${meetingId}` }]

  // a running proposal is followed until it ends and picked up again on coming back (lib/useJob.ts: stops on unmount)
  const run = useJob(`assist-taskplan-${key}`, api.taskJob, {
    onDone: (j) => { if (j.proposal) setP(j.proposal); else setErr('No task came back') },
    onError: setErr,
  })
  const busy = starting || run.busy
  const jid = run.jobId || last
  // mail waiting on Sam: a task proposed in the background, like its recommended reply (assist/tasks.py preplan). It opens
  // filled in, once; until it is there, look again every 20 s
  const pre = useQuery({ queryKey: ['taskProposal', mailId], queryFn: () => api.taskProposal(mailId!), enabled: !!mailId,
    refetchInterval: (q) => (q.state.data?.pending ? 20_000 : false) })
  const [fromPre, setFromPre] = useState(false)
  const took = useRef(false)
  useEffect(() => {
    const d = pre.data
    if (took.current || jid || p || !d || d.status !== 'ok' || !d.proposal) return
    took.current = true; setP(d.proposal); setFromPre(true)
  }, [pre.data])   // eslint-disable-line react-hooks/exhaustive-deps
  const notATask = async () => { if (mailId) await api.taskProposalDismiss(mailId); setP(null); setFromPre(false); qc.invalidateQueries({ queryKey: ['taskProposal', mailId] }) }
  useEffect(() => {   // back on this email or meeting: the proposal from earlier today, if its file is still there
    if (!last || run.jobId) return
    let live = true
    api.taskJob(last).then((j) => { if (live && !j.running && j.ok && j.proposal) setP(j.proposal) }).catch(() => setLast(''))
    return () => { live = false }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  const propose = async (text = ask) => {
    if (busy) return
    setStarting(true); setErr(''); setSaved(null); setAsk(text)
    try {
      const { job } = await api.taskPropose(mailId ? { mail: mailId, ask: text } : { meeting: meetingId, ask: text })
      setLast(job); run.follow(job)
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setStarting(false)
  }
  const blank = () => { setSaved(null); setP({ title: title ?? '', done_when: '', why: '', initiative_id: null, area: null, priority: null, due: null, add_to: null, add_to_title: null, subtasks: [{ title: '' }], sources: source }) }
  const set = <K extends keyof TaskProposal>(k: K, v: TaskProposal[K]) => setP((x) => (x ? { ...x, [k]: v } : x))
  const setStep = (i: number, s: Partial<TaskStepSpec>) => setP((x) => (x ? { ...x, subtasks: x.subtasks.map((y, j) => (j === i ? { ...y, ...s } : y)) } : x))
  const save = async () => {
    if (!p) return
    setErr('')
    try {
      const subtasks = p.subtasks.filter((s) => s.title.trim())
      if (!p.add_to && !p.title.trim()) throw new Error('Give the task a title.')
      if (p.add_to && !subtasks.length) throw new Error('Add at least one step.')
      const { id } = await api.taskCreate({ ...p, subtasks, sources: p.sources?.length ? p.sources : source, origin })
      setSaved(id); setP(null); setLast(''); setFromPre(false)
      qc.invalidateQueries({ queryKey: ['taskProposal', mailId] })
      qc.invalidateQueries({ queryKey: ['tasks'] })
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
  }
  const open = (data.data?.tasks ?? []).filter((t) => t.status === 'open' || t.status === 'snoozed')

  return (
    <div aria-label="Create a task">
      <header className="flex items-start gap-2 border-b border-line px-4 py-2 text-[13px] text-ink2">
        <ListChecks size={15} className="mt-0.5 shrink-0" aria-hidden />
        <span>Turn this {mailId ? 'email' : 'meeting'} into a task with steps, or add steps to a task you have. SleePO proposes; you edit and save.{pill ? '' : ' Nothing is sent.'}</span>
        {pill && !p && <button onClick={blank} className={cn(link, 'ml-auto shrink-0')}>Write it myself</button>}
      </header>
      <div className="px-4 py-3">
        {!p && !saved && pre.data?.status === 'used' && pre.data.task_id && <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg bg-panel2 px-3 py-2 text-[13px]">
          <Check size={14} aria-hidden />A task was made from this email: <Link to="/tasks" search={{ open: pre.data.task_id }} className="font-medium">{pre.data.task_title}</Link></div>}
        {!p && pre.data?.pending && !busy && <div className="mb-2 flex items-center gap-2 rounded-lg bg-panel2 px-3 py-2 text-[12.5px] text-ink2">
          <RefreshCw size={13} aria-hidden className="animate-spin motion-reduce:animate-none" />Proposing a task in the background. It appears here, or propose one now.</div>}
        {!p && pill && <AssistPill inputRef={askRef}
          field={{ label: 'What should SleePO know for the task?', placeholder: busy ? 'Proposing… usually under a minute' : 'Anything SleePO should know? e.g. Priya owns the intake form. Optional' }}
          actions={[{ label: 'Propose a task', icon: Sparkles, busy, prompt: (t) => t, run: (t) => void propose(t), tip: 'SleePO proposes a task with steps, or steps for a task you have (Enter)' }]} />}
        {!p && !pill && <>
          <label htmlFor={`task-ask-${key}`} className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold"><Sparkles size={14} aria-hidden />Anything SleePO should know? (optional)</label>
          <div className="relative" data-dictate>
          <textarea id={`task-ask-${key}`} ref={askRef} value={ask} onChange={(e) => setAsk(e.target.value)} rows={2}
            onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void propose() } }}
            placeholder="e.g. Priya should own the intake form; I need it before the leadership meeting on Thursday."
            className="w-full resize-y rounded-lg border border-line bg-bg p-2.5 pr-10 text-[13.5px] leading-relaxed text-ink outline-none focus:border-ink" />
            <span className="absolute bottom-2 right-2"><DictateButton /></span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <button onClick={blank} className={link}>Write it myself</button>
            <button onClick={() => void propose()} disabled={busy} title="Propose a task (⌘↵)" className="ml-auto inline-flex items-center gap-2 rounded-full bg-accent px-4 py-1.5 text-[13.5px] font-medium text-onaccent hover:brightness-95 disabled:opacity-60">
              {busy ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />}{busy ? 'Reading everything around it…' : 'Propose a task'}</button>
          </div>
          {busy && <p className="mt-2 text-[12.5px] text-ink2">Usually under a minute.</p>}
        </>}
        {saved && <div className="mt-1 flex items-center gap-2 text-[13px]"><Check size={14} className="text-ink" aria-hidden />Saved to Tasks. <Link to="/tasks" search={{ open: saved }} className="font-medium">Open it</Link></div>}
        {err && <p className="mt-2 text-[13px] text-hot">{err}</p>}

        {p && fromPre && pre.data && <div className="mb-3 rounded-lg bg-panel2 px-3 py-2 text-[12.5px] text-ink2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full bg-accentbg px-2 text-[11.5px] font-semibold leading-[18px] text-ink"><Sparkles size={11} aria-hidden />Proposed for you</span>
            {pre.data.needs_task === false ? <span>A reply may be all this needs{pre.data.note ? `: ${pre.data.note}` : '.'}</span> : pre.data.note && <span>{pre.data.note}</span>}
            <button onClick={notATask} title="Not a task: don't propose one for this email again" className="ml-auto underline decoration-line underline-offset-2 hover:text-ink">Not a task</button>
          </div>
        </div>}
        {p && <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <span className="font-semibold">Where it goes</span>
            <select value={p.add_to ?? ''} onChange={(e) => { const v = e.target.value ? Number(e.target.value) : null; set('add_to', v); set('add_to_title', open.find((t) => t.id === v)?.title ?? null) }}
              className="max-w-full rounded-lg border border-line bg-bg px-2 py-1 text-[13px]">
              <option value="">A new task</option>
              {open.map((t) => <option key={t.id} value={t.id}>Add steps to: {t.title}</option>)}
            </select>
          </div>
          {!p.add_to && <>
            <input aria-label="Task" value={p.title} onChange={(e) => set('title', e.target.value)} placeholder="The outcome, e.g. 2027 P&E budget approved" className={cn(field, 'font-semibold')} />
            <input aria-label="Done when" value={p.done_when} onChange={(e) => set('done_when', e.target.value)} placeholder="Done when… e.g. my manager signs it off" className={field} />
            <div className="flex flex-wrap gap-2">
              <FiledUnder value={{ initiative_id: p.initiative_id, area: p.area }} onChange={(f) => setP((x) => (x ? { ...x, ...f } : x))}
                initiatives={data.data?.initiatives ?? []} areas={data.data?.areas ?? []} className="rounded-lg border border-line bg-bg px-2 py-1 text-[13px]" />
              <input aria-label="Due" type="date" value={p.due ?? ''} onChange={(e) => set('due', e.target.value || null)} className="rounded-lg border border-line bg-bg px-2 py-1 text-[13px]" />
              <select aria-label="Priority" value={p.priority ?? ''} onChange={(e) => set('priority', (e.target.value || null) as TaskProposal['priority'])} className="rounded-lg border border-line bg-bg px-2 py-1 text-[13px]">
                <option value="">No priority</option><option value="now">Now</option><option value="today">Today</option><option value="this_week">This week</option><option value="later">Later</option>
              </select>
            </div>
            {p.why && <p className="text-[13px] leading-snug text-ink2">{p.why}</p>}
          </>}
          <div>
            <div className="mb-1 text-[13px] font-semibold">Steps</div>
            <ol className="space-y-1.5">
              {p.subtasks.map((s, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span className="w-5 text-right text-[12px] tabular-nums text-ink2">{i + 1}</span>
                  <input aria-label={`Step ${i + 1}`} value={s.title} onChange={(e) => setStep(i, { title: e.target.value })} placeholder="Step" className={cn(field, 'min-w-[200px] flex-1')} />
                  <input aria-label={`Who does step ${i + 1}`} value={s.owner ?? ''} onChange={(e) => setStep(i, { owner: e.target.value || null })} placeholder="You" className={cn(field, 'w-36')} />
                  <input aria-label={`Due for step ${i + 1}`} type="date" value={s.due ?? ''} onChange={(e) => setStep(i, { due: e.target.value || null })} className="rounded-lg border border-line bg-bg px-2 py-1 text-[13px]" />
                  {(s.actions?.length ?? 0) > 0 && <span className="text-[12px] text-ink2" title={s.actions!.map((a) => a.label).join('\n')}>{s.actions!.length} action{s.actions!.length > 1 ? 's' : ''} ready</span>}
                  <button onClick={() => setP((x) => (x ? { ...x, subtasks: x.subtasks.filter((_, j) => j !== i) } : x))} aria-label={`Remove step ${i + 1}`} title="Remove" className="rounded-full p-1 text-ink2 hover:bg-panel2 hover:text-ink"><X size={14} aria-hidden /></button>
                </li>))}
            </ol>
            <button onClick={() => setP((x) => (x ? { ...x, subtasks: [...x.subtasks, { title: '' }] } : x))} className={cn(link, 'mt-1.5')}><Plus size={12} aria-hidden />Add a step</button>
          </div>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button onClick={() => { setP(null); setLast('') }} className={link}>Start again</button>
            <button onClick={save} className="ml-auto inline-flex items-center gap-2 rounded-full bg-accent px-4 py-1.5 text-[13.5px] font-medium text-onaccent hover:brightness-95"><Check size={14} aria-hidden />{p.add_to ? 'Add the steps' : 'Save the task'}</button>
          </div>
        </div>}
      </div>
    </div>
  )
}
