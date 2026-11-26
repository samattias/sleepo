import { Network, Search } from 'lucide-react'
import { AgentTabs } from '@/components/AgentTabs'
import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, useNavigate } from '@tanstack/react-router'
import { api, type Person, type SoulUse } from '@/lib/api'
import { usePersisted } from '@/lib/util'
import { PersonView, type PersonTab } from '@/components/PersonPage'
import { RelationshipsHeader } from '@/views/companies'
import { FilterBar, FilterRow, Opt } from '@/components/FilterBar'
import { Avatar, Card, Chip, Chips, Empty, GroupRow, Loading, Markdown, Muted, Section, selectClass, Table, Tag } from '@/components/ui'
import { planDoc, profile } from '@/lib/profile'

// ---------------------------------------------------------------- Context
const CONTEXT_FILE = { me: 'context/me.md', company: 'context/company.md', soul: 'context/soul.md', cpo: 'context/cpo-soul.md', sleepo: 'context/assistant-soul.md' } as const

export function Context({ which }: { which: 'me' | 'company' | 'soul' }) {
  const docs = useQuery({ queryKey: ['docs'], queryFn: api.docs })
  const target = docs.data?.find((d) => d.path?.endsWith(CONTEXT_FILE[which]))
  const doc = useQuery({ queryKey: ['doc', target?.id], queryFn: () => api.doc(target!.id), enabled: !!target })
  const related = which === 'me' ? [planDoc()[0], 'context/strategy.md', 'context/preferences.md'].map((p) => docs.data?.find((d) => d.path?.endsWith(p))).filter(Boolean) : []
  if (!docs.data || (target && !doc.data)) return <Loading />
  if (!target) return <Empty>Not captured yet. Ask Claude to draft it.</Empty>
  return (
    <div>
      <Muted className="mb-2">Updated {target.meta?.updated ?? target.mtime} · <code>{target.path}</code></Muted>
      {related.length > 0 && <Chips>{related.map((d) => <Link key={d!.id} to="/explore/library/$" params={{ _splat: d!.id }}><Chip>{d!.title}</Chip></Link>)}</Chips>}
      <Card className="p-5"><Markdown>{doc.data!.md ?? ''}</Markdown></Card>
    </div>
  )
}

// The "Me" entry is Sam's own person page: same ontology as everyone else, plus his context documents.
export function MeRedirect() {
  const q = useQuery({ queryKey: ['people'], queryFn: api.people })
  const me = q.data?.find((p) => p.status === 'me')
  if (!q.data) return <Loading />
  return me ? <Navigate to="/people/$id" params={{ id: me.id }} replace /> : <Context which="me" />
}

const meDocs = (): [string, string][] => [planDoc(), ['context/strategy.md', 'Strategy frame'], ['context/preferences.md', 'Writing & meeting preferences']]

// The "Calendar and meetings" section of preferences.md, shown on the Me page.
function MeetingPrefs() {
  const docs = useQuery({ queryKey: ['docs'], queryFn: api.docs })
  const prefs = docs.data?.find((d) => d.path?.endsWith('context/preferences.md'))
  const doc = useQuery({ queryKey: ['doc', prefs?.id], queryFn: () => api.doc(prefs!.id), enabled: !!prefs })
  const sec = (doc.data?.md ?? '').match(/## Calendar and meetings[^\n]*\n([\s\S]*?)(?=\n## |$)/)
  if (!sec) return null
  return <>
    <Section right={prefs && <Link to="/explore/library/$" params={{ _splat: prefs.id }} className="text-[12.5px] font-normal">Edit in preferences →</Link>}>Calendar and meetings</Section>
    <Card className="mb-2 p-5"><Markdown>{sec[1].trim()}</Markdown></Card>
  </>
}

function MyContext() {
  const docs = useQuery({ queryKey: ['docs'], queryFn: api.docs })
  const meDoc = docs.data?.find((d) => d.path?.endsWith(CONTEXT_FILE.me))
  const doc = useQuery({ queryKey: ['doc', meDoc?.id], queryFn: () => api.doc(meDoc!.id), enabled: !!meDoc })
  if (!docs.data) return <Loading />
  const linked = meDocs().map(([path, label]) => ({ label, d: docs.data!.find((d) => d.path?.endsWith(path)) })).filter((x) => x.d)
  return <>
    <Section>Your context</Section>
    <div className="mb-2 grid gap-3 sm:grid-cols-3">
      {linked.map(({ label, d }) => <Link key={d!.id} to="/explore/library/$" params={{ _splat: d!.id }} className="block border border-line bg-panel p-4 text-ink no-underline hover:border-ink">
        <b className="text-[14px]">{label}</b><div className="mt-1 text-[12.5px] text-ink3">updated {d!.meta?.updated ?? d!.mtime}</div></Link>)}
    </div>
    <MeetingPrefs />
    <Section>Profile</Section>
    <Card className="p-5">{doc.data ? <Markdown>{(doc.data.md ?? '').replace(/^# .*\n+/, '')}</Markdown> : meDoc ? <Loading /> : <span className="text-ink3">Not captured yet. Ask Claude to draft it.</span>}</Card>
  </>
}

// The company page: Acme as an organisation node, with its two context documents as tabs —
// Overview (what is true on paper, company.md) and Soul (how things actually happen, soul.md).
// System › Soul: the company soul (how Acme actually works), the CPO soul (what good product leadership looks like, the
// standard SleePO holds Sam to) and SleePO's own soul (how the assistant operates). Under each, which agents read it
// and how (GET /api/souls, from assist/soul.py), so the page shows what actually reaches each prompt.
const soulTabs = () => [['company', 'Company', '/soul'], ['cpo', profile().role_short || 'Role', '/soul/cpo'], ['sleepo', 'SleePO', '/soul/sleepo']] as const   // cpo: the user's role soul
const SOUL_FILE = { company: CONTEXT_FILE.soul, cpo: CONTEXT_FILE.cpo, sleepo: CONTEXT_FILE.sleepo } as const
const HOW: Record<SoulUse['how'], string> = { carried: 'In its prompt', reads: 'Reads the page itself', inline: 'Own rules', summary: 'Through CLAUDE.md' }

function SoulUsers({ tab }: { tab: keyof typeof SOUL_FILE }) {
  const q = useQuery({ queryKey: ['souls'], queryFn: api.souls, retry: false })
  const rows = q.data?.[tab]?.used_by ?? []
  if (!rows.length) return null
  return <>
    <Section>Who reads this page</Section>
    <Table head={<><th>Agent</th><th>How</th><th>What it gets</th><th className="text-right">Characters</th></>}>
      {rows.map((u, i) => (
        <tr key={i}>
          <td className="font-medium">{u.label}</td>
          <td>{HOW[u.how]}</td>
          <td>{u.missing.length > 0
            ? <Tag tone="pending">Not found: {u.missing.join(', ')}. Carrying the whole page.</Tag>
            : u.how === 'inline' || u.how === 'summary' ? <span className="text-ink2">{u.note}</span> : u.sections.join(' · ')}</td>
          <td className="text-right tabular-nums">{u.chars != null ? u.chars.toLocaleString() : ''}</td>
        </tr>))}
    </Table>
    <Muted className="mt-2">Agents that run without tools cannot open files, so the text goes into their prompt. Rename a section heading and the
      agent falls back to the whole page; this table says when that happens.</Muted>
  </>
}

export function SoulPage({ tab }: { tab: keyof typeof SOUL_FILE }) {
  const docs = useQuery({ queryKey: ['docs'], queryFn: api.docs })
  const cur = docs.data?.find((d) => d.path?.endsWith(SOUL_FILE[tab]))
  const doc = useQuery({ queryKey: ['doc', cur?.id], queryFn: () => api.doc(cur!.id), enabled: !!cur })
  if (!docs.data) return <Loading />
  return (
    <div>
      <AgentTabs active="soul" />
      <div role="tablist" aria-label="Soul page" className="mb-3 inline-flex rounded-full bg-panel2 p-0.5">
        {soulTabs().map(([k, label, to]) => (
          <Link key={k} to={to} role="tab" aria-selected={tab === k} className={`rounded-full px-3 py-1 text-[13px] font-medium no-underline transition-colors ${tab === k ? 'bg-panel text-ink shadow-sm' : 'text-ink2 hover:text-ink'}`}>{label} soul</Link>))}
      </div>
      {!cur ? <Empty>Not captured yet. Ask Claude to draft it.</Empty> : !doc.data ? <Loading /> : <>
        <Card className="p-5"><Markdown>{doc.data.md ?? ''}</Markdown></Card>
        <Muted className="mt-2.5">Updated {cur.meta?.updated ?? cur.mtime} · <code>{cur.path}</code></Muted>
      </>}
      <SoulUsers tab={tab} />
    </div>
  )
}

// ---------------------------------------------------------------- Calendar
// ---------------------------------------------------------------- People
const AFF: [string, string][] = [['employee', 'Employees'], ['partner', 'Partners'], ['customer', 'Customers'], ['investor', 'Investors & board'], ['advisor', 'Advisors'], ['vendor', 'Vendors'], ['former employee', 'Former employees'], ['unclassified', 'Unclassified']]
const affTone = (a: string) => (a === 'employee' ? 'good' : a === 'former employee' || a === 'unclassified' ? 'plain' : 'pending') as 'good' | 'pending' | 'plain'

const ago = (iso?: string) => {
  if (!iso) return ''
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  return d <= 0 ? 'today' : d === 1 ? 'yesterday' : d < 14 ? `${d}d ago` : d < 60 ? `${Math.round(d / 7)}w ago` : `${Math.round(d / 30)}mo ago`
}
const DOT: Record<string, string> = { good: 'bg-accent ring-1 ring-ink/20', pending: 'bg-hot', plain: 'border border-ink3' }
const Kind = ({ p }: { p: Pick<Person, 'affiliation' | 'org'> }) => (
  <span className="inline-flex items-center gap-1.5"><span aria-hidden className={`size-1.5 rounded-full ${DOT[affTone(p.affiliation)]}`} />{p.affiliation}{p.org && p.affiliation !== 'employee' ? ` · ${p.org}` : ''}</span>)

export function People() {
  const q = useQuery({ queryKey: ['people'], queryFn: api.people })
  const nav = useNavigate()
  const [f, setF] = usePersisted('assist-v2-pf', { scope: 'all', dept: '', q: '', sort: 'org' })
  const P = q.data ?? []
  if (!q.data) return <Loading />
  const open = (p: Person) => p.open_items ?? 0
  const cnt = (k: string) => k === 'all' ? P.length : k === 'myorg' ? P.filter((p) => p.my_org).length : k === 'open' ? P.filter((p) => open(p) > 0).length : P.filter((p) => p.affiliation === k).length
  let list = P.filter((p) => f.scope === 'all' || (f.scope === 'myorg' ? p.my_org : f.scope === 'open' ? open(p) > 0 : p.affiliation === f.scope))
  if (f.dept) list = list.filter((p) => p.department === f.dept)
  if (f.q) { const re = new RegExp(f.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'); list = list.filter((p) => re.test([p.name, p.title, p.department, p.location, p.manager, p.org].join(' '))) }
  const sorters: Record<string, (a: Person, b: Person) => number> = {
    name: (a, b) => a.name.localeCompare(b.name), dept: (a, b) => (a.department || '~').localeCompare(b.department || '~') || a.name.localeCompare(b.name),
    meetings: (a, b) => b.meetings - a.meetings, open: (a, b) => open(b) - open(a) || b.meetings - a.meetings,
    contact: (a, b) => (b.last_contact || '').localeCompare(a.last_contact || ''),
    org: (a, b) => Number(b.status === 'me') - Number(a.status === 'me') || Number(b.my_org) - Number(a.my_org) || open(b) - open(a) || (b.last_contact || '').localeCompare(a.last_contact || '') || a.name.localeCompare(b.name),
  }
  list = [...list].sort(sorters[f.sort] ?? sorters.org)
  const depts = [...new Set(P.filter((p) => p.affiliation === 'employee').map((p) => p.department).filter(Boolean))].sort()
  const grouped = f.sort === 'org'
  const scopes: [string, string][] = [['all', 'Everyone'], ['myorg', 'My org'], ['open', 'With open items'], ...AFF.filter(([k]) => k !== 'employee' && cnt(k))]
  const Th = ({ k, children, right, className = '' }: { k?: string; children: string; right?: boolean; className?: string }) =>
    <th className={`whitespace-nowrap ${k ? 'cursor-pointer select-none hover:text-ink' : ''} ${right ? 'text-right' : ''} ${className}`} onClick={() => k && setF({ ...f, sort: f.sort === k ? 'org' : k })}>{children}{f.sort === k && ' ↓'}</th>
  const row = (p: Person) => (
    <tr key={p.id} className="cursor-pointer hover:[&>td]:bg-panel2" onClick={() => nav({ to: '/people/$id', params: { id: p.id } })}>
      <td className="py-2"><span className="flex items-center gap-2.5"><Avatar p={p} size={30} />
        <span className="min-w-0"><span className="flex items-center gap-1.5 font-semibold">{p.name}{p.status === 'me' && <span className="text-[11.5px] font-normal text-ink2">you</span>}{p.my_org && p.status !== 'me' && <span title="in your org" className="size-1.5 rounded-full bg-accent ring-1 ring-ink/20" />}</span>
          <span className="block max-w-[340px] truncate text-[12.5px] text-ink2">{p.affiliation === 'employee' ? p.title : <Kind p={p} />}</span></span></span></td>
      <td className="text-[13px] max-md:hidden">{p.department}</td>
      <td className="text-[13px] max-lg:hidden">{p.manager}</td>
      <td className="text-[13px] text-ink2 max-xl:hidden">{p.location}</td>
      <td className="whitespace-nowrap text-[13px] text-ink2 max-md:hidden" title={p.last_contact || ''}>{ago(p.last_contact)}</td>
      <td className="text-right text-[13px] tabular-nums max-md:hidden">{p.meetings || ''}</td>
      <td className="text-right text-[13px] tabular-nums">{open(p) > 0 && <b className="text-hot">{open(p)}</b>}</td>
    </tr>)
  return (
    <div className="max-w-[1180px]">
      <RelationshipsHeader on="people" right={<Link to="/links" className="text-[13px]">Check links</Link>} />
      <FilterBar search={f.q} onSearch={(v) => setF({ ...f, q: v })} placeholder="Search name, title, location…"
        right={list.length === P.length ? `${P.length} people` : `${list.length} of ${P.length}`}
        tokens={[
          ...(f.scope !== 'all' ? [{ label: scopes.find(([k]) => k === f.scope)?.[1] ?? f.scope, onRemove: () => setF({ ...f, scope: 'all' }) }] : []),
          ...(f.dept ? [{ label: f.dept, onRemove: () => setF({ ...f, dept: '' }) }] : []),
        ]}
        onClear={() => setF({ ...f, scope: 'all', dept: '' })}>
        <FilterRow label="Who">{scopes.map(([k, l]) => <Opt key={k} on={f.scope === k} count={cnt(k)} onClick={() => setF({ ...f, scope: k })}>{l}</Opt>)}</FilterRow>
        <FilterRow label="Department">
          <select value={f.dept} onChange={(e) => setF({ ...f, dept: e.target.value })} aria-label="Department" className={selectClass}>
            <option value="">All departments</option>{depts.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </FilterRow>
      </FilterBar>
      <Table head={<><Th k="name">Name</Th><Th k="dept" className="max-md:hidden">Department</Th><Th className="max-lg:hidden">Reports to</Th><Th className="max-xl:hidden">Location</Th><Th k="contact" className="max-md:hidden">Last contact</Th><Th k="meetings" right className="max-md:hidden">Meetings</Th><Th k="open" right>Open items</Th></>}>
        {grouped ? AFF.map(([k, l]) => { const rows = list.filter((p) => p.affiliation === k); if (!rows.length) return null; return [
          <GroupRow key={k} cols={7}>{l} <span className="font-normal text-ink2">· {rows.length}</span></GroupRow>, ...rows.map(row)] }) : list.map(row)}
      </Table>
    </div>
  )
}

// One person: header, highlights and tabs in components/PersonPage.tsx; Sam's own page shows his context documents instead.
export function PersonPage({ id, tab }: { id: string; tab?: PersonTab }) {
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const nav = useNavigate()
  return <PersonView id={id} tab={tab} people={people.data ?? []} me={<MyContext />}
    onTab={(t) => nav({ to: '/people/$id', params: { id }, search: { tab: t === 'overview' ? undefined : t }, replace: true })} />
}

// ---------------------------------------------------------------- Library
// people first: they are the main entities, everything else is reached through them (DESIGN.md §3.1)
const LIB_ORDER = ['People', 'Context', 'Initiatives', 'Emery Yates', 'Product docs', 'Briefs', 'Weekly reviews', 'Commitments', 'Decisions', 'Analyses', 'Pulls', 'Digests', 'Drafts', 'Memory', 'System', 'Meetings']
export function Library({ id }: { id?: string }) {
  const docs = useQuery({ queryKey: ['docs'], queryFn: api.docs })
  const doc = useQuery({ queryKey: ['doc', id], queryFn: () => api.doc(id!), enabled: !!id })
  const [open, setOpen] = usePersisted('assist-v2-lib', { q: '' })
  if (!docs.data) return <Loading />
  const re = open.q ? new RegExp(open.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
  return (
    <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
      <nav className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-32px)] lg:overflow-auto">
        <label className="relative mb-1 block">
          <Search size={13} aria-hidden className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-ink3" />
          <input placeholder="Filter titles" aria-label="Filter titles" value={open.q} onChange={(e) => setOpen({ q: e.target.value })}
            className="w-full border border-line bg-panel py-1 pl-7 pr-2 text-[12.5px] text-ink outline-none placeholder:text-ink3 focus:border-ink" />
        </label>
        {LIB_ORDER.map((sec) => { const ds = docs.data!.filter((d) => d.section === sec && (!re || re.test(d.title))); if (!ds.length) return null; const lim = sec === 'Meetings' && !re ? 30 : 400; return (
          <div key={sec}><h4 className="mb-1 mt-3.5 text-[12.5px] font-semibold text-ink">{sec} · {ds.length}</h4>
            {ds.slice(0, lim).map((d) => <Link key={d.id} to="/explore/library/$" params={{ _splat: d.id }} title={d.title} className={`block truncate border-l-2 px-2 py-1 text-[13.5px] no-underline ${d.id === id ? 'border-accent bg-accentbg text-ink' : 'border-transparent'} ${d.id === id ? '' : 'text-ink hover:bg-panel2'}`}>{d.title}</Link>)}
            {ds.length > lim && <Link to="/meetings" className="block px-2 py-1 text-[13px] text-ink3">… all {ds.length} under Meetings</Link>}
          </div>) })}
      </nav>
      <Card className="p-5">
        {!id && <Empty>Pick a document on the left.</Empty>}
        {id && !doc.data && <Loading />}
        {doc.data && <><div className="mb-2 flex flex-wrap items-baseline gap-3"><Muted className="flex-1">{doc.data.section} / {doc.data.path}{doc.data.mtime && ` · ${doc.data.mtime}`}</Muted>
          {/^(m|p|i)-\d+$/.test(id!) && <Link to="/explore/graph" search={{ focus: id }} className="inline-flex items-center gap-1.5 border border-line px-2.5 py-1 text-[12.5px] font-medium text-ink no-underline hover:border-ink"><Network size={14} />Show in graph</Link>}</div>
          <Markdown base={doc.data.path}>{doc.data.md ?? ''}</Markdown></>}
      </Card>
    </div>
  )
}
