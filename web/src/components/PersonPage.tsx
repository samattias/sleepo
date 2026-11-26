// One person (People › person), redesigned 18 Nov 2026 (Sam: "a lot of information there, almost too much ... figure out what
// the most relevant information is"). The page answers four questions, in this order, and keeps the rest one click away:
//   Where do we stand?       the summary at the top, with what to raise next time
//   Who is this to me?       the header: role, how they are tied to the user, when you were last in touch
//   What is open between us? Between you: what the user owes them and what they owe the user, fresh first, stale folded
//   What are we on now?      On the table: the current Top of mind topics they raised or are part of; Last time you met
//   When do we talk next?    the side column: the next meeting (and the next 1:1), notes, their people and bets
// Tabs hold the long lists: History (every conversation, or only their own words), Documents, Profile. Counts, the
// contact sparkline and per-row numbers are gone: they described the data rather than the person.
// Above all of it sits Where things stand: a few sentences SleePO writes from what was said (assist/person_summary.py), with
// its sources and its age, rewritten when the page opens and something came in since.
// Data: /api/people/{id}/page (assist/person_page.py), /api/people/{id}/summary and the entity timeline.
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CalendarClock, Check, CircleDot, ExternalLink, FileText, Hash, Lock, Mail, MessageSquare, RefreshCw, Video, X, type LucideIcon } from 'lucide-react'
import { api, type Loop, type Person, type PersonDoc, type PersonPageData, type PersonSaid, type PersonSummaryRef, type PersonTopic, type PersonUpcoming } from '@/lib/api'
import { cn, joinLabel } from '@/lib/util'
import { isMe as isUser } from '@/lib/profile'
import { personPill } from '@/lib/assistPills'
import { AssistPill } from './AssistPill'
import { PersonActivity } from './PersonActivity'
import { PersonLink } from './PersonLink'
import { Avatar, AvatarStack, btnClass, Loading, Markdown, Segmented } from './ui'
import { TZ, LOCALE } from '@/lib/time'

export const PERSON_TABS = ['overview', 'activity', 'said', 'documents', 'profile'] as const   // 'said' is History › In their words
export type PersonTab = (typeof PERSON_TABS)[number]

const z = (s: string) => new Date(/Z$|[+-]\d\d:\d\d$/.test(s) ? s : s + 'Z')
const fmt = (s: string, o: Intl.DateTimeFormatOptions) => { try { return new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, ...o }).format(z(s)) } catch { return '' } }
const day = (s?: string | null) => (s ? fmt(s, { weekday: 'short', day: 'numeric', month: 'short' }) : '')
const dayTime = (s: string) => fmt(s, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const clock = (s: string) => fmt(s, { hour: '2-digit', minute: '2-digit' })
const ago = (s?: string | null) => {
  if (!s) return ''
  const d = Math.floor((Date.now() - z(s).getTime()) / 864e5)
  return d <= 0 ? 'today' : d === 1 ? 'yesterday' : d < 14 ? `${d} days ago` : d < 60 ? `${Math.round(d / 7)} weeks ago` : `${Math.round(d / 30)} months ago`
}
const until = (s: string) => {
  const t = new Intl.DateTimeFormat('en-CA', { timeZone: TZ }), today = t.format(new Date()), d = t.format(z(s))
  const tom = t.format(new Date(Date.now() + 864e5))
  return d === today ? `Today ${clock(s)}` : d === tom ? `Tomorrow ${clock(s)}` : dayTime(s)
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const more = 'text-[13px] font-medium underline decoration-accent decoration-2 underline-offset-2'

export function PersonView({ id, tab = 'overview', people, me, onTab }: { id: string; tab?: PersonTab; people: Person[]; me: ReactNode; onTab: (t: PersonTab) => void }) {
  const p = useQuery({ queryKey: ['person', id], queryFn: () => api.person(id) })
  const page = useQuery({ queryKey: ['person-page', id], queryFn: () => api.personPage(id) })
  if (!p.data) return <Loading />
  const x = p.data, d = page.data
  const first = x.name.split(' ')[0]
  const num = Number(id.match(/\d+$/)?.[0] ?? 0)
  const isMe = x.status === 'me'
  const docs = (d?.documents ?? []).filter((doc) => !doc.sensitive)
  const history = tab === 'activity' || tab === 'said'
  const tabs: [PersonTab, string, boolean][] = [['overview', 'Overview', tab === 'overview'], ['activity', 'History', history],
    ['documents', `Documents${d ? ` · ${docs.length}` : ''}`, tab === 'documents'], ['profile', 'Profile', tab === 'profile']]
  return (
    <div className="max-w-[1180px]">
      <Link to="/people" className="mb-3 inline-block text-[13px] font-medium">← People</Link>
      <header className="flex flex-wrap items-start gap-4">
        <Avatar p={x} size={56} />
        <div className="min-w-0 flex-1">
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.01em]">{x.name}</h1>
          <Who x={x} people={people} />
          {!isMe && d && <Contact d={d} />}
        </div>
        {!isMe && d && (d.email || d.teams) && <div className="flex flex-wrap gap-1.5">
          {d.email && <a href={`mailto:${d.email}`} className={btnClass('outline')}><Mail size={13} />Email</a>}
          {d.teams && <a href={d.teams} target="_blank" rel="noopener" className={btnClass('outline')}><MessageSquare size={13} />Teams</a>}
        </div>}
      </header>
      {/* the assistant pill (Sam, 16 Nov 2026): ask about them, write to them, prep the next talk, with their chip */}
      {!isMe && num > 0 && <AssistPill className="mt-4 max-w-[860px]" target={{ kind: 'person', ref: String(num) }} {...personPill(x.name)} />}
      {isMe ? <div className="mt-5 border-t border-line pt-5">{me}</div> : <>
        <nav role="tablist" aria-label={`About ${first}`} className="sticky top-12 z-[3] mt-5 flex gap-1 overflow-x-auto border-b border-line bg-bg">
          {tabs.map(([k, l, on]) => <button key={k} role="tab" aria-selected={on} onClick={() => onTab(k)}
            className={cn('-mb-px shrink-0 border-b-2 px-3 py-2 text-[14px]', on ? 'border-accent font-semibold text-ink' : 'border-transparent text-ink2 hover:text-ink')}>{l}</button>)}
        </nav>
        <div className="mt-5">
          {!d ? <Loading /> : tab === 'overview' ? (
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
              <div className="min-w-0"><Overview d={d} pageId={id} id={num} name={x.name} onTab={onTab} /></div>
              <aside className="space-y-7"><Side x={x} d={d} people={people} onTab={onTab} /></aside>
            </div>)
            : history ? <>
              <Segmented className="mb-3" value={tab} onChange={onTab} label="Show" options={[['activity', 'Every conversation'], ['said', `In ${first}'s words`]]} />
              {tab === 'said' ? <Said d={d} first={first} /> : num > 0 && <PersonActivity id={num} name={x.name} />}
            </>
            : tab === 'documents' ? <Documents d={d} first={first} />
            : <Profile x={x} d={d} />}
        </div>
      </>}
    </div>
  )
}

// ---------------------------------------------------------------- header
// What they do, then how they are tied to the user: "Reports to you", "Your manager", "Partner · Tailspin Ltd",
// "Reports to Milo Marsh", and how SleePO's profile describes the relationship.
function Who({ x, people }: { x: Person; people: Person[] }) {
  const meta = [x.title || x.affiliation_note, x.department, x.location].filter(Boolean).join(' · ')
  const mgr = x.manager ? people.find((q) => q.name === x.manager) : undefined
  const ties: ReactNode[] = []
  if (x.status === 'me') ties.push('You')
  else if (x.manager && isUser(x.manager)) ties.push('Reports to you')
  else if (x.directs.some((n) => isUser(n))) ties.push('Your manager')
  else if (x.affiliation !== 'employee' && !x.relationship) ties.push(cap([x.affiliation, x.org].filter(Boolean).join(' · ')))   // the note says it otherwise
  else if (x.manager) ties.push(<>Reports to <PersonLink id={mgr?.id}>{x.manager}</PersonLink></>)
  const note = x.relationship || (x.affiliation !== 'employee' && x.affiliation_note !== x.title ? x.affiliation_note : '')
  if (note) ties.push(cap(note))
  return <>
    {meta && <div className="mt-0.5 text-[14px] text-ink2">{meta}</div>}
    {ties.length > 0 && <div className="mt-1 text-[13px]">{ties.map((t, i) => <span key={i}>{i > 0 && <span className="text-ink3"> · </span>}{t}</span>)}</div>}
  </>
}

// When you were last in touch, on which channel, and how often you usually are; "quieter than usual" when the gap since is
// three times the usual one (and at least a week): the keep-in-touch signal, without a chart.
function Contact({ d }: { d: PersonPageData }) {
  const last = (Object.entries(d.last) as [string, NonNullable<PersonPageData['last']['email']>][]).sort((a, b) => (a[1].ts < b[1].ts ? 1 : -1))[0]
  if (!last) return <div className="mt-1 text-[12.5px] text-ink2">No contact on record in the last 12 weeks</div>
  const gap = d.contact.usual_gap, since = d.contact.since_last
  const how = last[0] === 'chat' ? (last[1].where === 'DM' ? 'Teams' : 'chat') : last[0]
  const quiet = since != null && gap != null && since >= Math.max(7, gap * 3)
  return (
    <div className="mt-1 text-[12.5px] text-ink2">
      Last in touch {ago(last[1].ts)} by {how}
      {gap != null && <> · usually {gap <= 1 ? 'most days' : `every ${gap} days`}</>}
      {quiet && <span className="font-medium text-hot"> · quieter than usual</span>}
    </div>
  )
}

// ---------------------------------------------------------------- overview
function Block({ title, right, children, id }: { title: ReactNode; right?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section id={id} className="mb-8 scroll-mt-28">
      <div className="mb-2 flex items-baseline gap-2"><h2 className="text-[15px] font-semibold">{title}</h2>{right && <div className="ml-auto">{right}</div>}</div>
      {children}
    </section>
  )
}

function Overview({ d, pageId, id, name, onTab }: { d: PersonPageData; pageId: string; id: number; name: string; onTab: (t: PersonTab) => void }) {
  const first = name.split(' ')[0]
  const met = d.said.find((s) => s.kind === 'meeting')
  const [allTopics, setAllTopics] = useState(false)   // the three they raised or are most in; the rest folded
  return <>
    <Stand d={d} pageId={pageId} />
    <Between d={d} pageId={pageId} first={first} name={name} />
    {(d.topics ?? []).length > 0 && <Block title="On the table" right={<Link to="/initiatives" className={more}>Top of mind</Link>}>
      <ul className="border border-line bg-panel">{(allTopics ? d.topics : d.topics.slice(0, 3)).map((t) => <TopicRow key={t.id} t={t} first={first} />)}</ul>
      {d.topics.length > 3 && <button onClick={() => setAllTopics(!allTopics)} className="mt-1.5 text-[12.5px] text-ink2 hover:text-ink">{allTopics ? 'Show fewer' : `${d.topics.length - 3} more ${first} is part of`}</button>}
    </Block>}
    {met && <Block title="Last time you met" right={<button onClick={() => onTab('said')} className={more}>In {first}'s words</button>}>
      <div className="border border-line bg-panel"><SaidRow s={met} first={first} compact /></div>
    </Block>}
    <Block title="Recent conversations" right={<button onClick={() => onTab('activity')} className={more}>Full history</button>}>
      <PersonActivity id={id} name={name} compact limit={4} onMore={() => onTab('activity')} />
    </Block>
  </>
}

// ---------------------------------------------------------------- where things stand
// Written when the page opens with none, or when the newest is over 6 hours old and something came in with them since (or
// the prompt changed); Refresh writes it now. Every sentence carries its sources as chips that open them.
const REF = /\[([LTMECK]\d+)\]/g
const REF_ICON: Record<PersonSummaryRef['kind'], LucideIcon> = { item: CircleDot, topic: Hash, meeting: Video, email: Mail, chat: MessageSquare, event: CalendarClock }
function Src({ k, refs }: { k: string; refs: Record<string, PersonSummaryRef> }) {
  const r = refs[k]
  if (!r) return null
  const I = REF_ICON[r.kind] ?? CircleDot
  const tip = [r.label, r.date ? day(r.date) : ''].filter(Boolean).join(' · ')
  // a small round mark per source, its name on hover: the sentence stays readable with three sources after it
  return (
    <a href={r.url || undefined} target={r.url.startsWith('http') ? '_blank' : undefined} rel="noopener" title={tip} aria-label={`Source: ${tip}`}
      className="relative top-[-1px] mx-px inline-flex size-[18px] items-center justify-center rounded-full border border-line bg-panel align-middle text-ink2 no-underline hover:border-ink hover:bg-accent hover:text-onaccent">
      <I size={10} aria-hidden /></a>
  )
}
function Cited({ text, refs }: { text: string; refs: Record<string, PersonSummaryRef> }) {
  return <>{text.split(REF).map((p, i) => (i % 2 ? <Src key={i} k={p} refs={refs} /> : <Fragment key={i}>{p}</Fragment>))}</>
}

function Stand({ d, pageId }: { d: PersonPageData; pageId: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['person-summary', pageId], queryFn: () => api.personSummary(pageId), refetchInterval: (x) => (x.state.data?.running ? 2500 : false) })
  const start = useMutation({ mutationFn: () => api.personSummaryStart(pageId), onSettled: () => qc.invalidateQueries({ queryKey: ['person-summary', pageId] }) })
  const asked = useRef(false)
  const s = q.data, rec = s?.summary
  const hours = rec ? (Date.now() - z(rec.created_at).getTime()) / 36e5 : Infinity
  const busy = !!s?.running || start.isPending
  const lively = d.contact.days_84 > 0 || d.open.length > 0 || (d.topics ?? []).length > 0
  const want = !!s && !busy && !s.error && lively && (!rec || (s.newer && hours > 6))
  useEffect(() => { if (want && !asked.current) { asked.current = true; start.mutate() } }, [want, start])
  if (!s || (!rec && !busy && !s.error && !lively)) return null
  const when = rec ? (hours < 20 ? `Updated ${clock(rec.created_at)}` : `Updated ${day(rec.created_at)}`) : ''
  return (
    <section aria-label="Where things stand" className="mb-8 border border-line bg-panel px-4 py-3.5">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2">
        <h2 className="text-[15px] font-semibold">Where things stand</h2>
        <span className="ml-auto flex items-center gap-2 text-[12px] text-ink2">
          {busy ? 'Reading what is between you…' : <>{when}{rec && s.newer && ' · new since'}</>}
          {!busy && <button onClick={() => start.mutate()} className={btnClass('ghost', 'xs', 'text-ink2')} title="Write it again from what SleePO holds now"><RefreshCw size={12} />Refresh</button>}
        </span>
      </div>
      {rec ? <div className={cn(busy && 'opacity-60')}>
        <p className="text-[14px] leading-relaxed [overflow-wrap:anywhere]"><Cited text={rec.summary.situation} refs={rec.refs} /></p>
        {rec.summary.raise.length > 0 && <>
          <h3 className="mb-1 mt-3 text-[12.5px] font-medium text-ink2">Raise next time</h3>
          <ul className="space-y-1">{rec.summary.raise.map((r, i) => (
            <li key={i} className="flex gap-2 text-[13.5px] leading-snug"><span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent ring-1 ring-ink/20" />
              <span>{r.text}{r.refs.map((k) => <Src key={k} k={k} refs={rec.refs} />)}</span></li>))}</ul>
        </>}
      </div> : busy ? <div className="space-y-2 py-1" aria-hidden><div className="h-3 w-11/12 animate-pulse rounded bg-panel2" /><div className="h-3 w-4/5 animate-pulse rounded bg-panel2" /><div className="h-3 w-2/3 animate-pulse rounded bg-panel2" /></div>
        : s.error && <p className="text-[13px] text-ink2">SleePO could not write it this time ({s.error.slice(0, 140)}).</p>}
      {!busy && !rec && s.error && <button onClick={() => start.mutate()} className={cn(more, 'mt-1')}>Try again</button>}
    </section>
  )
}

// What the user owes them (replies, promises, decisions) and what they owe the user (waits), from the open-items register.
// Items with no movement for a while (decide or drop) are folded under the fresh ones; each can be marked done or dropped
// here, and its words open where it was said.
const KIND: Record<Loop['kind'], string> = { reply: 'Reply owed', promise: 'You promised', decision: 'To decide', waiting: 'Waiting' }
const ORDER: Loop['kind'][] = ['reply', 'decision', 'promise', 'waiting']
const srcOf = (l: Loop) => {
  if (l.said) return { url: `#/meetings/m-${l.said.meeting_id}?t=${l.said.t}`, where: `said in a meeting at ${l.said.clock}` }
  const u = l.links.find((k) => k.url)?.url ?? ''
  return { url: u, where: /#\/(mail|inbox)/.test(u) ? 'email' : /#\/messages/.test(u) ? 'message' : /#\/meetings/.test(u) ? 'meeting' : '' }
}
function tidy(l: Loop, name: string) {   // the heading already says who: "Gray Selby to submit the review" -> "Submit the review"
  const n = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const t = l.title.replace(new RegExp(`^${n} to `, 'i'), '').replace(new RegExp(`^Reply to ${n}:\\s*`, 'i'), 'Reply: ')
  return cap(t)
}

type LoopSet = (id: number, status: 'done' | 'dropped') => void
function LoopRow({ l, name, busy, onSet }: { l: Loop; name: string; busy: boolean; onSet: LoopSet }) {
  const s = srcOf(l), old = l.suggestion === 'decide_or_drop'
  return (
    <li className="group relative border-b border-line2 last:border-b-0">
      <a href={s.url || `#/loops?open=${l.id}`} className="block px-3 py-2.5 font-normal text-ink no-underline hover:bg-panel2">
        <span className="block text-[13.5px] leading-snug [overflow-wrap:anywhere]">{tidy(l, name)}</span>
        <span className="mt-0.5 block text-[12px] text-ink2">{[KIND[l.kind], s.where, l.due ? `due ${day(l.due)}` : '', ago(l.origin_at), old ? 'no movement since' : ''].filter(Boolean).join(' · ')}</span>
      </a>
      {/* over the row on hover, so the words keep the full width (and phones, without hover, the whole row) */}
      <span className="absolute right-2 top-2 flex gap-1 rounded-full bg-panel p-0.5 opacity-0 shadow-sm transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <button onClick={() => onSet(l.id, 'done')} disabled={busy} className={btnClass('outline', 'xs')} title="It is done"><Check size={12} />Done</button>
        <button onClick={() => onSet(l.id, 'dropped')} disabled={busy} className={btnClass('ghost', 'xs')} title="Not worth doing: drop it"><X size={12} />Drop</button>
      </span>
    </li>
  )
}
function LoopGroup({ title, ls, ...rest }: { title: string; ls: Loop[]; name: string; busy: boolean; onSet: LoopSet }) {
  if (!ls.length) return null
  return <>
    <h3 className="mb-1 mt-3 text-[12.5px] font-medium text-ink2 first:mt-0">{title}</h3>
    <ul className="border border-line bg-panel">{ls.map((l) => <LoopRow key={l.id} l={l} {...rest} />)}</ul>
  </>
}

function Between({ d, pageId, first, name }: { d: PersonPageData; pageId: string; first: string; name: string }) {
  const qc = useQueryClient()
  const [older, setOlder] = useState(false)
  const set = useMutation({ mutationFn: ({ id, status }: { id: number; status: 'done' | 'dropped' }) => api.loopSet(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['person-page', pageId] }) })
  const stale = d.open.filter((l) => l.suggestion === 'decide_or_drop')
  const rows = [...(older ? d.open : d.open.filter((l) => l.suggestion !== 'decide_or_drop'))].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind))
  const mine = rows.filter((l) => l.kind !== 'waiting'), theirs = rows.filter((l) => l.kind === 'waiting')
  return (
    <Block id="open-items" title="Between you" right={<Link to="/loops" className={more}>Open items</Link>}>
      {d.open.length === 0 ? <p className="text-[13px] text-ink2">Nothing open between you.</p> : <>
        {rows.length === 0 && <p className="text-[13px] text-ink2">Nothing new between you.</p>}
        <LoopGroup title={`You owe ${first}`} ls={mine} name={name} busy={set.isPending} onSet={(id, status) => set.mutate({ id, status })} />
        <LoopGroup title={`${first} owes you`} ls={theirs} name={name} busy={set.isPending} onSet={(id, status) => set.mutate({ id, status })} />
        {stale.length > 0 && <button onClick={() => setOlder(!older)} className="mt-2 text-[12.5px] text-ink2 hover:text-ink">
          {older ? 'Hide the older ones' : <>{stale.length} older with no movement · <span className="font-medium text-hot">decide or drop</span></>}</button>}
      </>}
    </Block>
  )
}

function TopicRow({ t, first }: { t: PersonTopic; first: string }) {
  const by = t.raised === 'them' ? `${first} raised it` : t.raised === 'you' ? 'You raised it' : ''
  return (
    <li className="border-b border-line2 last:border-b-0">
      <Link to="/topics/$id" params={{ id: String(t.id) }} className="block px-3 py-2.5 font-normal text-ink no-underline hover:bg-panel2">
        <span className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 text-[13.5px] font-medium leading-snug">{t.title}{t.private && <Lock size={11} aria-label="People matter: private" className="ml-1.5 inline align-baseline" />}</span>
          {by && <span className="shrink-0 text-[12px] text-ink2">{by}</span>}
        </span>
        {t.summary && <span className="mt-0.5 block line-clamp-2 text-[12.5px] leading-snug text-ink2">{t.summary}</span>}
        {(t.initiative || t.area_name || t.ask) && <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
          {(t.initiative || t.area_name) && <span className="rounded-full bg-panel2 px-2 py-px text-ink2">{t.initiative || t.area_name}</span>}
          {t.ask && <span className="min-w-0 truncate"><span className="font-medium">On you:</span> {t.ask}</span>}
        </span>}
      </Link>
    </li>
  )
}

// ---------------------------------------------------------------- side column
function Side({ x, d, people, onTab }: { x: Person; d: PersonPageData; people: Person[]; onTab: (t: PersonTab) => void }) {
  return <>
    <NextMeeting d={d} />
    <Notes x={x} d={d} onTab={onTab} />
    <Org x={x} d={d} people={people} />
    <Bets d={d} />
  </>
}

function SideBlock({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return <section><div className="mb-1.5 flex items-baseline gap-2"><h2 className="text-[14px] font-semibold">{title}</h2>{right && <div className="ml-auto">{right}</div>}</div>{children}</section>
}

function MeetingRow({ u, label }: { u: PersonUpcoming; label?: string }) {
  return (
    <div className="border-b border-line2 px-3 py-2.5 last:border-b-0">
      {label && <div className="text-[12px] text-ink2">{label}</div>}
      <div className="text-[14px] font-semibold">{until(u.start)}</div>
      <div className="text-[13px] leading-snug [overflow-wrap:anywhere]">{u.subject}<span className="text-ink2">{u.one_to_one ? ' · 1:1' : u.others > 1 ? ` · ${u.others} people` : ''}</span></div>
      <div className="mt-1 flex gap-3 text-[12.5px]">
        <Link to="/prep" search={{ event: u.event_id }}>{u.brief ? 'Brief ready' : 'Prepare'}</Link>
        {u.join_url && <a href={u.join_url} target="_blank" rel="noopener">{joinLabel(u.join_url).replace(' meeting', '')}</a>}
      </div>
    </div>
  )
}

// The next meeting with them, and the next 1:1 when that is a different one; the rest of the fortnight folded.
function NextMeeting({ d }: { d: PersonPageData }) {
  const [all, setAll] = useState(false)
  const next = d.upcoming[0], one = d.upcoming.find((u) => u.one_to_one)
  const shown = next ? (one && one !== next ? [next, one] : [next]) : []
  const rest = d.upcoming.filter((u) => !shown.includes(u))
  return (
    <SideBlock title="Next meeting">
      {!next ? <p className="text-[13px] text-ink2">Nothing booked in the next two weeks.</p> : <>
        <div className="border border-line bg-panel">
          {shown.map((u, i) => <MeetingRow key={u.event_id + u.start} u={u} label={i === 1 ? 'Next 1:1' : undefined} />)}
          {all && rest.map((u) => <MeetingRow key={u.event_id + u.start} u={u} />)}
        </div>
        {rest.length > 0 && <button onClick={() => setAll(!all)} className="mt-1.5 text-[12.5px] text-ink2 hover:text-ink">
          {all ? 'Show fewer' : `${rest.length} more in the next two weeks`}</button>}
      </>}
    </SideBlock>
  )
}

// What the user told SleePO about them (assist/remember.py), and how they work from the profile SleePO keeps.
function Notes({ x, d, onTab }: { x: Person; d: PersonPageData; onTab: (t: PersonTab) => void }) {
  const mem = useQuery({ queryKey: ['memory'], queryFn: api.memory })
  const remembered = (mem.data?.memories ?? []).filter((m) => m.status === 'active' && m.people_ids.includes(d.id))
  const how = workStyle(x.profile ?? '').slice(0, 3)
  if (!remembered.length && !how.length) return null
  return (
    <SideBlock title="Notes" right={x.profile ? <button onClick={() => onTab('profile')} className={cn(more, 'text-[12.5px]')}>Profile</button> : undefined}>
      <ul className="space-y-1.5 text-[13px] leading-snug">
        {remembered.map((m) => <li key={m.id} className="border-l-2 border-accent pl-2"><span className="text-ink2">You told SleePO: </span>{m.text}</li>)}
        {how.map((h, i) => <li key={i} className="border-l-2 border-line pl-2">{h}</li>)}
      </ul>
    </SideBlock>
  )
}

// the bullets of the profile's "How they work / what they care about" section (memory/people/<name>.md)
function workStyle(md: string) {
  const m = md.match(/^##\s*How (?:they|he|she) work[^\n]*\n([\s\S]*?)(?=^##\s|$(?![\s\S]))/im)
  return m ? m[1].split('\n').map((l) => l.replace(/^\s*[-*]\s+/, '').trim()).filter((l) => l && !l.startsWith('#')) : []
}

function OrgLine({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex items-center gap-3 py-1"><span className="w-[112px] shrink-0 text-[12px] text-ink2">{label}</span><span className="min-w-0">{children}</span></div>
}

function Org({ x, d, people }: { x: Person; d: PersonPageData; people: Person[] }) {
  const byName = (n: string) => people.find((q) => q.name === n)
  const byId = (i: number) => people.find((q) => q.id === `p-${i}`)
  const mgr = x.manager && !isUser(x.manager) ? byName(x.manager) : undefined
  const withNames = d.with.map((w) => byId(w.id)?.name ?? w.name)
  if (!mgr && !x.directs.length && !withNames.length) return null
  return (
    <SideBlock title="People">
      {mgr && <OrgLine label="Reports to"><PersonLink id={mgr.id} className="flex items-center gap-2 text-[13px]"><Avatar p={mgr} size={22} />{mgr.name}</PersonLink></OrgLine>}
      {x.directs.length > 0 && <OrgLine label={`Team · ${x.directs.length}`}><AvatarStack names={x.directs} person={byName} max={7} linked /></OrgLine>}
      {withNames.length > 0 && <OrgLine label="Works most with"><AvatarStack names={withNames} person={byName} max={6} linked /></OrgLine>}
    </SideBlock>
  )
}

// The bets they are a key person in (others they touch folded), and the roadmap items they own, in flight first.
function Bets({ d }: { d: PersonPageData }) {
  const [all, setAll] = useState(false)
  const [road, setRoad] = useState(false)
  const key = d.initiatives.filter((i) => i.key), others = d.initiatives.filter((i) => !i.key)
  const shown = all ? d.initiatives : key.length ? key : others.slice(0, 3)
  const flight = d.roadmap.filter((r) => r.status === 'inflight')
  if (!d.initiatives.length && !d.roadmap.length) return null
  return (
    <SideBlock title="Bets">
      {shown.length > 0 && <div className="flex flex-wrap gap-1.5">{shown.map((i) => (
        <Link key={i.slug} to="/initiatives/$slug" params={{ slug: i.slug }} className={cn('rounded-full border px-2.5 py-0.5 text-[12.5px] font-normal text-ink no-underline hover:border-ink', i.key ? 'border-ink/40' : 'border-line')}
          title={i.key ? 'A key person in this bet' : 'Part of their work touches this bet'}>{i.name}</Link>))}</div>}
      {d.initiatives.length > shown.length && <button onClick={() => setAll(true)} className="mt-1.5 text-[12.5px] text-ink2 hover:text-ink">{d.initiatives.length - shown.length} more they touch</button>}
      {d.roadmap.length > 0 && <div className="mt-3">
        <button onClick={() => setRoad(!road)} className="text-[13px] hover:underline">Owns {d.roadmap.length} roadmap item{d.roadmap.length > 1 ? 's' : ''}{flight.length ? ` · ${flight.length} in flight` : ''}</button>
        {road && <ul className="mt-1 border border-line bg-panel">{d.roadmap.map((r) => (
          <li key={r.id}><Link to="/roadmap" search={{ item: r.id }} className="flex items-baseline gap-2 border-b border-line2 px-2.5 py-1.5 font-normal text-ink no-underline last:border-b-0 hover:bg-panel2">
            <span className="w-[54px] shrink-0 text-[11.5px] tabular-nums text-ink2">{r.id}</span>
            <span className="min-w-0 flex-1 text-[13px] leading-snug">{r.name}</span>
            {r.status === 'inflight' && <span className="shrink-0 text-[11.5px] font-medium">In flight</span>}
          </Link></li>))}</ul>}
      </div>}
    </SideBlock>
  )
}

// ---------------------------------------------------------------- in their words
function SaidRow({ s, first, compact }: { s: PersonSaid; first: string; compact?: boolean }) {
  const ext = s.url.startsWith('http')
  if (s.kind === 'meeting') return (
    <div className="border-b border-line2 px-3 py-2.5 last:border-b-0">
      <div className="flex items-baseline gap-2"><Video size={13} aria-hidden className="shrink-0 self-center text-ink2" />
        <a href={s.url} className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{s.title}</a>
        <span className="shrink-0 text-[12px] text-ink2">{day(s.ts)}{s.share != null ? ` · ${Math.round(s.share * 100)}% of the talk` : ''}</span></div>
      {(s.points ?? []).length > 0 ? <ul className="mt-1 space-y-0.5 pl-[21px]">{(compact ? s.points!.slice(0, 3) : s.points!).map((p, i) => (
        <li key={i} className="flex gap-2 text-[13px] leading-snug">
          <a href={`#/meetings/m-${s.meeting_id}?t=${p.t}`} className="shrink-0 pt-px text-[11.5px] font-normal tabular-nums text-ink2" title="Open this moment in the transcript">{p.clock}</a><span>{p.text}</span></li>))}</ul>
        : <div className="mt-0.5 pl-[21px] text-[12px] text-ink2">{first} spoke; main points not written yet (the next refresh does it).</div>}
    </div>)
  const I = s.kind === 'email' ? Mail : MessageSquare
  return (
    <a href={s.url} target={ext ? '_blank' : undefined} rel="noopener" className="flex gap-3 border-b border-line2 px-3 py-2.5 font-normal text-ink no-underline last:border-b-0 hover:bg-panel2">
      <I size={13} aria-hidden className="mt-[3px] shrink-0 text-ink2" />
      <span className="min-w-0 flex-1">
        {s.kind === 'email' && <span className="block truncate text-[13px] font-semibold">{s.subject || '(no subject)'}</span>}
        <span className={cn('block border-l-2 border-accent pl-2 text-[13.5px] leading-snug [overflow-wrap:anywhere]', compact && 'line-clamp-3')}>{s.text}</span>
        <span className="mt-0.5 block text-[12px] text-ink2">{s.kind === 'email' ? 'Email' : s.dm ? 'Teams DM' : s.where}{` · ${day(s.ts)}, ${clock(s.ts)}`}</span>
      </span>
    </a>
  )
}

function Said({ d, first }: { d: PersonPageData; first: string }) {
  const [kind, setKind] = useState<'all' | 'meeting' | 'chat' | 'email'>('all')
  const [chan, setChan] = useState(false)
  const nCh = d.said.filter((s) => s.channel).length
  const rows = d.said.filter((s) => (kind === 'all' || s.kind === kind) && (chan || !s.channel))
  const c = (k: PersonSaid['kind']) => d.said.filter((s) => s.kind === k && (chan || !s.channel)).length
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <p className="text-[13px] text-ink2">{first}'s own words over the last 90 days: messages, emails they wrote and their main points in meetings.</p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {nCh > 0 && <label className="flex items-center gap-1.5 text-[12.5px]"><input type="checkbox" checked={chan} onChange={(e) => setChan(e.target.checked)} />Channel posts · {nCh}</label>}
          <Segmented value={kind} onChange={setKind} options={[['all', 'All'], ['meeting', `Meetings · ${c('meeting')}`], ['chat', `Chat · ${c('chat')}`], ['email', `Email · ${c('email')}`]]} />
        </div>
      </div>
      {rows.length === 0 ? <p className="text-[13px] text-ink2">Nothing here.</p> : <div className="border border-line bg-panel">{rows.map((s, i) => <SaidRow key={i} s={s} first={first} />)}</div>}
      <p className="mt-2 text-[12px] text-ink2">Meeting points are summaries of the transcript, not quotes; open the timestamp to check what was actually said.</p>
    </section>
  )
}

// ---------------------------------------------------------------- documents
const HOW: Record<PersonDoc['how'], string> = { theirs: 'Shared or sent by', sent: 'You sent to', shared_with: 'Shared with', discussed: 'Discussed in meetings with', named: 'Documents that name' }
const HOW_ROW: Record<PersonDoc['how'], string> = { theirs: 'From {first}', sent: 'You sent it', shared_with: 'Shared with {first}', discussed: 'Discussed in a meeting', named: 'Names {first}' }
const HOW_ORDER: PersonDoc['how'][] = ['theirs', 'sent', 'shared_with', 'discussed', 'named']

function DocRow({ x, first }: { x: PersonDoc; first: string }) {
  const label = x.title || x.name
  return (
    <Link to="/documents" search={{ open: x.id }} className="flex gap-3 border-b border-line2 px-3 py-2.5 font-normal text-ink no-underline last:border-b-0 hover:bg-panel2">
      <FileText size={14} aria-hidden className="mt-[3px] shrink-0 text-ink2" />
      <span className="min-w-0 flex-1">
        <span className="block text-[13.5px] font-medium leading-snug [overflow-wrap:anywhere]">{label}{x.sensitive && <Lock size={11} aria-label="HR, legal or personal" className="ml-1.5 inline align-baseline" />}</span>
        {x.title && x.title !== x.name && <span className="block truncate text-[12px] text-ink2">{x.name}</span>}
        {x.summary && <span className="mt-0.5 block line-clamp-2 text-[12.5px] leading-snug [overflow-wrap:anywhere]">{x.summary}</span>}
        <span className="mt-0.5 block truncate text-[12px] text-ink2">{[HOW_ROW[x.how].replace('{first}', first), x.kind, x.where].filter(Boolean).join(' · ')}</span>
      </span>
      <span className="shrink-0 pt-px text-[12px] tabular-nums text-ink2">{day(x.ts)}{x.copies > 1 && <span className="block text-right">{x.copies} copies</span>}</span>
    </Link>
  )
}

function Documents({ d, first }: { d: PersonPageData; first: string }) {
  const [sens, setSens] = useState(false)
  const hidden = d.documents.filter((x) => x.sensitive).length
  const list = d.documents.filter((x) => sens || !x.sensitive)
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <p className="text-[13px] text-ink2">Files {first} shared, files sent between you, files discussed in your meetings and files that name them. Opening one shows it in Documents, with a link to the original.</p>
        {hidden > 0 && <button onClick={() => setSens(!sens)} className={btnClass('outline', 'sm', 'ml-auto font-normal')}><Lock size={12} />{sens ? 'Hide' : 'Show'} {hidden} HR, legal or personal</button>}
      </div>
      {list.length === 0 && <p className="text-[13px] text-ink2">No documents linked to {first} yet.</p>}
      {HOW_ORDER.map((h) => { const rows = list.filter((x) => x.how === h); return rows.length > 0 && (
        <div key={h} className="mb-5">
          <h3 className="mb-1.5 text-[13.5px] font-semibold">{HOW[h]} {first} <span className="font-normal text-ink2">· {rows.length}</span></h3>
          <div className="border border-line bg-panel">{rows.map((x) => <DocRow key={x.id + x.name} x={x} first={first} />)}</div>
        </div>) })}
    </section>
  )
}

// ---------------------------------------------------------------- profile
function Profile({ x, d }: { x: Person; d: PersonPageData }) {
  return (
    <section>
      {x.kb && <a href={x.kb} target="_blank" rel="noopener" className={btnClass('outline', 'sm', 'mb-3')}><ExternalLink size={13} />Their page in the knowledge base</a>}
      <div className="border border-line bg-panel p-5">{x.profile ? <Markdown>{x.profile}</Markdown> : <span className="text-[13px] text-ink2">No written profile yet. Org data only.</span>}</div>
      <p className="mt-2 text-[12px] text-ink2">{d.profile_updated && `Updated ${day(d.profile_updated)}. `}Written by SleePO from your meetings and mail and kept in memory/people; it is a reading of the evidence, not a verdict on the person.</p>
    </section>
  )
}
