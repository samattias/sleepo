// Initiatives: Sam's weighted bets as hubs. The list is a portfolio (goal, topics, activity, tasks, who is
// involved); each initiative has a page with its status and suggested actions, its tasks, a timeline of everything linked to
// it, the people, suggested links to confirm, and a scoped question box. Sam, 22 Oct 2026: no "needs attention" box and no
// drafts to approve; SleePO writes the status (current at once, refreshed when stale) and suggests actions as tasks.
// Sam, 28 Oct 2026: what is top of mind first. The page opens on the topics of the last days (components/TopOfMind.tsx) and
// orders the bets by the attention they had lately (Weight keeps the old order); each row names its current topics.
// Sam, 29 Oct 2026: an initiative's page is where he works on it. Under the header, Write an email, Create a document, Decide
// and Ask in chat (components/InitiativeWork.tsx, assist/initiative_work.py); Latest reads everything linked to it in place,
// and "Work from this" picks items for those actions.
// Sam, 29 Oct 2026: no Strategy switch and no Update all statuses (a status still rewrites itself when its page opens
// stale, and each page has its own Refresh).
// Sam, 30 Oct 2026: no status in the bets list (no health dot, status line or Status column): a row is the bet, its goal,
// its topics, activity, tasks and people. The status is on the initiative's own page.
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, ChevronDown, ChevronRight, RefreshCw, Sparkles, X } from 'lucide-react'
import { api, workBase, type IniDetail, type IniLink, type IniSummary, type IniUpdate, type Person } from '@/lib/api'
import { cn } from '@/lib/util'
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { ItemRow, WorkBar, useWork, type Intent, type Pin } from '@/components/InitnfhgjcAlmi'
import { Avatar, Empty, Loading, Markdown, AvatarStack, Segmented } from '@/components/ui'
import { InitiativeTasks } from '@/views/tasks'
import { TopOfMind } from '@/components/TopOfMind'
import { TZ, LOCALE } from '@/lib/time'
import { NewSince, useGraphChanges } from '@/components/NewSince'

const day = (iso?: string | null) => iso ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(iso.length === 10 ? iso + 'T12:00:00Z' : iso)) : ''
const HEALTH: Record<string, { dot: string; label: string }> = {
  'on track': { dot: 'bg-accent ring-1 ring-ink/30', label: 'On track' }, 'at risk': { dot: 'bg-transparent ring-2 ring-inset ring-hot', label: 'At risk' },
  'off track': { dot: 'bg-hot', label: 'Off track' }, blocked: { dot: 'bg-hot', label: 'Blocked' }, '': { dot: 'bg-line', label: 'No status' },
}
const health = (h?: string | null) => HEALTH[h ?? ''] ?? HEALTH['']
const seenKey = (slug: string) => `assist-ini-seen-${slug}`
const seen = (slug: string) => { try { return localStorage.getItem(seenKey(slug)) } catch { return null } }

function useJob(onDone?: () => void) {
  const [id, setId] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['iniJob', id], queryFn: () => api.iniJob(id!), enabled: !!id, refetchInterval: (s) => (s.state.data?.running === false ? false : 2000) })
  useEffect(() => { if (q.data && !q.data.running) onDone?.() }, [q.data?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  return { start: (p: Promise<{ job: string }>) => p.then((r) => setId(r.job)), job: q.data, running: !!id && (!q.data || q.data.running) }
}

function Spark({ v }: { v: number[] }) {
  const max = Math.max(1, ...v)
  return <svg width={v.length * 7} height="20" aria-label={`activity, last ${v.length} weeks`} className="shrink-0">
    {v.map((n, i) => <rect key={i} x={i * 7} y={20 - Math.max(1.5, (n / max) * 20)} width="5" height={Math.max(1.5, (n / max) * 20)} className={i === v.length - 1 ? 'fill-ink' : 'fill-ink3/40'} />)}</svg>
}

// ---------------------------------------------------------------- portfolio
const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors disabled:opacity-60'
const SORT_KEY = 'assist-ini-sort'
const savedSort = (): 'mind' | 'weight' => { try { return localStorage.getItem(SORT_KEY) === 'weight' ? 'weight' : 'mind' } catch { return 'mind' } }

export function InitiativesPage() {
  const q = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const [sort, setSortState] = useState(savedSort)
  const setSort = (v: 'mind' | 'weight') => { setSortState(v); try { localStorage.setItem(SORT_KEY, v) } catch { /* ignore */ } }
  if (!q.data) return <Loading />
  // by attention: the bets discussed lately first (their topics' weight, then what was linked this week), the rest by weight
  const rows = sort === 'weight' ? q.data : [...q.data].sort((a, b) => (b.heat ?? 0) - (a.heat ?? 0) || b.weight - a.weight)
  const quietFrom = sort === 'mind' ? rows.findIndex((x) => !(x.topics?.length)) : -1
  return (
    <div className="max-w-[1100px]">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Initiatives</h1>
        <span className="mr-auto text-[13px] text-ink2">{q.data.length} initiatives</span>
      </div>

      <TopOfMind people={people.data} />

      <div className="mb-2 flex items-center gap-2">
        <h2 className="mr-auto text-[15px] font-semibold">Your bets</h2>
        <Segmented label="Order" value={sort} onChange={setSort}
          options={[['mind', 'Top of mind', 'The bets discussed most in the last days first'], ['weight', 'Weight', 'By the weight in your strategy']] as const} />
      </div>
      <div className="border border-line bg-panel">
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-line px-4 py-2 text-[12px] font-semibold text-ink2 md:grid-cols-[minmax(0,1fr)_90px_150px_110px]">
          <span>Initiative</span><span className="max-md:hidden">8 weeks</span><span className="max-md:hidden">Tasks</span><span className="text-right">People</span></div>
        {rows.map((x, i) => [i === quietFrom && i > 0 && <div key="quiet" className="border-b border-line2 bg-panel2 px-4 py-1.5 text-[12px] font-semibold text-ink2">Not discussed lately</div>,
          <Row key={x.slug} x={x} all={people.data} />])}
      </div>
    </div>
  )
}

function Row({ x, all }: { x: IniSummary; all?: Person[] }) {
  const fresh = x.newest && (!seen(x.slug) || x.newest > seen(x.slug)!)
  return (
    <Link to="/initiatives/$slug" params={{ slug: x.slug }} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-line2 px-4 py-3 text-ink no-underline last:border-0 hover:bg-panel2 md:grid-cols-[minmax(0,1fr)_90px_150px_110px]">
      <span className="min-w-0">
        <span className="flex items-center gap-2"><b className="truncate text-[15px]">{x.name}</b>
          <span className="shrink-0 text-[11.5px] text-ink3">w{x.weight}</span>{fresh && <span className="shrink-0 rounded-full bg-accent px-1.5 text-[10.5px] font-semibold text-onaccent">new</span>}</span>
        {x.goal && <span className="mt-0.5 block truncate text-[12.5px] text-ink2">{x.goal}</span>}
        {!!x.topics?.length && <span className="mt-1.5 flex flex-wrap gap-1" aria-label="Top of mind">
          {x.topics.slice(0, 3).map((t) => <span key={t} className="max-w-full truncate rounded-full border border-line px-2 py-px text-[11.5px] text-ink">{t}</span>)}
          {x.topics.length > 3 && <span className="px-1 text-[11.5px] text-ink3">+{x.topics.length - 3}</span>}</span>}
      </span>
      <span className="max-md:hidden"><Spark v={x.activity} /></span>
      <span className="text-[12.5px] text-ink2 max-md:hidden">{x.tasks_open ?? 0} open{(x.tasks_suggested ?? 0) > 0 && <span className="text-ink3"> · {x.tasks_suggested} suggested</span>}</span>
      <span className="flex justify-end"><AvatarStack names={x.people.map((p) => p.name)} person={(n) => all?.find((p) => p.name === n)} size={22} /></span>
    </Link>
  )
}

// ---------------------------------------------------------------- one initiative

export function InitiativePage({ slug, open }: { slug: string; open?: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['initiative', slug], queryFn: () => api.initiative(slug) })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  // what Sam works on here: the items he picked (kept per initiative); each button opens a conversation in Ask SleePO
  const base = workBase({ slug })
  const w = useWork({ base, key: `ini-${slug}` })
  const [openKey, setOpenKey] = useState<string | null>(open ?? null)   // the item read in place in Latest (kept in the address)
  useSearchSync('open', openKey)
  usePageTitle(q.data?.name)
  useEffect(() => { if (q.data?.newest) try { localStorage.setItem(seenKey(slug), new Date().toISOString()) } catch { /* ignore */ } }, [q.data?.newest, slug])
  const reload = () => { qc.invalidateQueries({ queryKey: ['initiative', slug] }); qc.invalidateQueries({ queryKey: ['portfolio'] }) }
  const verdict = async (l: IniLink, v: 'confirmed' | 'rejected' | null) => {
    qc.setQueryData<IniDetail>(['initiative', slug], (d) => d && { ...d, timeline: v === 'rejected' ? d.timeline.filter((x) => x.key !== l.key) : d.timeline.map((x) => x.key === l.key ? { ...x, verdict: v } : x),
      suggestions: d.suggestions.filter((x) => x.key !== l.key) })
    await api.iniVerdict(slug, l.ref_type, l.ref_id, v); reload()
  }
  if (q.isError) return <Empty>Unknown initiative.</Empty>
  if (!q.data) return <Loading />
  const x = q.data
  // Sam, 22 Oct 2026: one column and only what he uses. The status (with suggested actions), the tasks, the latest activity;
  // the rest (V2MOM, milestone, background) folds into About. Questions go to the chat, not a box here.
  return (
    <div className="max-w-[920px]">
      <header className="mb-4 flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">{x.name}</h1>
          {x.goal && <p className="mt-1 text-[14px] text-ink2">{x.goal}</p>}
        </div>
        <KeyPeople people={x.people} all={people.data} />
      </header>

      <WorkBar subj={{ kind: 'initiative', base, key: `ini-${slug}`, name: x.name, work: x.work }} w={w} />

      <StatusCard x={x} onChange={reload} />

      <TopOfMind initiativeId={x.id} people={people.data} />

      {/* initiative → task → step → action (Tasks, 22 Oct 2026) */}
      <section className="mb-5">
        <h2 className="mb-2 text-[15px] font-semibold">Tasks</h2>
        <InitiativeTasks initiativeId={x.id} />
      </section>

      <Latest base={base} items={x.timeline} pins={w.pins} onPin={w.togglePin} onUse={w.actFrom} onVerdict={verdict} openKey={openKey} setOpenKey={setOpenKey} />
      <About x={x} />
    </div>
  )
}

// Who is in it: the people most involved, as faces; each opens their page
function KeyPeople({ people, all }: { people: IniDetail['people']; all?: Person[] }) {
  if (!people.length) return null
  const shown = people.slice(0, 6)
  return (
    <div className="flex shrink-0 items-center pt-1.5" aria-label="People involved">
      <div className="flex -space-x-1.5">{shown.map((p) => { const full = all?.find((a) => a.name === p.name); const face = <Avatar p={full ?? { name: p.name, avatar: '' }} size={28} />
        return p.id ? <Link key={p.name} to="/people/$id" params={{ id: p.id }} title={p.name} className="rounded-full ring-2 ring-bg">{face}</Link>
          : <span key={p.name} title={p.name} className="rounded-full ring-2 ring-bg">{face}</span> })}</div>
      {people.length > shown.length && <span className="ml-1.5 text-[12px] text-ink3">+{people.length - shown.length}</span>}
    </div>
  )
}

// Latest: everything linked to the initiative, newest first, by kind; each item opens in place to be read (the email with its
// thread, the message with the ones before it, the meeting's notes, the document's card), with what Sam can do from it:
// work from it (picked for the actions above), email, document or decide from it, or open it where it lives. In the full
// list a tick or a cross says whether an item belongs here (it teaches the linker).
const KINDS: [string, string][] = [['', 'All'], ['meeting', 'Meetings'], ['mail', 'Mail'], ['chat', 'Messages'], ['doc', 'Documents']]

function Latest({ base, items, pins, onPin, onUse, onVerdict, openKey, setOpenKey }: {
  base: string; items: IniLink[]; pins: Pin[]; onPin: (l: IniLink) => void; onUse: (l: IniLink, p: Intent) => void
  onVerdict: (l: IniLink, v: 'confirmed' | 'rejected' | null) => void; openKey: string | null; setOpenKey: (k: string | null) => void
}) {
  const [kind, setKind] = useState('')
  const [all, setAll] = useState(false)
  const shown = items.filter((x) => !kind || x.type === kind)
  const list = all ? shown : shown.slice(0, 8)
  const counts = items.reduce<Record<string, number>>((m, x) => ({ ...m, [x.type]: (m[x.type] ?? 0) + 1 }), {})
  // arriving with ?open= (Back, a link): show that item, opened, wherever it is in the list
  const arrived = useRef(false)
  useEffect(() => {
    if (arrived.current || !openKey || !items.length) return
    arrived.current = true
    const i = items.findIndex((x) => x.key === openKey)
    if (i < 0) { setOpenKey(null); return }
    if (i >= 8) setAll(true)
    setTimeout(() => document.getElementById(`ini-${openKey}`)?.scrollIntoView({ block: 'center' }), 80)
  }, [items.length]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="mb-5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto flex items-baseline gap-2 text-[15px] font-semibold">Latest{items.length > 0 && <span className="text-[12.5px] font-normal text-ink3">{items.length} linked</span>}</h2>
        {items.length > 0 && <div role="radiogroup" aria-label="Kind" className="flex flex-wrap gap-1">
          {KINDS.filter(([k]) => !k || counts[k]).map(([k, l]) => <button key={k} role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
            className={cn('rounded-full px-2.5 py-0.5 text-[12px] transition-colors', kind === k ? 'bg-ink text-bg' : 'bg-panel2 text-ink2 hover:text-ink')}>
            {l}{k && <span className="ml-1 opacity-70">{counts[k]}</span>}</button>)}
        </div>}
      </div>
      {items.length === 0 ? <p className="text-[13px] text-ink2">Nothing linked yet.</p> : <div className="border border-line bg-panel">
        {list.map((x) => <ItemRow key={x.key} base={base} x={x} open={openKey === x.key} onToggle={() => setOpenKey(openKey === x.key ? null : x.key)}
          pinned={pins.some((p) => p.key === x.key)} onPin={() => onPin(x)} onUse={(p) => onUse(x, p)} onVerdict={all ? (v) => onVerdict(x, v) : undefined} />)}
      </div>}
      {shown.length > 8 && <button onClick={() => setAll(!all)} className="mt-1.5 inline-flex items-center gap-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink">
        {all ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}{all ? 'Show less' : `Show all ${shown.length}`}</button>}
    </section>
  )
}

// What does not change week to week, folded away
function About({ x }: { x: IniDetail }) {
  const [open, setOpen] = useState(false)
  const includes = [...new Set([...x.themes, ...x.merged])]
  if (!x.v2mom && !x.milestone && !includes.length && !x.profile_md && !x.owner) return null
  return (
    <section className="mb-5 border-t border-line pt-3">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-1 text-[13.5px] font-semibold">
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}About this initiative</button>
      {open && <div className="mt-2 space-y-1.5 text-[13px]">
        <div className="text-ink2">Weight {x.weight}{x.owner ? ` · ${x.owner}` : ''}</div>
        {x.v2mom && <div><span className="text-ink3">V2MOM: </span>{x.v2mom}</div>}
        {x.milestone && <div><span className="text-ink3">Next milestone: </span>{x.milestone}</div>}
        {includes.length > 0 && <div><span className="text-ink3">Includes: </span>{includes.join(' · ')}</div>}
        {x.profile_md && <div className="mt-2 border-l-2 border-line pl-3 text-[13px] [&_.md_p]:my-1"><Markdown>{x.profile_md}</Markdown></div>}
      </div>}
    </section>
  )
}

// The status: where the initiative stands, written by SleePO from everything linked to it (assist/initiatives.py
// draft_update), current at once. It is kept current from new material (graph memory, DESIGN-GRAPH-MEMORY.md; Sam,
// 17 Nov 2026): after the syncs SleePO reads what reached the bet since its status (directly, or through one of its tasks or
// topics) and rewrites it only when something changed (assist/graph_refresh.py), and "Updated … from new material" says what
// and from which item. The page itself rewrites a status at least 6 hours old with material SleePO has not read yet (the
// background run is off, over its daily ceiling or not done), never while that run is going. The old rule (over two days
// old and anything newer linked) stays only as a backstop after 7 days, for material linked too weakly to count.
// Under it, what SleePO suggests Sam does next: task suggestions under this initiative, added or dismissed here
// (Tasks: nothing is on his list until he adds it).
function StatusCard({ x, onChange }: { x: IniDetail; onChange: () => void }) {
  const qc = useQueryClient()
  const job = useJob(() => { onChange(); qc.invalidateQueries({ queryKey: ['tasks'] }); qc.invalidateQueries({ queryKey: ['graph-changes'] }) })
  const [hist, setHist] = useState(false)
  const [src, setSrc] = useState(false)
  const changes = useGraphChanges('initiative', x.id)
  const u = x.last_update
  const at = u?.approved_at ?? u?.drafted_at
  const ageDays = at ? (Date.now() - Date.parse(at)) / 86_400_000 : Infinity
  const fresh = changes.data?.unreviewed ?? 0   // new since the status and not read by SleePO's refresh yet
  const stale = !u || (fresh > 0 && ageDays >= 0.25 && !changes.data?.refreshing) || (ageDays > 7 && !!x.newest && x.newest > (at ?? ''))
  const auto = useRef(false)
  useEffect(() => { if (stale && !auto.current && !job.running) { auto.current = true; job.start(api.iniDraft(x.slug)) } }, [stale]) // eslint-disable-line react-hooks/exhaustive-deps
  const h = health(u?.health)
  const when = at ? (ageDays < 1 / 24 ? 'just now' : ageDays < 1 ? `${Math.max(1, Math.round(ageDays * 24))} h ago` : `${Math.round(ageDays)} d ago`) : ''
  return (
    <section className="mb-4 border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2">
        <b className="text-[14px]">Status</b>
        {u && <span className="inline-flex items-center gap-1.5 rounded-full bg-panel2 px-2 py-px text-[12px] font-medium"><span className={cn('size-2 rounded-full', h.dot)} />{h.label}</span>}
        <span className="inline-flex items-center gap-1 text-[12px] text-ink3"><Sparkles size={11} aria-hidden />{job.running ? 'SleePO is reading the latest material…' : u ? `by SleePO · ${when}${u.edited ? ' · edited' : ''}` : 'not written yet'}</span>
        <button onClick={() => job.start(api.iniDraft(x.slug))} disabled={job.running} title="Rewrite the status from the latest material, and suggest actions"
          className={cn(pill, 'ml-auto text-ink hover:bg-panel2')}>
          <RefreshCw size={13} className={cn(job.running && 'animate-spin')} />{job.running ? 'Updating…' : 'Refresh'}</button>
      </div>
      {u ? <div className={cn('px-4 py-3 transition-opacity', job.running && 'opacity-60')}>
        {u.status && <p className="text-[15px] leading-snug">{u.status}</p>}
        <div className="mt-2.5 grid gap-x-4 gap-y-1.5 text-[13.5px] sm:grid-cols-[110px_minmax(0,1fr)]">
          {([['progress', 'What changed'], ['blockers', 'Watch'], ['next', 'Next'], ['scope', 'Scope change']] as [keyof IniUpdate, string][])
            .filter(([k]) => u[k] && !/^none\.?$/i.test(String(u[k])))
            .map(([k, l]) => [<span key={k + 'l'} className="text-[12.5px] font-medium text-ink3">{l}</span>, <span key={k}>{String(u[k])}</span>])}
        </div>
        {u.sources.length > 0 && <div className="mt-2 text-[12px] text-ink3">
          <button onClick={() => setSrc(!src)} aria-expanded={src} className="inline-flex items-center gap-1 hover:text-ink">{src ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}Sources · {u.sources.length}</button>
          {src && <div className="mt-1.5 flex flex-wrap gap-1.5">{u.sources.map((s, i) => <a key={i} href={s.url} target={s.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="max-w-[260px] truncate rounded-full border border-line px-2 py-0.5 font-normal text-ink2 no-underline hover:border-ink">{s.label}</a>)}</div>}</div>}
        {!job.running && <NewSince kind="initiative" id={x.id} what="this status" data={changes.data} className="mt-1.5" />}
      </div> : <p className="px-4 py-3 text-[13.5px] text-ink2">{job.running ? 'Writing the first status from everything linked to this initiative. Usually a minute or two.' : 'No status yet.'}</p>}
      {job.job?.ok === false && <p className="px-4 pb-3 text-[12.5px] text-hot">{job.job.error}</p>}
      <SuggestedActions initiativeId={x.id} />
      {x.updates.length > 1 && <div className="border-t border-line px-4 py-2 text-[12.5px]">
        <button onClick={() => setHist(!hist)} className="inline-flex items-center gap-1 text-ink2 hover:text-ink">{hist ? <ChevronDown size={13} /> : <ChevronRight size={13} />}Earlier statuses · {x.updates.length - 1}</button>
        {hist && x.updates.slice(1).map((e) => <div key={e.id} className="mt-2 border-l-2 border-line pl-3"><div className="text-ink3">{day(e.approved_at)} · {health(e.health).label}</div><p className="text-[13px]">{e.status}</p></div>)}
      </div>}
    </section>
  )
}

// What SleePO suggests doing next on this initiative: its task suggestions (new tasks, and steps for tasks Sam has here).
// Add puts one on his list; dismiss tells SleePO not to suggest it again.
function SuggestedActions({ initiativeId }: { initiativeId: number }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['tasks'], queryFn: api.tasks })
  const set = useMutation({ mutationFn: ({ id, status }: { id: number; status: 'open' | 'dismissed' }) => api.taskPatch(id, { status }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['tasks'] }); qc.invalidateQueries({ queryKey: ['portfolio'] }) } })
  const mine = new Set((q.data?.tasks ?? []).filter((t) => t.initiative_id === initiativeId).map((t) => t.id))
  const [all, setAll] = useState(false)
  // newest first (the status run's own suggestions come first); three shown, the rest folded
  const list = (q.data?.suggestions ?? []).filter((t) => t.initiative_id === initiativeId || (t.parent_id != null && mine.has(t.parent_id))).sort((a, b) => b.id - a.id)
  if (!list.length) return null
  const parent = (id: number | null) => q.data?.tasks.find((t) => t.id === id)?.title
  return (
    <div className="border-t border-line px-4 py-3">
      <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold"><Sparkles size={13} aria-hidden className="text-ink2" />Suggested actions
        <span className="font-normal text-ink3">· add to your tasks, or dismiss</span></div>
      <div className="space-y-1.5">
        {list.slice(0, all ? 12 : 3).map((t) => {
          const steps = ((t as unknown as { subtasks?: { title: string }[] }).subtasks ?? []).map((s) => s.title)
          const busy = set.isPending && set.variables?.id === t.id
          return (
            <div key={t.id} className={cn('flex items-start gap-3 rounded-lg border border-line px-3 py-2 transition-opacity', busy && 'opacity-50')}>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium leading-snug">{t.title}{t.parent_id != null && <span className="font-normal text-ink3"> · step for {parent(t.parent_id) ?? 'a task'}</span>}</div>
                {t.why && <div className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-ink2" title={t.why}>{t.why}</div>}
                {steps.length > 0 && <div className="mt-0.5 text-[12px] text-ink3" title={steps.join('\n')}>{steps.length} step{steps.length > 1 ? 's' : ''}</div>}
              </div>
              <button onClick={() => set.mutate({ id: t.id, status: 'open' })} disabled={busy} className={cn(pill, 'shrink-0 bg-accent px-2.5 font-semibold text-onaccent hover:brightness-95')}><Check size={13} aria-hidden />Add</button>
              <button onClick={() => set.mutate({ id: t.id, status: 'dismissed' })} disabled={busy} aria-label="Dismiss" title="Dismiss: do not suggest it again"
                className="grid size-7 shrink-0 place-items-center rounded-full text-ink2 transition-colors hover:bg-panel2 hover:text-ink"><X size={14} aria-hidden /></button>
            </div>)
        })}
        {list.length > 3 && <button onClick={() => setAll(!all)} className="inline-flex items-center gap-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink">
          {all ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}{all ? 'Show fewer' : `Show ${Math.min(list.length, 12) - 3} more`}</button>}
        {all && list.length > 12 && <Link to="/tasks" className="ml-2 text-[12.5px]">{list.length - 12} more on the Tasks page</Link>}
      </div>
    </div>
  )
}
