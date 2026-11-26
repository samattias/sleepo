// Tasks: Sam's plan of work (assist/tasks.py, 22 Oct 2026; replaced Actions and Open items). Initiative → task → step → action:
// a task is an outcome with a "done when", its steps each have an owner (someone else's step is a wait on them), and actions
// (an email, a message, a document Claude builds, a think-through) get a step done. Nothing here is sent. The list holds only
// what Sam made or accepted: the register and the assistant only suggest, and an unaccepted suggestion expires after 30 days.
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, ArrowUpRight, CalendarDays, Check, ChevronDown, ChevronRight, CornerDownRight, EyeOff, FilePlus2, FileSpreadsheet, FileText, Mail, MessageSquare, Pencil, Pin, Plus, Presentation, RefreshCw, RotateCcw, Sparkles, Trash2, X } from 'lucide-react'
import { api, type ActionSource, type DocItem, type TaskDoc, type TaskNode, type TasksData } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { btnClass, Empty, inputClass, Loading, Tag } from '@/components/ui'
import { TaskHistory } from '@/components/TaskHistory'
import { ActionRow, asList, type Action } from '@/components/Actions'
import { ClaudeStep } from '@/components/ActionSteps'
import { EmailDraft } from '@/components/EmailDraft'
import { openDoc } from '@/components/DocChip'
import { Segmented } from '@/components/FilterBar'
import { FiledUnder, filingLabel, type Filing } from '@/components/TaskCreator'
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { TZ, LOCALE } from '@/lib/time'
import { signoff } from '@/lib/profile'
import { AssistPill } from '@/components/AssistPill'
import { taskPill } from '@/lib/assistPills'
import { PersonLink } from '@/components/PersonLink'

type View = 'next' | 'initiative' | 'waiting' | 'suggested' | 'done' | 'history'
const KIND: Record<string, string> = { do: 'Do', reply: 'Reply', chase: 'Chase', decide: 'Decide', create: 'Create', prep: 'Prepare' }
const PRIO: Record<string, string> = { now: 'Now', today: 'Today', this_week: 'This week', later: 'Later' }
const ORIGIN: Record<string, string> = { register: 'from what was said or promised', assistant: 'suggested by SleePO', mail: 'from an email', meeting: 'from a meeting', sam: '' }
const primary = btnClass('primary', 'md')       // pill buttons (Sam, 23 Oct 2026: as in the Inbox and Meetings); cards stay square
const secondary = btnClass('outline', 'md', 'font-normal')
const icon = btnClass('ghost', 'icon')
const input = cn(inputClass, 'py-1.5 text-[13.5px]')   // fields and dropdowns rounded like the buttons (UI review, 30 Oct 2026)
const fmtDay = (d?: string | null) => { try { return d ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(d.length === 10 ? d + 'T12:00:00Z' : d)) : '' } catch { return d ?? '' } }
const fmtWhen = (d?: string | null) => { try { return d ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(d)) : '' } catch { return '' } }
const today = () => new Date().toISOString().slice(0, 10)
const overdue = (d?: string | null) => !!d && d < today()

function snoozeTimes() {
  const now = new Date()
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1); tomorrow.setHours(8, 0, 0, 0)
  const monday = new Date(now); monday.setDate(now.getDate() + ((8 - now.getDay()) % 7 || 7)); monday.setHours(8, 0, 0, 0)
  const twoWeeks = new Date(now); twoWeeks.setDate(now.getDate() + 14); twoWeeks.setHours(8, 0, 0, 0)
  return [{ label: 'Tomorrow 08:00', at: tomorrow }, { label: 'Monday 08:00', at: monday }, { label: 'In two weeks', at: twoWeeks }]
}
const iso = (d: Date) => d.toISOString().replace(/\.\d+Z$/, 'Z')

function useTaskMutations() {
  const qc = useQueryClient()
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.taskPatch(id, body),
    onSettled: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  })
  const create = useMutation({ mutationFn: (body: Record<string, unknown>) => api.taskCreate(body), onSettled: () => qc.invalidateQueries({ queryKey: ['tasks'] }) })
  return { patch: (id: number, body: Record<string, unknown>) => patch.mutateAsync({ id, body }), create: (b: Record<string, unknown>) => create.mutateAsync(b), error: patch.error ?? create.error }
}

// Back navigation (lib/nav.ts): the task Sam has open stays in the address (?open=, replaced, not pushed) and names the Back
// label, so Task → linked email → Back lands on the same task. Cards report opening and closing here.
const TaskOpen = createContext<(t: { id: number; title: string } | null, id: number) => void>(() => {})

// open: a task or step id (#/tasks?open=…) to expand, scroll to and highlight: only when it came from a link elsewhere
export function Tasks({ open }: { open?: number } = {}) {
  const [cur, setCur] = useState<{ id: number; title: string } | null>(null)
  const [arrival, setArrival] = useState(open)   // a link from elsewhere: scroll to it and highlight; Sam's own clicks do not
  useEffect(() => { if (open !== cur?.id) setArrival(open) }, [open])   // eslint-disable-line react-hooks/exhaustive-deps
  useSearchSync('open', cur?.id ?? null)
  usePageTitle(cur?.title)
  const report = (t: { id: number; title: string } | null, id: number) => setCur((c) => (t ? t : c && c.id === id ? null : c))
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['tasks'], queryFn: api.tasks, refetchInterval: (s) => (s.state.data?.job?.running ? 4000 : 60_000) })
  const [view, setView] = usePersisted<View>('assist-tasks-view', 'next')
  const [adding, setAdding] = useState(false)
  const suggest = useMutation({ mutationFn: api.taskSuggest, onSettled: () => qc.invalidateQueries({ queryKey: ['tasks'] }) })
  const d = q.data
  const focusTop = d && arrival ? (d.tasks.find((t) => t.id === arrival || t.subtasks.some((s) => s.id === arrival))?.id
    ?? d.suggestions.find((t) => t.id === arrival)?.id) : undefined
  useEffect(() => {   // a link to a task opens the view it is in
    if (!d || !arrival) return
    const t = d.tasks.find((x) => x.id === focusTop)
    if (d.suggestions.some((x) => x.id === arrival)) setView('suggested')
    else if (t && (t.status === 'done' || t.status === 'dropped')) setView('done')
    else if (t && view === 'suggested') setView('next')
  }, [d?.tasks.length, arrival])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <Loading />
  const live = d.tasks.filter((t) => t.status === 'open' || t.status === 'snoozed')
  const nextList = live.filter((t) => t.status === 'open' && !t.waiting)
  const waiting = live.filter((t) => t.waiting || t.subtasks.some((s) => s.status === 'open' && s.owner && !s.handoff))
  const done = d.tasks.filter((t) => t.status === 'done' || t.status === 'dropped')
  const running = !!d.job?.running || suggest.isPending

  return (
    <TaskOpen.Provider value={report}>
    <div className="max-w-[1000px]">
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Tasks</h1>
        <span className="text-[13px] text-ink2">{live.length} open · {waiting.length} waiting on others{d.suggestions.length ? ` · ${d.suggestions.length} suggested` : ''}</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => suggest.mutate()} disabled={running} title="SleePO reads your mail, meetings and messages and suggests tasks and steps; nothing is added until you accept" className={secondary}>
            {running ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />}{running ? 'Suggesting…' : 'Suggest tasks'}</button>
          <button onClick={() => setAdding(!adding)} className={primary}><Plus size={14} aria-hidden />New task</button>
        </div>
      </div>
      <p className="mb-3 max-w-[760px] text-[13px] text-ink2">Initiatives hold tasks; a task is an outcome with steps; each step has an owner and the actions that get it done. Only what you add or accept is here.</p>
      {running && <div className="mb-4 border-l-2 border-accent bg-panel px-3 py-2 text-[13px]">Reading what came in… usually 1–3 minutes. Suggestions land under Suggested.</div>}
      {d.job?.ok === false && !running && d.job.error && <div className="mb-4 border-l-2 border-hot bg-panel px-3 py-2 text-[13px]">The last suggestion run failed: {d.job.error}</div>}
      {adding && <NewTask data={d} onDone={() => setAdding(false)} />}

      <div className="mb-4 mt-2">
        <Segmented value={view} onChange={(v) => setView(v as View)} options={[['next', `Next ${nextList.length}`], ['initiative', 'By initiative'], ['waiting', `Waiting ${waiting.length}`],
          ['suggested', `Suggested ${d.suggestions.length}`], ['done', `Done ${done.length}`], ['history', 'History']] as [View, string][]} />
      </div>

      {view === 'next' && (nextList.length ? <div className="flex flex-col gap-3">{nextList.map((t) => <TaskCard key={t.id} t={t} data={d} focus={t.id === focusTop} openId={arrival} />)}</div>
        : <>
          <Empty>{live.length ? 'Everything open is waiting on someone else.' : 'No tasks yet. Add one, make one from an email (Inbox › Create task) or a meeting, or accept a suggestion.'}</Empty>
          {d.suggestions.length > 0 && <section className="mt-4">
            <h2 className="mb-2 text-[15px] font-semibold">Suggested <span className="font-normal text-ink2">· {d.suggestions.length} to accept or dismiss</span></h2>
            <div className="flex flex-col gap-3">{d.suggestions.map((s) => <Suggestion key={s.id} s={s} data={d} focus={s.id === arrival} />)}</div>
          </section>}
        </>)}
      {view === 'initiative' && <ByInitiative data={d} tasks={live} focusTop={focusTop} openId={arrival} />}
      {view === 'waiting' && (waiting.length ? <div className="flex flex-col gap-3">{waiting.map((t) => <TaskCard key={t.id} t={t} data={d} focus={t.id === focusTop} openId={arrival} waitingView />)}</div>
        : <Empty>Nobody owes you a step.</Empty>)}
      {view === 'suggested' && (d.suggestions.length ? <div className="flex flex-col gap-3">{d.suggestions.map((s) => <Suggestion key={s.id} s={s} data={d} focus={s.id === arrival} />)}</div>
        : <Empty>No suggestions waiting. New promises, waits and decisions from your mail and meetings land here, and SleePO's own suggestions after each morning refresh.</Empty>)}
      {view === 'done' && (done.length ? <div className="flex flex-col gap-3">{done.map((t) => <TaskCard key={t.id} t={t} data={d} focus={t.id === focusTop} openId={arrival} />)}</div>
        : <Empty>Nothing closed this week.</Empty>)}
      {view === 'history' && <TaskHistory data={d} />}
    </div>
    </TaskOpen.Provider>
  )
}

function ByInitiative({ data, tasks, focusTop, openId }: { data: TasksData; tasks: TaskNode[]; focusTop?: number; openId?: number }) {
  // the bets first, then day-to-day work by area, then anything not filed
  const groups: { key: string; name: string; note?: string; match: (t: TaskNode) => boolean }[] = [
    ...data.initiatives.map((i) => ({ key: `i${i.id}`, name: i.name, note: `weight ${i.weight}`, match: (t: TaskNode) => t.initiative_id === i.id })),
    ...data.areas.map((a) => ({ key: `a${a.key}`, name: `Day-to-day · ${a.name}`, note: a.hint, match: (t: TaskNode) => !t.initiative_id && t.area === a.key })),
    { key: 'none', name: 'Not filed', match: (t: TaskNode) => !t.initiative_id && !t.area }]
  const dayToDay = tasks.filter((t) => !t.initiative_id && t.area).length
  return <>
    {tasks.length > 0 && <p className="mb-4 text-[12.5px] text-ink2">{tasks.length - dayToDay} on your bets · {dayToDay} day-to-day</p>}
    {groups.map((g) => {
    const list = tasks.filter(g.match)
    if (!list.length) return null
    return (
      <section key={g.key} className="mb-6">
        <h2 className="mb-2 text-[15px] font-semibold">{g.name} <span className="font-normal text-ink2">· {list.length}{g.note ? ` · ${g.note}` : ''}</span></h2>
        {g.key === 'none' && <p className="mb-2 text-[12.5px] text-ink2">File each under a bet or a day-to-day area; if it fits neither, is it yours to do?</p>}
        <div className="flex flex-col gap-3">{list.map((t) => <TaskCard key={t.id} t={t} data={data} focus={t.id === focusTop} openId={openId} />)}</div>
      </section>)
  })}</>
}

// The tasks of one initiative, for its page (views/initiatives.tsx)
export function InitiativeTasks({ initiativeId }: { initiativeId: number }) {
  const q = useQuery({ queryKey: ['tasks'], queryFn: api.tasks })
  const [adding, setAdding] = useState(false)
  if (!q.data) return <Loading />
  const list = q.data.tasks.filter((t) => t.initiative_id === initiativeId && (t.status === 'open' || t.status === 'snoozed'))
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[13px] text-ink2">{list.length ? `${list.length} open task${list.length > 1 ? 's' : ''}` : 'No open tasks under this initiative.'}</span>
        <button onClick={() => setAdding(!adding)} className={cn(secondary, 'ml-auto px-2 py-1 text-[12.5px]')}><Plus size={13} aria-hidden />New task</button>
      </div>
      {adding && <NewTask data={q.data} initiativeId={initiativeId} onDone={() => setAdding(false)} />}
      <div className="flex flex-col gap-3">{list.map((t) => <TaskCard key={t.id} t={t} data={q.data!} />)}</div>
    </div>
  )
}

function NewTask({ data, initiativeId, onDone }: { data: TasksData; initiativeId?: number; onDone: () => void }) {
  const m = useTaskMutations()
  const [title, setTitle] = useState('')
  const [doneWhen, setDoneWhen] = useState('')
  const [filed, setFiled] = useState<Filing>({ initiative_id: initiativeId ?? null, area: null })
  const [due, setDue] = useState('')
  const [steps, setSteps] = useState('')
  const [err, setErr] = useState('')
  const save = async () => {
    setErr('')
    try {
      await m.create({ title, done_when: doneWhen, ...filed, due: due || null, subtasks: steps.split('\n').map((s) => s.trim()).filter(Boolean).map((s) => ({ title: s })) })
      onDone()
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
  }
  return (
    <div className="mb-4 border border-ink bg-panel p-4">
      <div className="grid gap-2">
        <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="The outcome, e.g. new pricing agreed with finance and marketing" aria-label="Task" className={cn(input, 'font-semibold')} />
        <input value={doneWhen} onChange={(e) => setDoneWhen(e.target.value)} placeholder="Done when… e.g. the price list is in the partner pack" aria-label="Done when" className={input} />
        <div className="flex flex-wrap gap-2">
          <FiledUnder value={filed} onChange={setFiled} initiatives={data.initiatives} areas={data.areas} className={input} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due" className={input} />
        </div>
        <textarea value={steps} onChange={(e) => setSteps(e.target.value)} rows={3} placeholder={'Steps, one per line (optional)\nDraft the options\nAsk finance for the margin numbers'} aria-label="Steps" className={cn(input, 'resize-y rounded-xl')} />
      </div>
      {err && <p className="mt-2 text-[13px] text-hot">{err}</p>}
      <div className="mt-3 flex gap-2"><button onClick={save} disabled={!title.trim()} className={primary}><Check size={14} aria-hidden />Add task</button><button onClick={onDone} className={secondary}>Cancel</button></div>
    </div>
  )
}

function Circle({ done, onClick, title }: { done: boolean; onClick: () => void; title: string }) {
  return <button onClick={onClick} title={title} aria-label={title}
    className={cn('mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full border', done ? 'border-ink bg-ink text-bg' : 'border-ink3 hover:border-ink hover:bg-accent')}>
    {done && <Check size={12} aria-hidden />}</button>
}

function Snooze({ onPick }: { onPick: (at: string) => void }) {
  const [open, setOpen] = useState(false)
  return <span className="relative">
    <button onClick={() => setOpen(!open)} title="Snooze" aria-label="Snooze" className={icon}><AlarmClock size={14} aria-hidden /></button>
    {open && <div className="absolute right-0 top-9 z-20 w-44 border border-line bg-panel py-1 shadow-xl">
      {snoozeTimes().map((s) => <button key={s.label} onClick={() => { setOpen(false); onPick(iso(s.at)) }} className="block w-full px-3 py-1.5 text-left text-[13px] hover:bg-panel2">{s.label}</button>)}
    </div>}
  </span>
}

function TaskCard({ t, data, focus, openId, waitingView }: { t: TaskNode; data: TasksData; focus?: boolean; openId?: number; waitingView?: boolean }) {
  const m = useTaskMutations()
  const report = useContext(TaskOpen)
  const [open, setOpenRaw] = useState(!!focus)
  const setOpen = (v: boolean) => { setOpenRaw(v); report(v ? { id: t.id, title: t.title } : null, t.id) }
  const [edit, setEdit] = useState(false)
  const [undo, setUndo] = useState<{ id: number; title: string } | null>(null)   // a step just deleted, for a few seconds
  const ref = useRef<HTMLElement>(null)
  useEffect(() => { if (focus) { setOpen(true); ref.current?.scrollIntoView({ block: 'center' }) } }, [focus])
  useEffect(() => { if (!undo) return; const x = setTimeout(() => setUndo(null), 8000); return () => clearTimeout(x) }, [undo])
  const closed = t.status === 'done' || t.status === 'dropped'
  const steps = t.subtasks.filter((s) => !['suggested', 'dismissed', 'expired', 'deleted'].includes(s.status))
  const ghosts = t.subtasks.filter((s) => s.status === 'suggested')
  const next = steps.find((s) => s.id === t.next_id)
  const others = steps.filter((s) => s.status === 'open' && s.owner && !s.handoff)
  const shownSteps = waitingView && !open ? others : steps
  const del = async (s: TaskNode) => { await m.patch(s.id, { status: 'deleted' }); setUndo({ id: s.id, title: s.title }) }
  return (
    <article ref={ref} className={cn('border border-line bg-panel', closed && 'opacity-60', focus && 'border-ink shadow-[4px_4px_0_0_var(--accent)]')}>
      <div className="flex items-start gap-3 px-4 py-3">
        <Circle done={closed} onClick={() => m.patch(t.id, { status: closed ? 'open' : 'done' })} title={closed ? 'Reopen the task' : 'Close the task (its open steps close with it)'} />
        <div className="min-w-0 flex-1">
          {edit ? <TaskEdit t={t} data={data} onDone={() => setEdit(false)} /> : <>
            <button onClick={() => setOpen(!open)} className="flex w-full items-start gap-1.5 text-left" aria-expanded={open}>
              <span className={cn('flex-1 text-[15px] font-semibold leading-snug', closed && 'line-through')}>{t.title}</span>
              {open ? <ChevronDown size={16} className="mt-0.5 shrink-0 text-ink3" aria-hidden /> : <ChevronRight size={16} className="mt-0.5 shrink-0 text-ink3" aria-hidden />}
            </button>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-ink2">
              <Tag>{filingLabel(t)}</Tag>
              {t.decide_or_drop && <Tag tone="pending" className="font-medium">Decide or drop</Tag>}
              {t.priority && <Tag tone={t.priority === 'now' ? 'pending' : 'plain'}>{PRIO[t.priority]}</Tag>}
              {t.steps_total ? <span>{t.steps_done}/{t.steps_total} steps</span> : null}
              {(t.due || t.next_due) && <span className={cn(overdue(t.next_due ?? t.due) && 'font-medium text-hot')}>· due {fmtDay(t.next_due ?? t.due)}</span>}
              {t.owner && <span>· with {t.owner}</span>}
              {t.waiting && <span>· waiting on {[...new Set(others.map((s) => s.owner))].join(', ') || t.owner}</span>}
              {t.status === 'snoozed' && t.snooze_until && <span>· snoozed until {fmtWhen(t.snooze_until)}</span>}
              {t.closed_by && closed && <span>· {t.status === 'dropped' ? 'dropped' : t.closed_by.startsWith('auto') ? 'closed from evidence' : 'done'} {fmtDay(t.closed_at)}</span>}
              {ghosts.length > 0 && <span className="font-medium text-ink">· {ghosts.length} suggested step{ghosts.length > 1 ? 's' : ''}</span>}
            </div>
            {t.decide_or_drop && <p className="mt-1 text-[12.5px] text-ink2">{t.decide_or_drop} Keep it (edit or snooze), close it, or drop it.</p>}
            {!open && next && next.id !== t.id && <div className="mt-1.5 flex items-start gap-1.5 text-[13.5px]"><CornerDownRight size={14} className="mt-0.5 shrink-0 text-ink3" aria-hidden /><span><span className="text-ink2">Next:</span> {next.title}</span></div>}
            {open && t.done_when && <p className="mt-1.5 text-[13.5px]"><span className="text-ink2">Done when:</span> {t.done_when}</p>}
            {open && t.why && <p className="mt-1 text-[13.5px] leading-snug text-ink2">{t.why}</p>}
          </>}
        </div>
        {!edit && <div className="flex shrink-0 items-center gap-1">
          <button onClick={() => { setEdit(true); setOpen(true) }} title="Edit the task" aria-label="Edit the task" className={icon}><Pencil size={14} aria-hidden /></button>
          {!closed && <Snooze onPick={(at) => m.patch(t.id, { status: 'snoozed', snooze_until: at })} />}
          {!closed ? <button onClick={() => m.patch(t.id, { status: 'dropped' })} title="Drop: not worth doing" aria-label="Drop" className={icon}><X size={14} aria-hidden /></button>
            : <button onClick={() => m.patch(t.id, { status: 'open' })} title="Reopen" aria-label="Reopen" className={icon}><RotateCcw size={14} aria-hidden /></button>}
        </div>}
      </div>
      {t.all_done && !closed && <div className="flex flex-wrap items-center gap-2 border-t border-line2 bg-panel2 px-4 py-2 text-[13px]">
        All steps are done{t.done_when ? <> · is it “{t.done_when}”?</> : '.'}
        <button onClick={() => m.patch(t.id, { status: 'done' })} className={cn(primary, 'ml-auto px-2.5 py-1 text-[12.5px]')}><Check size={13} aria-hidden />Close the task</button>
      </div>}
      {(open || (waitingView && others.length > 0)) && <div className="border-t border-line2 px-4 pb-3 pt-2">
        {/* the assistant pill (Sam, 16 Nov 2026): ask about the task or get its next step done, with the task's chip */}
        {open && !closed && <AssistPill className="mb-3 mt-1" target={{ kind: 'task', ref: String(t.id) }} {...taskPill(next?.title)} />}
        {open && <div className="mb-1 text-[12px] font-semibold text-ink">Steps</div>}
        {steps.length === 0 && open && !closed && <StepActions node={t} label={t.title} />}
        {shownSteps.length > 0 && <ol className="flex flex-col">{shownSteps.map((s) => <Step key={s.id} s={s} task={t} data={data} focus={s.id === openId} onDelete={() => del(s)} />)}</ol>}
        {undo && <div role="status" className="my-1 flex items-center gap-2 bg-panel2 px-3 py-1.5 text-[13px]">
          <Trash2 size={13} className="text-ink3" aria-hidden />Deleted “{undo.title}”
          <button onClick={async () => { await m.patch(undo.id, { status: 'open' }); setUndo(null) }} className="ml-auto font-medium underline decoration-accent decoration-2 underline-offset-2">Undo</button></div>}
        {open && ghosts.map((s) => <GhostStep key={s.id} s={s} />)}
        {open && !closed && <AddStep taskId={t.id} />}
        {open && <TaskLinkedItems t={t} />}
        {open && <TaskDocuments t={t} />}
        {open && t.sources.length > 0 && <Sources sources={t.sources} />}
      </div>}
    </article>
  )
}

function TaskEdit({ t, data, onDone }: { t: TaskNode; data: TasksData; onDone: () => void }) {
  const m = useTaskMutations()
  const [f, setF] = useState({ title: t.title, done_when: t.done_when ?? '', initiative_id: t.initiative_id, area: t.area, due: t.due ?? '', priority: t.priority ?? '', owner: t.owner ?? '' })
  const save = async () => { await m.patch(t.id, { ...f, due: f.due || null, priority: f.priority || null, owner: f.owner || null }); onDone() }
  const remove = async () => {
    if (!window.confirm(`Delete “${t.title}” and its steps? Use Drop instead if it is simply not worth doing.`)) return
    await m.patch(t.id, { status: 'deleted' }); onDone()
  }
  return (
    <div className="grid gap-2" onKeyDown={(e) => { if (e.key === 'Escape') onDone() }}>
      <input autoFocus value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} onKeyDown={(e) => { if (e.key === 'Enter') save() }} aria-label="Task" className={cn(input, 'font-semibold')} />
      <input value={f.done_when} onChange={(e) => setF({ ...f, done_when: e.target.value })} placeholder="Done when…" aria-label="Done when" className={input} />
      <div className="flex flex-wrap gap-2">
        {!t.parent_id && <FiledUnder value={{ initiative_id: f.initiative_id, area: f.area }} onChange={(x) => setF({ ...f, ...x })} initiatives={data.initiatives} areas={data.areas} className={input} />}
        <input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} aria-label="Due" className={input} />
        <select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} aria-label="Priority" className={input}>
          <option value="">No priority</option>{Object.entries(PRIO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} placeholder="Owner: you" aria-label="Owner" className={cn(input, 'w-40')} />
      </div>
      <div className="flex items-center gap-2">
        <button onClick={save} className={cn(primary, 'px-2.5 py-1 text-[12.5px]')}><Check size={13} aria-hidden />Save</button>
        <button onClick={onDone} className={cn(secondary, 'px-2.5 py-1 text-[12.5px]')}>Cancel</button>
        <button onClick={remove} className="ml-auto inline-flex items-center gap-1 text-[12.5px] text-ink2 hover:text-hot"><Trash2 size={13} aria-hidden />Delete task</button>
      </div>
    </div>
  )
}

// One step: tick it, click its title to open its actions, change it in place (pencil, or double-click the title), or delete
// it (the task shows Undo for a few seconds). Owner and due date sit on the right.
function Step({ s, task, data, focus, onDelete }: { s: TaskNode; task: TaskNode; data: TasksData; focus?: boolean; onDelete: () => void }) {
  const m = useTaskMutations()
  const [open, setOpen] = useState(!!focus)
  const [edit, setEdit] = useState(false)
  const [f, setF] = useState({ title: s.title, owner: s.owner ?? '', due: s.due ?? '' })
  const [move, setMove] = useState(false)
  const done = s.status === 'done' || s.status === 'dropped'
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => { if (focus) ref.current?.scrollIntoView({ block: 'center' }) }, [focus])
  const isNext = task.next_id === s.id
  const startEdit = () => { setF({ title: s.title, owner: s.owner ?? '', due: s.due ?? '' }); setEdit(true) }
  const save = async () => { if (!f.title.trim()) return; await m.patch(s.id, { title: f.title, owner: f.owner || null, due: f.due || null }); setEdit(false) }
  const who = !s.owner ? 'You' : done ? s.owner : s.handoff ? `Hand to ${s.owner}` : `Waiting on ${s.owner}`
  return (
    <li ref={ref} className={cn('group/step border-b border-line2 last:border-0', focus && 'bg-accentbg')}>
      <div className="flex items-start gap-2.5 py-2">
        <Circle done={done} onClick={() => m.patch(s.id, { status: done ? 'open' : 'done' })} title={done ? 'Reopen the step' : 'Mark the step done'} />
        <div className="min-w-0 flex-1">
          {edit ? <div className="flex flex-wrap items-center gap-2" onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEdit(false) }}>
            <input autoFocus value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} aria-label="Step" className={cn(input, 'min-w-[220px] flex-1 py-0.5')} />
            <input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} placeholder="Who: you" aria-label="Who does it" className={cn(input, 'w-36 py-0.5')} />
            <input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} aria-label="Due" className={cn(input, 'py-0.5')} />
            <button onClick={save} className={cn(primary, 'px-2 py-0.5 text-[12.5px]')}>Save</button>
            <button onClick={() => setEdit(false)} className={cn(secondary, 'px-2 py-0.5 text-[12.5px]')}>Cancel</button>
          </div> : <div className="flex items-start gap-2">
            <button onClick={() => setOpen(!open)} onDoubleClick={startEdit} aria-expanded={open} title="Open its actions; double-click to change it"
              className={cn('min-w-0 flex-1 text-left text-[14px] leading-snug', done && 'text-ink2 line-through', isNext && 'font-semibold')}>{s.title}</button>
            <span className="flex shrink-0 items-center gap-1.5 pt-px text-[12px] text-ink2">
              {s.kind && s.kind !== 'do' && <span className="max-sm:hidden">{KIND[s.kind]}</span>}
              <span className={cn('rounded-full px-1.5 leading-[18px]', s.owner && !done ? 'bg-panel2 font-medium text-ink' : '')}>{s.owner && s.owner_person_id ? <PersonLink id={s.owner_person_id} title={`${s.owner}'s page`}>{who}</PersonLink> : who}</span>
              {s.due && <span className={cn(!done && overdue(s.due) && 'font-medium text-hot')}>{fmtDay(s.due)}</span>}
              {s.actions.length > 0 && <span title={s.actions.map((a) => a.label).join('\n')}>{s.actions.length} action{s.actions.length > 1 ? 's' : ''}</span>}
              <span className="flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/step:opacity-100">
                <button onClick={startEdit} title="Change the step" aria-label={`Change ${s.title}`} className="p-1 hover:text-ink"><Pencil size={13} aria-hidden /></button>
                <button onClick={onDelete} title="Delete the step" aria-label={`Delete ${s.title}`} className="p-1 hover:text-hot"><Trash2 size={13} aria-hidden /></button>
              </span>
              <button onClick={() => setOpen(!open)} aria-label={open ? 'Close' : 'Open'} className="p-0.5 text-ink3 hover:text-ink">{open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}</button>
            </span>
          </div>}
          {!edit && done && s.closed_by?.startsWith('auto') && <div className="mt-0.5 text-[12px] text-ink2">Closed from evidence{s.close_ref && <> · <a href={s.close_ref.url}>{s.close_ref.label}</a></>}</div>}
          {open && !edit && <div className="mt-1 pb-1">
            <StepActions node={s} label={`${task.title}: ${s.title}`} />
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
              <button onClick={() => setMove(!move)} className="text-ink2 underline decoration-line underline-offset-2 hover:text-ink">Move to another task</button>
              {!done && <button onClick={() => m.patch(s.id, { status: 'dropped' })} title="Not worth doing: kept in the task's history" className="text-ink2 underline decoration-line underline-offset-2 hover:text-ink">Drop</button>}
            </div>
            {move && <MoveTo id={s.id} exclude={task.id} data={data} allowTask onDone={() => setMove(false)} />}
          </div>}
        </div>
      </div>
    </li>
  )
}

// A step SleePO suggests on a task Sam has: accept or dismiss
function GhostStep({ s }: { s: TaskNode }) {
  const m = useTaskMutations()
  return (
    <div className="flex items-start gap-2.5 border-b border-dashed border-line py-2 last:border-0">
      <Sparkles size={15} className="mt-0.5 shrink-0 text-ink3" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] leading-snug">{s.title}</div>
        <div className="mt-0.5 text-[12px] text-ink2">Suggested {ORIGIN[s.origin ?? ''] ?? ''}{s.owner ? ` · ${s.owner}` : ''}{s.due ? ` · due ${fmtDay(s.due)}` : ''}{s.why ? ` · ${s.why}` : ''}</div>
      </div>
      <button onClick={() => m.patch(s.id, { status: 'open' })} className={cn(primary, 'px-2 py-1 text-[12.5px]')}><Check size={13} aria-hidden />Add</button>
      <button onClick={() => m.patch(s.id, { status: 'dismissed' })} title="Dismiss" aria-label="Dismiss" className={icon}><X size={14} aria-hidden /></button>
    </div>
  )
}

function AddStep({ taskId }: { taskId: number }) {
  const m = useTaskMutations()
  const [title, setTitle] = useState('')
  const [owner, setOwner] = useState('')
  const add = async () => { if (!title.trim()) return; await m.create({ parent_id: taskId, title, owner: owner || null }); setTitle(''); setOwner('') }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Plus size={14} className="text-ink3" aria-hidden />
      <input value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add() }} placeholder="Add a step" aria-label="Add a step" className={cn(input, 'min-w-[220px] flex-1 py-0.5')} />
      <input value={owner} onChange={(e) => setOwner(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add() }} placeholder="Who (you)" aria-label="Who does it" className={cn(input, 'w-32 py-0.5')} />
      {title.trim() && <button onClick={add} className={cn(primary, 'px-2 py-0.5 text-[12.5px]')}>Add</button>}
    </div>
  )
}

const BLANK: Record<string, (title: string, owner: string | null) => Action> = {
  email: (t, o) => ({ type: 'email', label: o ? `Email ${o}` : 'Email', to: [], subject: t, body: `${o ? `Hi ${o.split(' ')[0]},` : 'Hi,'}\n\n[FILL]\n\n${signoff()}` }),
  teams: (t, o) => ({ type: 'teams', label: o ? `Message ${o} on Teams` : 'Teams message', to: [], message: `${o ? `Hi ${o.split(' ')[0]}, ` : ''}[FILL: ${t}]` }),
  create: (t) => ({ type: 'create', label: 'Create a document in Claude', app: 'cowork', format: 'docx', title: t, prompt: `${t}. [FILL: what it must cover and for whom]` }),
  draft: (t) => ({ type: 'draft', label: 'Think it through in Claude', app: 'chat', prompt: `Help me think through: ${t}` }),
}

// A step's actions, done properly: an email is a draft from Sam (the Inbox's draft card: edit in place, copy, or open in
// Outlook); a document opens Claude Cowork with SleePO's context pack; a message is copied to paste. Edits are kept on the
// step, any action can be removed, and what Sam does is logged.
export function StepActions({ node, label }: { node: TaskNode; label: string }) {
  const qc = useQueryClient()
  const m = useTaskMutations()
  const src = useQuery({ queryKey: ['taskSources', node.id], queryFn: () => api.taskSources(node.id), staleTime: 60_000, enabled: node.actions.length > 0 })
  const used = (step: number) => (what: string) => { api.taskLog(node.id, step, what).then(() => qc.invalidateQueries({ queryKey: ['tasks'] })) }
  const latest = useRef(node.actions)   // edits to two drafts in a row must not overwrite each other
  latest.current = node.actions
  const saveAt = (i: number) => (a: Action) => { const next = latest.current.map((x, j) => (j === i ? a : x)); latest.current = next; m.patch(node.id, { actions: next }) }
  const removeAt = (i: number) => m.patch(node.id, { actions: latest.current.filter((_, j) => j !== i) })
  const addAction = (k: string) => m.patch(node.id, { actions: [...latest.current, BLANK[k](node.title, node.owner)] })
  const ready = node.actions.length === 0 || !!src.data || src.isError
  return (
    <div>
      {!ready && <div className="text-[12px] text-ink3">Loading what this is about…</div>}
      {ready && node.actions.map((a, i) => <ActionStep key={`${node.id}-${i}-${a.type}`} a={a} i={i} node={node} label={label} sources={src.data ?? []}
        onUsed={used(i)} onSave={saveAt(i)} onRemove={() => removeAt(i)} />)}
      {node.log.length > 0 && <div className="mt-1 text-[12px] text-ink2">{node.log.slice(-3).map((l, i) => <div key={i}>{fmtWhen(l.at)} · {l.what}{l.label ? `: ${l.label}` : ''}</div>)}</div>}
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-ink2">
        <span>Add an action:</span>
        {([['email', Mail, 'Email'], ['teams', MessageSquare, 'Message'], ['create', FilePlus2, 'Document'], ['draft', Sparkles, 'Think it through']] as const).map(([k, Icon, l]) =>
          <button key={k} onClick={() => addAction(k)} className={btnClass('outline', 'xs', 'font-normal text-ink2 hover:text-ink')}><Icon size={12} aria-hidden />{l}</button>)}
      </div>
    </div>
  )
}

function ActionStep({ a, i, node, label, sources, onUsed, onSave, onRemove }: { a: Action; i: number; node: TaskNode; label: string; sources: ActionSource[]
  onUsed: (what: string) => void; onSave: (a: Action) => void; onRemove: () => void }) {
  const tid = `task-${node.id}`
  if (a.type === 'email') {
    const emails = sources.filter((s): s is Extract<ActionSource, { kind: 'email' }> => s.kind === 'email' && !s.missing && s.full)
    const id = (x?: string) => (x ?? '').replace(/^am:/, '')
    const email = emails.find((s) => !!a.reply_to && id(s.graph_id) === id(a.reply_to)) ?? (!asList(a.to).length && /^(reply|answer|respond)\b/i.test(a.label) ? emails.find((s) => s.closes) : undefined)
    return <EmailDraft a={a} taskId={node.id} step={i} email={email} onSave={onSave} onUsed={onUsed} onRemove={onRemove} />
  }
  const body = a.type === 'create' || a.type === 'edit' || a.type === 'draft'
    ? <ClaudeStep a={a} step={i + 1} index={i} targetId={tid} act={(idx, p) => api.taskAct(node.id, idx, p)} />
    : <ActionRow a={a} label={label} compact step={i + 1} targetId={tid} onUsed={onUsed} />
  return (
    <div className="group/act flex items-start gap-1">
      <div className="min-w-0 flex-1">{body}</div>
      <button onClick={onRemove} title="Remove this action" aria-label={`Remove ${a.label}`} className="mt-2.5 p-1 text-ink3 opacity-0 transition-opacity hover:text-hot focus:opacity-100 group-hover/act:opacity-100"><Trash2 size={13} aria-hidden /></button>
    </div>
  )
}

// Mail threads, messages and meeting notes linked to the task (assist/task_links.py, the Inbox's links): newest first, each
// opening where it lives. Unlink takes the whole thread off the task, for good (the Inbox shows the same link).
const LINK_HOW: Record<string, string> = { thread: 'same thread', model: 'matched by SleePO', sam: 'linked by you' }
function TaskLinkedItems({ t }: { t: TaskNode }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['taskLinked', t.id], queryFn: () => api.taskLinked(t.id), staleTime: 60_000 })
  const [all, setAll] = useState(false)
  if (!q.data?.length) return null
  const unlink = async (item: number) => { await api.itemTaskLink(item, t.id, false); qc.invalidateQueries({ queryKey: ['taskLinked', t.id] }); qc.invalidateQueries({ queryKey: ['taskDocs', t.id] }) }
  const list = all ? q.data : q.data.slice(0, 5)
  return (
    <section aria-label="Linked mail and messages" className="mt-3">
      <div className="mb-1 flex items-center gap-2"><span className="text-[12px] font-semibold text-ink">Linked mail and messages</span><span className="text-[12px] text-ink3">{q.data.length}</span></div>
      {list.map((x) => { const Icon = x.kind === 'mail' ? Mail : x.kind === 'meeting' ? CalendarDays : MessageSquare; return (
        <div key={x.item_id} className="group/link flex items-center gap-2 border-b border-line2 py-1.5 last:border-0">
          <Icon size={15} className="shrink-0 text-ink2" aria-hidden />
          <a href={x.url} className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink no-underline hover:underline">{x.title}</a>
          <span className="shrink-0 text-[12px] text-ink3 max-sm:hidden">{x.who ? `${x.who} · ` : ''}{fmtDay(x.ts)} · {LINK_HOW[x.source] ?? x.source}</span>
          <button onClick={() => unlink(x.item_id)} title="Not about this task: unlink it (the whole thread)" aria-label={`Unlink ${x.title}`}
            className="p-1 text-ink3 opacity-0 hover:text-ink focus:opacity-100 group-hover/link:opacity-100"><X size={13} aria-hidden /></button>
        </div>) })}
      {q.data.length > 5 && <button onClick={() => setAll(!all)} className="mt-0.5 text-[12px] text-ink2 hover:text-ink">{all ? 'Show fewer' : `Show all ${q.data.length}`}</button>}
    </section>
  )
}

// The documents a task is about (assist/tasks.py documents): pinned by Sam, then its own material and documents on its topic,
// newest first, one per file (older versions fold under it). Each opens the real file. Pin keeps it with the task and hands it
// to Claude when a step builds a document; hide says it is not about this task. Add a document finds any file by name.
function TaskDocuments({ t }: { t: TaskNode }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['taskDocs', t.id], queryFn: () => api.taskDocuments(t.id), staleTime: 60_000 })
  const all = useQuery({ queryKey: ['documents'], queryFn: api.documents, staleTime: 300_000 })
  const [adding, setAdding] = useState(false)
  const [find, setFind] = useState('')
  const set = async (doc: string, op: 'pin' | 'unpin' | 'hide') => { await api.taskDocSet(t.id, doc, op); qc.invalidateQueries({ queryKey: ['taskDocs', t.id] }) }
  const byId = new Map((all.data ?? []).map((d) => [d.id, d]))
  const list = [...(q.data?.pinned ?? []), ...(q.data?.related ?? [])]
  const shown = new Set(list.flatMap((x) => [x.id, ...x.versions]))
  const words = find.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const found = words.length ? (all.data ?? []).filter((d) => !shown.has(d.id) && words.every((w) => d.name.toLowerCase().includes(w)))
    .sort((a, b) => (b.ts || '').localeCompare(a.ts || '')).slice(0, 6) : []
  return (
    <section aria-label="Documents" className="mt-3">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[12px] font-semibold text-ink">Documents</span>
        {q.data && <span className="text-[12px] text-ink3">{list.length ? 'newest first' : 'none found on this topic yet'}</span>}
        <button onClick={() => setAdding(!adding)} className="ml-auto inline-flex items-center gap-1 text-[12px] text-ink2 hover:text-ink"><Plus size={12} aria-hidden />Add a document</button>
      </div>
      {adding && <div className="mb-2">
        <input autoFocus value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a document by name, e.g. budget 2027" aria-label="Find a document" className={cn(input, 'w-full py-1 text-[13px]')} />
        {found.map((d) => <button key={d.id} onClick={async () => { await set(d.id, 'pin'); setFind(''); setAdding(false) }}
          className="flex w-full items-center gap-2 border-b border-line2 px-1 py-1.5 text-left text-[13px] hover:bg-panel2">
          <DocIcon name={d.name} /><span className="min-w-0 flex-1 truncate">{d.name}</span><span className="shrink-0 text-[12px] text-ink3">{fmtDay(d.ts)} · {d.where}</span></button>)}
        {words.length > 0 && !found.length && all.data && <div className="px-1 py-1.5 text-[12.5px] text-ink3">No document by that name.</div>}
      </div>}
      {!q.data ? <div className="text-[12px] text-ink3">Finding documents…</div> : list.map((x) => <DocRow key={x.id} x={x} d={byId.get(x.id)} older={x.versions.map((v) => byId.get(v)).filter((v): v is DocItem => !!v)}
        onPin={() => set(x.id, x.pinned ? 'unpin' : 'pin')} onHide={() => set(x.id, 'hide')} />)}
    </section>
  )
}

const DocIcon = ({ name }: { name: string }) => {
  const ext = (name.split('.').pop() ?? '').toLowerCase()
  const Icon = ['xls', 'xlsx', 'csv'].includes(ext) ? FileSpreadsheet : ['ppt', 'pptx', 'key'].includes(ext) ? Presentation : FileText
  return <Icon size={15} className="shrink-0 text-ink2" aria-hidden />
}

function DocRow({ x, d, older, onPin, onHide }: { x: TaskDoc; d?: DocItem; older: DocItem[]; onPin: () => void; onHide: () => void }) {
  const [more, setMore] = useState(false)
  const open = (doc?: DocItem) => { if (doc) openDoc(doc) }
  return (
    <div className="group/doc border-b border-line2 py-1.5 last:border-0">
      <div className="flex items-center gap-2">
        <DocIcon name={x.name} />
        <button onClick={() => open(d)} disabled={!d} title={d ? `Open ${x.name}` : 'This document is no longer available'} className="min-w-0 flex-1 truncate text-left text-[13.5px] font-medium text-ink hover:underline disabled:font-normal disabled:text-ink2">{x.name}</button>
        <span className="shrink-0 text-[12px] text-ink3 max-sm:hidden">{fmtDay(x.ts)}{d?.where ? ` · ${d.where}` : ''}</span>
        <span className="flex shrink-0 items-center gap-0.5">
          <button onClick={onPin} title={x.pinned ? 'Unpin: no longer kept with this task' : 'Pin: keep it with this task (Claude builds on it)'} aria-label={x.pinned ? 'Unpin' : 'Pin'}
            className={cn('p-1', x.pinned ? 'text-ink' : 'text-ink3 opacity-0 hover:text-ink focus:opacity-100 group-hover/doc:opacity-100')}>{x.pinned ? <Pin size={13} className="fill-current" aria-hidden /> : <Pin size={13} aria-hidden />}</button>
          {!x.pinned && <button onClick={onHide} title="Not about this task: hide it" aria-label="Hide" className="p-1 text-ink3 opacity-0 hover:text-ink focus:opacity-100 group-hover/doc:opacity-100"><EyeOff size={13} aria-hidden /></button>}
        </span>
      </div>
      <div className="ml-[23px] flex flex-wrap items-center gap-x-2 text-[12px] text-ink3">
        <span>{x.pinned ? 'pinned by you' : x.reason}</span>
        {older.length > 0 && <button onClick={() => setMore(!more)} className="hover:text-ink">· {older.length} older version{older.length > 1 ? 's' : ''}</button>}
      </div>
      {more && <div className="ml-[23px] mt-0.5">{older.map((o) => <button key={o.id} onClick={() => open(o)} className="block max-w-full truncate text-left text-[12.5px] text-ink2 hover:text-ink hover:underline">{o.name} · {fmtDay(o.ts)}</button>)}</div>}
    </div>
  )
}

function Sources({ sources }: { sources: TaskNode['sources'] }) {
  const [show, setShow] = useState(false)
  return (
    <div className="mt-2 text-[12px] text-ink3">
      <button onClick={() => setShow(!show)} aria-expanded={show} className="inline-flex items-center gap-1 hover:text-ink">
        {show ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}From {sources.length} source{sources.length > 1 ? 's' : ''}
      </button>
      {show && <div className="mt-1.5 flex flex-wrap gap-1.5">
        {sources.map((s) => <a key={s.ref} href={s.url} target={s.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="max-w-[320px] truncate rounded-full border border-line px-2 py-0.5 font-normal text-ink2 no-underline hover:border-ink">{s.label}</a>)}
      </div>}
    </div>
  )
}

// Put a task (with no steps) or a step under another task, or make a step a task of its own
function MoveTo({ id, exclude, data, allowTask, onDone }: { id: number; exclude?: number; data: TasksData; allowTask?: boolean; onDone: () => void }) {
  const m = useTaskMutations()
  const [to, setTo] = useState<string>('')
  const [err, setErr] = useState('')
  const go = async () => { setErr(''); try { await m.patch(id, { parent_id: to === 'task' ? null : Number(to) }); onDone() } catch (e) { setErr(String(e instanceof Error ? e.message : e)) } }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
      <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="Move to" className={cn(input, 'max-w-full')}>
        <option value="">Move to…</option>
        {allowTask && <option value="task">Its own task</option>}
        {data.tasks.filter((t) => t.id !== exclude && t.id !== id && (t.status === 'open' || t.status === 'snoozed')).map((t) => <option key={t.id} value={t.id}>A step of: {t.title}</option>)}
      </select>
      <button onClick={go} disabled={!to} className={cn(primary, 'px-2 py-1 text-[12.5px]')}><ArrowUpRight size={13} aria-hidden />Move</button>
      {err && <span className="text-hot">{err}</span>}
    </div>
  )
}

function Suggestion({ s, data, focus }: { s: TaskNode; data: TasksData; focus?: boolean }) {
  const m = useTaskMutations()
  const [filed, setFiled] = useState<Filing>({ initiative_id: s.initiative_id, area: s.area })
  const [move, setMove] = useState(false)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => { if (focus) ref.current?.scrollIntoView({ block: 'center' }) }, [focus])
  const steps = s.subtasks.filter((x) => x.status === 'suggested')
  const isStep = !!s.parent_id
  const accept = async () => { if (!isStep && (filed.initiative_id !== s.initiative_id || filed.area !== s.area)) await m.patch(s.id, filed); await m.patch(s.id, { status: 'open' }) }
  const days = Math.max(0, 30 - Math.floor((Date.now() - new Date(s.created_at).getTime()) / 86_400_000))
  return (
    <article ref={ref} className={cn('border border-dashed border-line bg-panel', focus && 'border-ink shadow-[4px_4px_0_0_var(--accent)]')}>
      <div className="flex items-start gap-3 px-4 py-3">
        <Sparkles size={18} className="mt-0.5 shrink-0 text-ink3" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] text-ink2">{isStep ? <>A step for <span className="font-medium text-ink">{s.parent_title}</span></> : 'A new task'} · {ORIGIN[s.origin ?? ''] || 'suggested'} · expires in {days} day{days === 1 ? '' : 's'}</div>
          <div className="mt-0.5 text-[15px] font-semibold leading-snug">{s.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-ink2">
            {[s.owner && `${s.owner} does it`, s.due && `due ${fmtDay(s.due)}`, s.done_when && `done when ${s.done_when}`].filter(Boolean).join(' · ')}
          </div>
          {s.why && <p className="mt-1 text-[13.5px] leading-snug text-ink2">{s.why}</p>}
          {steps.length > 0 && <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-[13.5px]">
            {steps.map((x) => <li key={x.id} className="group">
              <span>{x.title}</span>{x.owner && <span className="text-ink2"> · {x.owner}</span>}{x.actions.length > 0 && <span className="text-ink2"> · {x.actions.length} action{x.actions.length > 1 ? 's' : ''} ready</span>}
              <button onClick={() => m.patch(x.id, { status: 'dismissed' })} title="Leave this step out" aria-label={`Leave out ${x.title}`} className="ml-1.5 align-middle text-ink3 opacity-0 hover:text-ink group-hover:opacity-100 focus:opacity-100"><X size={12} aria-hidden /></button>
            </li>)}
          </ol>}
          {s.sources.length > 0 && <Sources sources={s.sources} />}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {!isStep && <FiledUnder value={filed} onChange={setFiled} initiatives={data.initiatives} areas={data.areas} className={cn(input, 'py-1 text-[13px]')} />}
            <button onClick={accept} className={cn(primary, 'px-2.5 py-1 text-[12.5px]')}><Check size={13} aria-hidden />{isStep ? 'Add the step' : 'Add to my tasks'}</button>
            {!steps.length && <button onClick={() => setMove(!move)} className={cn(secondary, 'px-2.5 py-1 text-[12.5px]')}>{isStep ? 'Put it elsewhere' : 'Make it a step of…'}</button>}
            <button onClick={() => m.patch(s.id, { status: 'dismissed' })} className={cn(secondary, 'px-2.5 py-1 text-[12.5px]')}><X size={13} aria-hidden />Dismiss</button>
          </div>
          {move && <MoveTo id={s.id} exclude={s.parent_id ?? undefined} data={data} allowTask={isStep} onDone={() => { setMove(false) }} />}
        </div>
      </div>
    </article>
  )
}

// A meeting's suggestions as proposed steps (assist/tasks.py propose_from_meeting / propose_from_brief): the meeting panel's
// "Follow-ups from this meeting" and the brief's "Prepare for this meeting". Each says where it was said and which task it
// goes to; Add puts it there (a new task's first step accepts the task too), Own task makes it a task of its own, the cross
// dismisses it. Do it opens the step's actions (the email draft, Open in Claude, Copy). Pill buttons: the Meetings style.
const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2 disabled:opacity-60'
const pillOn = 'inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-[12.5px] font-semibold text-onaccent hover:brightness-95 disabled:opacity-60'
export function ProposedSteps({ steps, empty }: { steps: TaskNode[]; empty?: string }) {
  if (!steps.length) return empty ? <p className="text-[13px] text-ink2">{empty}</p> : null
  return <div className="flex flex-col gap-2">{steps.map((s) => <ProposedStep key={s.id} s={s} />)}</div>
}

function ProposedStep({ s }: { s: TaskNode }) {
  const qc = useQueryClient()
  const [doing, setDoing] = useState(false)
  const [busy, setBusy] = useState(false)
  const act = async (body: Record<string, unknown>[]) => { setBusy(true); try { for (const b of body) await api.taskPatch(s.id, b) } finally { setBusy(false); qc.invalidateQueries({ queryKey: ['tasks'] }) } }
  const suggested = s.status === 'suggested'
  const done = s.status === 'done' || s.status === 'dropped'
  const src = s.sources[0]
  const said = src?.label.includes(' · ') ? src.label.split(' · ').slice(1).join(' · ') : ''
  const newTask = s.parent_status === 'suggested'
  return (
    <article className={cn('rounded-xl border bg-panel px-3.5 py-2.5', suggested ? 'border-dashed border-ink3/60' : 'border-line', done && 'opacity-60')}>
      <div className="flex items-start gap-2.5">
        {suggested ? <Sparkles size={15} className="mt-0.5 shrink-0 text-ink3" aria-hidden />
          : <button onClick={() => act([{ status: done ? 'open' : 'done' }])} title={done ? 'Reopen the step' : 'Mark the step done'} aria-label={done ? 'Reopen' : 'Mark done'}
              className={cn('mt-0.5 inline-flex size-[18px] shrink-0 items-center justify-center rounded-full border', done ? 'border-ink bg-ink text-bg' : 'border-ink3 hover:border-ink hover:bg-accent')}>{done && <Check size={11} aria-hidden />}</button>}
        <div className="min-w-0 flex-1">
          <div className={cn('text-[14px] font-medium leading-snug', done && 'line-through')}>{s.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-ink2">
            {said && src && <a href={src.url} title="Open the transcript at that moment" className="font-medium">{said}</a>}
            {s.parent_title && (suggested
              ? <span>{newTask ? <>new task: <span className="text-ink">{s.parent_title}</span></> : <>step of <span className="text-ink">{s.parent_title}</span></>}</span>
              : <Link to="/tasks" search={{ open: s.id }} className="inline-flex items-center gap-0.5">in Tasks: {s.parent_title}<ArrowUpRight size={11} aria-hidden /></Link>)}
            {s.due && <span>due {fmtDay(s.due)}</span>}
          </div>
          {s.why && <p className="mt-1 text-[12.5px] leading-snug text-ink2">{s.why}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-1">
            {suggested && <button disabled={busy} onClick={() => act([{ status: 'open' }])} className={pillOn} title={newTask ? 'Add it to Tasks, as the first step of this new task' : 'Add it as a step of this task'}>
              <Check size={13} aria-hidden />{newTask ? 'Add to Tasks' : 'Add to the task'}</button>}
            {suggested && <button disabled={busy} onClick={() => act([{ parent_id: null }, { status: 'open' }])} className={pill} title="Make it a task of its own">Own task</button>}
            {s.actions.length > 0 && <button onClick={() => setDoing(!doing)} aria-expanded={doing} className={pill}>
              <ChevronDown size={13} aria-hidden className={cn('transition-transform', !doing && '-rotate-90')} />Do it · {s.actions.length} action{s.actions.length > 1 ? 's' : ''}</button>}
            {suggested && <button disabled={busy} onClick={() => act([{ status: 'dismissed' }])} title="Not worth doing: dismiss it" aria-label="Dismiss" className="ml-auto rounded-full p-1.5 text-ink3 hover:bg-panel2 hover:text-ink"><X size={14} aria-hidden /></button>}
          </div>
          {doing && <div className="mt-2"><StepActions node={s} label={s.parent_title ? `${s.parent_title}: ${s.title}` : s.title} /></div>}
        </div>
      </div>
    </article>
  )
}
