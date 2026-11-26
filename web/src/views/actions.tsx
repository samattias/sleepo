// The Actions page (Sam, 25 Nov 2026: "get rid of the dashboard page. I don't like it and I don't use it. Instead, I want a page
// with ... my reactive and proactive action"). It replaced Today, the board of widgets, as the first page.
// Reactive: someone is waiting on Sam (emails that need a response, Teams and Slack messages he owes, follow-ups from his
// meetings). Proactive: what SleePO recommends he start (emails and messages it has written, promises he made and has not kept,
// the other suggested next steps). Built on the server (assist/actions_view.py) from the lists SleePO already keeps: every row
// is an email, a register item or a task step, and each button acts on that thing through its own route, so the Inbox, Drafts,
// Tasks and Messages show the same change. A document page: the page scrolls. Each section shows its first rows, the rest on
// request; long-overdue suggestions sink below current ones (the server's ranking).
import { useEffect, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CalendarDays, Check, Handshake, Inbox as InboxIcon, Lightbulb, ListChecks, MessagesSquare, Plus, Send, Sparkles, X, type LucideIcon } from 'lucide-react'
import { api, type ActionItem, type ActionsData, type Person } from '@/lib/api'
import { cn } from '@/lib/util'
import { Avatar, btnClass } from '@/components/ui'
import { OutlookLogo } from '@/components/OutlookLogo'
import { AssistPill } from '@/components/AssistPill'
import { useAskAssistant } from '@/components/AssistContext'
import { personId } from '@/components/PersonLink'
import { actionsPill } from '@/lib/assistPills'
import { ago, LOCALE, TZ } from '@/lib/time'

type Section = { id: string; title: string; note: string; icon: LucideIcon; empty: string; limit: number; link?: { href: string; label: string } }
const REACTIVE: Section[] = [
  { id: 'emails', title: 'Emails', note: 'waiting on a response from you', icon: InboxIcon, empty: 'No email is waiting on you.', limit: 8, link: { href: '#/inbox', label: 'Inbox' } },
  { id: 'messages', title: 'Teams and Slack', note: 'messages you owe an answer', icon: MessagesSquare, empty: 'No message is waiting on an answer.', limit: 6, link: { href: '#/messages', label: 'Messages' } },
  { id: 'followups', title: 'From your meetings', note: 'what was asked or agreed in your calls', icon: CalendarDays, empty: 'No follow-ups from your meetings of the last two weeks.', limit: 8, link: { href: '#/meetings', label: 'Meetings' } },
]
const PROACTIVE: Section[] = [
  { id: 'send', title: 'Ready to send', note: 'emails and messages SleePO wrote for you', icon: Send, empty: 'Nothing written and waiting to be sent.', limit: 5 },
  { id: 'promises', title: 'Promises you made', note: 'what you said you would do', icon: Handshake, empty: 'No open promises.', limit: 5, link: { href: '#/tasks', label: 'Tasks' } },
  { id: 'next', title: 'Suggested next steps', note: 'chases, decisions and preparation', icon: Lightbulb, empty: 'No suggestions waiting.', limit: 5, link: { href: '#/tasks', label: 'Tasks' } },
]

type Gone = { text: string; undo?: () => Promise<unknown> } | null
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function ActionsPage() {
  const q = useQuery({ queryKey: ['actions'], queryFn: api.actions })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const qc = useQueryClient()
  const [hidden, setHidden] = useState<string[]>([])   // rows acted on, gone at once (the refetch confirms it)
  const [gone, setGone] = useState<Gone>(null)
  useEffect(() => { if (!gone) return; const t = setTimeout(() => setGone(null), 8000); return () => clearTimeout(t) }, [gone])
  const refresh = (...keys: string[]) => { for (const k of ['actions', ...keys]) qc.invalidateQueries({ queryKey: [k] }) }
  // run an action on a row: hide it, say what happened, offer Undo when there is one
  const act = async (r: ActionItem, text: string, run: () => Promise<unknown>, undo?: () => Promise<unknown>, keys: string[] = []) => {
    setHidden((h) => [...h, r.key])
    try {
      await run()
      setGone({ text, undo: undo && (async () => { await undo(); setHidden((h) => h.filter((k) => k !== r.key)); refresh(...keys) }) })
    } catch (e) {
      setHidden((h) => h.filter((k) => k !== r.key))
      setGone({ text: `Could not do that: ${msg(e)}` })
    }
    refresh(...keys)
  }
  const person = (id: number | null) => (id == null ? undefined : people.data?.find((p) => p.id === personId(id)))
  const today = new Date().toLocaleDateString(LOCALE, { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' })
  const d = q.data
  const n = (side: keyof Omit<ActionsData, 'counts'>) => (d ? Object.values(d[side]).flat().filter((r) => !hidden.includes(r.key)).length : 0)

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Actions</h1>
        <span className="text-[14px] text-ink2">{today}</span>
      </div>
      <AssistPill className="mb-5 max-w-[860px]" target={null} {...actionsPill()} />
      {gone && (
        <div role="status" className="sticky top-0 z-10 mb-3 flex max-w-[860px] items-center gap-2 rounded-full border border-line bg-panel px-4 py-1.5 text-[12.5px] text-ink2 shadow-lg">
          <span className="min-w-0 truncate">{gone.text}</span>
          {gone.undo ? <button onClick={() => { void gone.undo!(); setGone(null) }} className="ml-auto shrink-0 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Undo</button>
            : <button onClick={() => setGone(null)} aria-label="Dismiss" className="ml-auto shrink-0 text-ink hover:opacity-70"><X size={13} aria-hidden /></button>}
        </div>)}
      {q.error && <div role="alert" className="mb-3 border border-l-2 border-line border-l-hot bg-panel px-3 py-2 text-[13px]">Actions could not load: {msg(q.error)}</div>}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Column title="Reactive" note="People waiting on you" count={n('reactive')} loading={!d}>
          {REACTIVE.map((s) => <Block key={s.id} s={s} rows={(d?.reactive[s.id as keyof ActionsData['reactive']] ?? []).filter((r) => !hidden.includes(r.key))}
            loading={!d} render={(r) => <Row key={r.key} r={r} who={person(r.person_id)} act={act} />} />)}
        </Column>
        <Column title="Proactive" note="What SleePO recommends you start" count={n('proactive')} loading={!d}>
          {PROACTIVE.map((s) => <Block key={s.id} s={s} rows={(d?.proactive[s.id as keyof ActionsData['proactive']] ?? []).filter((r) => !hidden.includes(r.key))}
            loading={!d} render={(r) => <Row key={r.key} r={r} who={person(r.person_id)} act={act} />} />)}
        </Column>
      </div>
    </div>
  )
}

function Column({ title, note, count, loading, children }: { title: string; note: string; count: number; loading: boolean; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-4">
      <div className="flex items-baseline gap-2 border-b-2 border-ink pb-1.5">
        <h2 className="text-[19px] font-semibold tracking-[-0.01em]">{title}</h2>
        <span className="text-[13px] text-ink2">{note}</span>
        {!loading && <span className="ml-auto text-[13px] font-semibold tabular-nums">{count}</span>}
      </div>
      {children}
    </section>
  )
}

function Block({ s, rows, loading, render }: { s: Section; rows: ActionItem[]; loading: boolean; render: (r: ActionItem) => ReactNode }) {
  const [all, setAll] = useState(false)
  const shown = all ? rows : rows.slice(0, s.limit)
  // follow-ups are grouped under their meeting, newest meeting first (the server's order)
  const groups = s.id === 'followups' ? shown.reduce<{ head: ActionItem['meeting']; rows: ActionItem[] }[]>((g, r) => {
    const last = g[g.length - 1]
    if (last && last.head?.id === r.meeting?.id) last.rows.push(r); else g.push({ head: r.meeting, rows: [r] })
    return g
  }, []) : null
  return (
    <div className="min-w-0 border border-line bg-panel">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2">
        <s.icon size={15} aria-hidden className="shrink-0" />
        <h3 className="text-[14px] font-semibold">{s.title}</h3>
        <span className="min-w-0 truncate text-[12.5px] text-ink2 max-sm:hidden">{s.note}</span>
        {!loading && rows.length > 0 && <span className="ml-auto shrink-0 text-[12.5px] font-semibold tabular-nums">{rows.length}</span>}
        {s.link && <a href={s.link.href} className={cn(btnClass('ghost', 'xs', 'shrink-0 text-ink2 hover:text-ink'), !(rows.length > 0) && 'ml-auto')}>{s.link.label}<ArrowRight size={12} aria-hidden /></a>}
      </div>
      {loading ? <div className="px-4 py-3 text-[12.5px] text-ink2">Loading…</div>
        : rows.length === 0 ? <div className="px-4 py-3 text-[12.5px] text-ink2">{s.empty}</div>
        : <ul>{groups ? groups.map((g, i) => (
            <li key={`${g.head?.id ?? 'm'}-${i}`}>
              {g.head && <a href={`#${g.head.url}`} className="flex items-baseline gap-2 border-b border-line2 bg-panel2 px-4 py-1 text-[12px] text-ink2 no-underline hover:text-ink">
                <span className="min-w-0 truncate font-medium text-ink">{g.head.title}</span>{g.head.at && <span className="shrink-0">{ago(g.head.at, 'long')}</span>}</a>}
              <ul>{g.rows.map(render)}</ul>
            </li>)) : shown.map(render)}</ul>}
      {rows.length > s.limit && (
        <button onClick={() => setAll(!all)} className="w-full border-t border-line2 px-4 py-1.5 text-left text-[12.5px] font-medium text-ink2 hover:bg-panel2 hover:text-ink">
          {all ? 'Show fewer' : `Show ${rows.length - s.limit} more`}</button>)}
    </div>
  )
}

type Act = (r: ActionItem, text: string, run: () => Promise<unknown>, undo?: () => Promise<unknown>, keys?: string[]) => Promise<void>

function Mark({ r, who }: { r: ActionItem; who?: Person }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 300_000 })
  const logo = r.app && r.app !== 'outlook' ? meta.data?.logos?.[r.app] : undefined
  if (r.kind === 'email' || r.kind === 'message') {
    return (
      <span className="relative mt-0.5 shrink-0">
        <Avatar p={who ?? { name: r.who || '?', avatar: '' }} size={28} />
        <span className="absolute -bottom-1 -right-1 grid size-[15px] place-items-center rounded-full bg-panel ring-1 ring-line">
          {r.app === 'outlook' ? <OutlookLogo size={10} /> : logo ? <img src={logo} alt="" width={10} height={10} className="object-contain" /> : null}</span>
      </span>)
  }
  const Icon = r.kind === 'send' ? (r.app === 'outlook' ? null : MessagesSquare) : r.kind === 'promise' ? Handshake : r.kind === 'followup' ? CalendarDays : ListChecks
  return (
    <span className={cn('mt-0.5 grid size-7 shrink-0 place-items-center rounded-full', r.hot ? 'bg-accent text-onaccent' : 'bg-panel2 text-ink')}>
      {r.kind === 'send' && r.app === 'outlook' ? <OutlookLogo size={14} /> : logo ? <img src={logo} alt="" width={14} height={14} className="object-contain" /> : Icon ? <Icon size={14} aria-hidden /> : null}
    </span>)
}

const HOT_TAG = /^(Overdue|Due today|Due tomorrow|CEO|Waiting \d+ days)$/
const READY_TAG = /ready$/i

function Row({ r, who, act }: { r: ActionItem; who?: Person; act: Act }) {
  const chat = useAskAssistant(r.kind === 'email' ? { kind: 'email', ref: String(r.item_id) } : r.kind === 'message' ? { kind: 'message', ref: String(r.item_id) }
    : r.step_id ? { kind: 'task', ref: String(r.step_id) } : null)
  const [asking, setAsking] = useState(false)
  const ask = async (q: string) => { setAsking(true); try { await chat.ask(q) } finally { setAsking(false) } }
  const step = r.step_id
  // the line under the title: who it is with or from, and what it belongs to
  const sub = r.kind === 'email' ? r.who
    : r.kind === 'message' ? [r.why].filter(Boolean).join(' · ')
    : r.kind === 'promise' ? [r.who && `To ${r.who}`, r.made && `said ${ago(r.made, 'long')}`].filter(Boolean).join(' · ')
    : r.kind === 'send' ? [r.who && `To ${r.who}`, r.task].filter(Boolean).join(' · ')
    : r.kind === 'followup' ? [!/^Follow up:/i.test(r.task ?? '') && r.task, r.filed].filter(Boolean).join(' · ')   // the meeting is the group's heading
    : [r.task, r.filed].filter(Boolean).join(' · ')
  const when = r.kind === 'email' || r.kind === 'message' ? ago(r.ts) : ''
  const title = r.kind === 'message' ? r.who || r.title : r.title

  // the buttons: one main move, then accept / done / dismiss as fits the thing
  const main: ReactNode = r.kind === 'email' ? <a href={`#${r.open}`} className={btnClass(r.ready ? 'primary' : 'outline', 'xs')}>{r.ready ? 'Review the reply' : 'Reply'}</a>
    : r.kind === 'message' ? <button onClick={() => ask('Draft a reply to this message.')} disabled={asking || chat.busy} className={btnClass('primary', 'xs')}><Sparkles size={12} aria-hidden />Draft a reply</button>
    : r.draft ? <a href={`#/inbox?draft=${encodeURIComponent(r.draft)}`} className={btnClass('primary', 'xs')}>Open the email</a>
    // a Teams or Slack message SleePO wrote: its step in Tasks has it with Copy and open Teams / Slack
    : r.action && (r.action.type === 'teams' || r.action.type === 'slack') ? <a href={`#${r.open}`} className={btnClass('primary', 'xs')}>Open the message</a>
    : r.kind === 'promise' ? <button onClick={() => ask(`Help me keep this promise${r.who ? ` to ${r.who}` : ''}: ${r.title}. Draft the email or message that delivers it, or say what is missing.`)}
        disabled={asking || chat.busy} className={btnClass('primary', 'xs')}><Sparkles size={12} aria-hidden />Draft it</button>
    : <button onClick={() => ask(`Help me do this step: ${r.title}. Draft whatever needs writing, or say what is missing.`)} disabled={asking || chat.busy}
        className={btnClass(r.kind === 'send' ? 'primary' : 'outline', 'xs')}><Sparkles size={12} aria-hidden />Do it in chat</button>
  const secondary: ReactNode[] = []
  if (r.kind === 'email' && r.item_id) {
    const id = r.item_id
    secondary.push(<button key="none" onClick={() => act(r, `“${r.title}” no longer needs a response`, () => api.replyNeeds(id, false), () => api.replyNeeds(id, true), ['replyInbox', 'loops'])}
      title="No response needed: take it off the list" aria-label={`No response needed: ${r.title}`} className={btnClass('ghost', 'icon', 'size-6 text-ink2 hover:text-ink')}><X size={14} aria-hidden /></button>)
  }
  if (r.kind === 'message' && r.loop_id) {
    const id = r.loop_id
    secondary.push(<a key="open" href={`#${r.open}`} className={btnClass('ghost', 'xs', 'text-ink2 hover:text-ink')}>Open</a>)
    secondary.push(<button key="done" onClick={() => act(r, `Answered: ${r.who}`, () => api.loopSet(id, 'done'), () => api.loopSet(id, 'open'), ['loops'])}
      title="Answered: take it off the list" aria-label={`Answered ${r.who}`} className={btnClass('ghost', 'icon', 'size-6 text-ink2 hover:text-ink')}><Check size={14} aria-hidden /></button>)
  }
  if (step && r.kind !== 'email' && r.kind !== 'message') {
    if (r.suggested) {
      secondary.push(<button key="add" onClick={() => act(r, `Added to your tasks: ${r.title}`, () => api.taskPatch(step, { status: 'open' }), undefined, ['tasks', 'drafts'])}
        title="Add it to your tasks" className={btnClass('ghost', 'xs', 'text-ink2 hover:text-ink')}><Plus size={12} aria-hidden />Add</button>)
    } else {
      secondary.push(<button key="done" onClick={() => act(r, `Done: ${r.title}`, () => api.taskPatch(step, { status: 'done' }), () => api.taskPatch(step, { status: 'open' }), ['tasks', 'drafts'])}
        title="Mark it done" aria-label={`Mark done: ${r.title}`} className={btnClass('ghost', 'icon', 'size-6 text-ink2 hover:text-ink')}><Check size={14} aria-hidden /></button>)
    }
    if (r.kind === 'send' && r.draft && r.index != null) {   // the Drafts folder's Remove, with its undo
      const idx = r.index
      secondary.push(<button key="remove" onClick={() => act(r, `Removed “${r.title}”`, () => api.draftsExclude(step, idx), () => api.draftsExclude(step, idx, true), ['drafts', 'tasks'])}
        title="Not worth sending: remove it" aria-label={`Remove ${r.title}`} className={btnClass('ghost', 'icon', 'size-6 text-ink2 hover:text-ink')}><X size={14} aria-hidden /></button>)
    } else if (r.suggested) {
      secondary.push(<button key="dismiss" onClick={() => act(r, `Dismissed: ${r.title}`, () => api.taskPatch(step, { status: 'dismissed' }), undefined, ['tasks', 'drafts'])}
        title="Not worth doing: dismiss it" aria-label={`Dismiss ${r.title}`} className={btnClass('ghost', 'icon', 'size-6 text-ink2 hover:text-ink')}><X size={14} aria-hidden /></button>)
    }
  }

  return (
    <li className="group border-b border-line2 px-4 py-2.5 last:border-b-0 hover:bg-panel2/60">
      <div className="flex gap-3">
        <Mark r={r} who={who} />
        <div className="min-w-0 flex-1">
          <a href={`#${r.open}`} title={r.why || r.rank_why?.join(' · ') || undefined} className="block text-ink no-underline">
            <span className="flex items-baseline gap-2">
              <span className="min-w-0 truncate text-[13.5px] font-medium">{title}</span>
              {when && <span className="ml-auto shrink-0 text-[12px] text-ink2">{when}</span>}
            </span>
            {sub && <span className="block truncate text-[12.5px] text-ink2">{sub}</span>}
            {r.line && <span className="mt-0.5 line-clamp-2 block text-[12.5px] leading-snug text-ink3">{r.line}</span>}
          </a>
          {r.said && <a href={r.said.url.replace(/^#?/, '#')} className="mt-0.5 block truncate text-[12px] text-ink2 underline decoration-line underline-offset-2 hover:text-ink">{r.said.label}</a>}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {r.tags.map((t) => <span key={t} className={cn('rounded-full px-1.5 py-px text-[11px]', READY_TAG.test(t) ? 'bg-accentbg text-ink' : HOT_TAG.test(t) && r.hot ? 'bg-panel2 font-medium text-hot' : 'bg-panel2 text-ink2')}>{t}</span>)}
            <span className="ml-auto flex items-center gap-1">{secondary}{main}</span>
          </div>
        </div>
      </div>
    </li>
  )
}
